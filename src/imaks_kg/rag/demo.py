"""Demo UI server. Loopback-only by default; public deployment is opt-in via IMAKS_* environment variables.

No external web dependencies or automatic paid calls.
"""
import argparse
import collections
import hmac
import json
import os
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs
from . import live, vector as v, event_explain, agent

PAGE = Path(__file__).with_name('demo.html')

GENERATION_PATHS = ('/api/ask', '/api/explain-event', '/api/explain-incident', '/api/agent')
UPLOAD_PATHS = ('/api/analyses', '/api/analyses/import')


def _env_int(env, name):
    raw = (env.get(name) or '').strip()
    if not raw:
        return 0
    value = int(raw)
    if value < 0:
        raise ValueError(f'{name} must be >= 0')
    return value


class DeployConfig:
    """Opt-in public deployment settings. With no IMAKS_* variables the server stays loopback-only.

    IMAKS_BIND_HOST              listen address (default 127.0.0.1; use 0.0.0.0 inside a container)
    IMAKS_PUBLIC_HOSTS           comma-separated public host names served behind HTTPS (e.g. imaks.example.com)
    IMAKS_ACCESS_CODE            if set, generation requests must send it in X-Access-Code
    IMAKS_GENERATION_DAILY_LIMIT max accepted generation requests per UTC day, all clients (0 = unlimited)
    IMAKS_GENERATION_HOURLY_PER_IP  max accepted generation requests per client IP per hour (0 = unlimited)
    IMAKS_UPLOAD_HOURLY_PER_IP   max CSV/ZIP uploads per client IP per hour (0 = unlimited)
    IMAKS_TRUST_PROXY            1 when behind a reverse proxy that overwrites X-Forwarded-For (e.g. Caddy)
    """

    def __init__(self, bind_host='127.0.0.1', public_hosts=(), access_code='', daily_limit=0,
                 hourly_per_ip=0, upload_hourly_per_ip=0, trust_proxy=False):
        self.bind_host = bind_host
        self.public_hosts = tuple(h for h in public_hosts if h)
        for host in self.public_hosts:
            if '/' in host or ':' in host or not host.strip() == host:
                raise ValueError('IMAKS_PUBLIC_HOSTS takes bare host names such as imaks.example.com')
        self.access_code = access_code
        self.daily_limit = daily_limit
        self.hourly_per_ip = hourly_per_ip
        self.upload_hourly_per_ip = upload_hourly_per_ip
        self.trust_proxy = trust_proxy

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        return cls(bind_host=(env.get('IMAKS_BIND_HOST') or '127.0.0.1').strip(),
                   public_hosts=[h.strip().lower() for h in (env.get('IMAKS_PUBLIC_HOSTS') or '').split(',')],
                   access_code=env.get('IMAKS_ACCESS_CODE') or '',
                   daily_limit=_env_int(env, 'IMAKS_GENERATION_DAILY_LIMIT'),
                   hourly_per_ip=_env_int(env, 'IMAKS_GENERATION_HOURLY_PER_IP'),
                   upload_hourly_per_ip=_env_int(env, 'IMAKS_UPLOAD_HOURLY_PER_IP'),
                   trust_proxy=(env.get('IMAKS_TRUST_PROXY') or '').strip() == '1')

    def allowed_hosts(self, port):
        return {f'127.0.0.1:{port}'} | set(self.public_hosts)

    def allowed_origins(self, port):
        return {f'http://127.0.0.1:{port}'} | {f'https://{h}' for h in self.public_hosts}


class Limiter:
    """In-memory request budget. Restarting the server resets the counters."""

    def __init__(self, daily_limit=0, hourly_per_ip=0, clock=time.time):
        self.daily_limit, self.hourly_per_ip, self.clock = daily_limit, hourly_per_ip, clock
        self.lock = threading.Lock()
        self.day, self.day_count = None, 0
        self.per_ip = collections.defaultdict(collections.deque)

    def take(self, ip):
        """Reserve one request. Returns None when accepted, otherwise 'daily' or 'hourly'."""
        now = self.clock()
        with self.lock:
            day = time.strftime('%Y-%m-%d', time.gmtime(now))
            if day != self.day:
                self.day, self.day_count = day, 0
            window = self.per_ip[ip]
            while window and window[0] <= now - 3600:
                window.popleft()
            if self.daily_limit and self.day_count >= self.daily_limit:
                return 'daily'
            if self.hourly_per_ip and len(window) >= self.hourly_per_ip:
                return 'hourly'
            self.day_count += 1
            window.append(now)
            return None

    def remaining_today(self):
        if not self.daily_limit:
            return None
        with self.lock:
            today = time.strftime('%Y-%m-%d', time.gmtime(self.clock()))
            used = self.day_count if self.day == today else 0
            return max(0, self.daily_limit - used)


def detection_presentation():
    from ..detection.rules import OUT
    seal = v.read(OUT/'complete.json')
    for name, checksum in seal.items():
        if Path(name).name != name or v.digest((OUT/name).read_bytes()) != checksum:
            raise ValueError('Detector artifact integrity mismatch')
    registry = v.read(OUT/'rules.json')
    rules = {r['id']: r for r in registry['rules']}
    return {'summary': v.read(OUT/'summary.json'), 'policy': registry['policy'],
            'events': [dict(e, rule=rules[e['rule_id']]) for e in v.read(OUT/'events.json')]}


def incident_presentation(store=None):
    """Rule-engine incidents (sealed run + overlay). Selectable next to the v1 detections."""
    from . import incident_tools
    store = store or incident_tools.IncidentStore()
    return {'source': 'rule_engine', 'lock': store.lock(), 'incidents': store.incidents,
            'correlations': store.correlations, 'warnings': incident_tools.WARNINGS}


def saved_run(run_id):
    if not run_id or any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for ch in run_id):
        raise ValueError('Invalid run ID')
    path = live.LIVE_ROOT/run_id
    if path.resolve().parent != live.LIVE_ROOT.resolve():
        raise ValueError('Invalid run path')
    return path


def presentation(path):
    if (path/'agent_lock.json').is_file():
        a=v.read(path/'answer.json');lock=v.read(path/'agent_lock.json')
        trace=v.read(path/'tools/trace.json') if (path/'tools/trace.json').is_file() else {'steps':[], 'evidence_tokens':0}
        edges=a['graph_paths'];nodes=sorted({str(e[k]) for e in edges for k in ('s','o')})
        tokens=sum(x.get('usage',{}).get('total_tokens',0) for x in a['usage'] if x['stage']!='embedding')
        xai=dict(a.get('xai',{}))
        xai.setdefault('claim_binding', {'status':'not_recorded','scope':'historical_or_other_agent','published':False})
        return {'id':path.name,'question':v.read(path/'input.json')['question'],'answer':a['answer'],
                'model':lock['config']['generation_model'],'usage':{'total_tokens':tokens},
                'context_tokens':a.get('xai',{}).get('context_tokens',trace['evidence_tokens']),
                'tool_evidence_tokens':trace['evidence_tokens'],'sources':a['sources'],
                'warnings':a['limitations'],'uncovered_documents':[], 'visited_nodes':nodes,
                'edges':edges,'source_links':{},'card_nodes':[], 'source_reasons':{},
                'agent_status':a['status'],'agent_steps':trace['steps'],'candidate_ids':a['candidate_ids'],
                'xai':xai,'verification':a.get('verification',[]), 'claims':a.get('claims',[])}
    a=v.read(path/'answer.json');r=v.read(path/'retrieval.json')
    # Return a defined UI payload, never credentials, raw requests or arbitrary files.
    return {'id':path.name,'question':a['question'],'answer':a['answer'],
            'model':a['returned_model'],'usage':a.get('usage',{}),
            'embedding_usage':a.get('embedding_api',{}).get('usage',{}),
            'embedding_cache_hit':a.get('embedding_api',{}).get('cache_hit'),
            'context_tokens':r['context_tokens'], 'sources':a['retrieved_sources'],
            'warnings':a['warnings'],'uncovered_documents':r['uncovered_explicit_documents'],
            'visited_nodes':r['visited_nodes'],'edges':r['traversed_edges'],
            'source_links':r['source_links'],'card_nodes':r['graph_nodes'],
            'source_reasons':r['source_candidate_reasons']}


def make_server(port=8765, answer=live.answer, explain=event_explain.answer, agent_answer=agent.answer,
                explain_incident=event_explain.answer_incident, page=PAGE, hidden_run_ids=(),
                incident_store_factory=None, agent_options=None, team_config=None, generation_enabled=True, analysis_service=None,
                deploy=None):
    # SHACL/SPARQL parsing uses deeply nested calls. Windows' default worker
    # stack can exhaust while loading/parsing it for the first upload.
    if analysis_service is not None and os.name=='nt' and threading.stack_size()<8*1024*1024:
        threading.stack_size(8*1024*1024)
    token=secrets.token_urlsafe(32);busy=threading.Lock()
    deploy=deploy or DeployConfig.from_env()
    generation_budget=Limiter(deploy.daily_limit,deploy.hourly_per_ip)
    upload_budget=Limiter(0,deploy.upload_hourly_per_ip)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,data,kind='application/json; charset=utf-8',download_name=None):
            body=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            if download_name is not None:self.send_header('Content-Disposition','attachment; filename="'+download_name+'"')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(body)
        def local(self):
            # Name kept for compatibility: loopback host, or an explicitly configured public host.
            return self.headers.get('Host','').lower() in deploy.allowed_hosts(self.server.server_port)
        def client_ip(self):
            if deploy.trust_proxy:
                forwarded=[part.strip() for part in self.headers.get('X-Forwarded-For','').split(',') if part.strip()]
                if forwarded:return forwarded[-1]
            return self.client_address[0]
        def over_budget(self,limiter):
            reason=limiter.take(self.client_ip())
            if reason is None:return False
            message=('오늘 사용할 수 있는 질문 수를 모두 사용했습니다. 내일 다시 시도해 주세요.' if reason=='daily'
                     else '요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.')
            self.reply(429,{'error':message,'code':'rate_limited_'+reason})
            return True
        def do_GET(self):
            if not self.local():return self.reply(403,{'error':'로컬 주소로 접속해 주세요.'})
            path=urlparse(self.path).path
            if path=='/':
                return self.reply(200,page.read_text(encoding='utf-8').replace('__TOKEN__',token).encode(),'text/html; charset=utf-8')
            if path=='/api/history':
                rows=[]
                visible=(p for p in live.LIVE_ROOT.glob('*/answer.json') if p.parent.name not in hidden_run_ids)
                for p in sorted(visible,key=lambda p:p.stat().st_mtime,reverse=True)[:50]:
                    a=v.read(p);question=a.get('question') or v.read(p.parent/'input.json')['question']
                    rows.append({'id':p.parent.name,'question':('Agent · ' if (p.parent/'agent_lock.json').exists() else '')+question,
                                 'integration':a.get('integration',{})})
                return self.reply(200,rows)
            if path=='/api/session':
                data={'csrf_token':token,'generation_enabled':generation_enabled}
                if analysis_service is not None:data['analysis_enabled']=True
                if generation_enabled and deploy.access_code:data['access_code_required']=True
                remaining=generation_budget.remaining_today()
                if generation_enabled and remaining is not None:data['generation_remaining_today']=remaining
                return self.reply(200,data)
            if analysis_service is not None and (path=='/api/analyses' or path.startswith('/api/analyses/')):
                from .sensor_analysis import InputError
                try:
                    if path=='/api/analyses':return self.reply(200,analysis_service.list())
                    parts=unquote(path[len('/api/analyses/'):]).split('/')
                    analysis_id=parts[0]
                    analysis_service.folder(analysis_id)
                    if len(parts)==1:return self.reply(200,analysis_service.summary(analysis_id))
                    if len(parts)==2 and parts[1]=='export':
                        return self.reply(200,analysis_service.export_bundle(analysis_id),'application/zip',analysis_id+'.zip')
                    if len(parts)==2 and parts[1]=='series':
                        query=parse_qs(urlparse(self.path).query,keep_blank_values=True)
                        if (set(query)-{'sensor_id','start','end','offset','limit','include_warmup'} or
                            any(len(values)!=1 for values in query.values()) or not query.get('sensor_id',[''])[0]):
                            raise InputError('invalid_series_query','센서 ID와 조회 인자를 확인해 주세요.')
                        warmup=query.get('include_warmup',['false'])[0]
                        if warmup not in ('true','false'):raise InputError('invalid_warmup_flag','include_warmup은 true 또는 false여야 합니다.')
                        result=analysis_service.series(analysis_id,query['sensor_id'][0],start=query.get('start',[None])[0],
                            end=query.get('end',[None])[0],offset=int(query.get('offset',['0'])[0]),limit=int(query.get('limit',['2000'])[0]),
                            include_warmup=warmup=='true')
                        return self.reply(200,result)
                    if len(parts)==3 and parts[1]=='incidents':return self.reply(200,analysis_service.detail(analysis_id,parts[2]))
                    return self.reply(404,{'error':'분석 조회 경로를 확인해 주세요.'})
                except InputError as error:return self.reply(409 if error.code=='analysis_not_ready' else 400,{'error':str(error),'code':error.code})
                except FileNotFoundError:return self.reply(404,{'error':'저장된 분석을 찾을 수 없습니다.'})
                except (ValueError,KeyError,TypeError):return self.reply(400,{'error':'조회 형식 또는 분석 자료의 무결성을 확인할 수 없습니다.'})
            if path=='/api/team-config' and team_config is not None:
                return self.reply(200,team_config())
            if path=='/api/detections':
                try:return self.reply(200,detection_presentation())
                except (ValueError,FileNotFoundError):return self.reply(503,{'error':'탐지 결과가 없거나 무결성 검사를 통과하지 못했습니다.'})
            if path=='/api/incidents':
                try:
                    profile=parse_qs(urlparse(self.path).query).get('profile',['main_v3_1'])[0]
                    store=incident_store_factory(profile) if incident_store_factory is not None else None
                    return self.reply(200,incident_presentation(store))
                except (ValueError,FileNotFoundError):return self.reply(503,{'error':'룰 엔진 사건 결과가 없거나 무결성 검사를 통과하지 못했습니다.'})
            if path.startswith('/api/decision-evidence/'):
                from . import decision_evidence
                try:
                    run=saved_run(unquote(path[len('/api/decision-evidence/'):]))
                    return self.reply(200,decision_evidence.for_saved_run(run))
                except FileNotFoundError:return self.reply(404,{'error':'저장된 사건 근거를 찾을 수 없습니다.'})
                except (ValueError,KeyError,TypeError):return self.reply(400,{'error':'사건 근거와 봉인이 일치하는 저장 실행만 점검할 수 있습니다.'})
            if path.startswith('/api/claim-catalog/'):
                from . import claim_binding
                try:
                    run=saved_run(unquote(path[len('/api/claim-catalog/'):]))
                    return self.reply(200,claim_binding.catalog_for_saved_run(run))
                except FileNotFoundError:return self.reply(404,{'error':'저장된 사건 근거를 찾을 수 없습니다.'})
                except (ValueError,KeyError,TypeError):return self.reply(400,{'error':'사건 근거와 봉인이 일치하는 실행만 주장 목록을 만들 수 있습니다.'})
            if path.startswith('/api/claim-paths/'):
                from . import evidence_paths
                try:
                    run=saved_run(unquote(path[len('/api/claim-paths/'):]))
                    return self.reply(200,evidence_paths.for_saved_run(run))
                except FileNotFoundError:return self.reply(404,{'error':'저장된 사건 근거를 찾을 수 없습니다.'})
                except (ValueError,KeyError,TypeError):return self.reply(400,{'error':'사건 근거와 봉인이 일치하는 실행만 경로를 점검할 수 있습니다.'})
            if path.startswith('/api/rule-explanations/'):
                from . import rule_explanations
                try:
                    run=saved_run(unquote(path[len('/api/rule-explanations/'):]))
                    return self.reply(200,rule_explanations.for_saved_run(run))
                except FileNotFoundError:return self.reply(404,{'error':'저장된 사건 근거를 찾을 수 없습니다.'})
                except (ValueError,KeyError,TypeError):return self.reply(400,{'error':'사건 근거와 봉인이 일치하는 실행만 경계·종료를 점검할 수 있습니다.'})
            if path.startswith('/api/document-claims/'):
                from . import document_claims
                try:
                    run=saved_run(unquote(path[len('/api/document-claims/'):]))
                    return self.reply(200,document_claims.for_saved_run(run))
                except FileNotFoundError:return self.reply(404,{'error':'저장된 문서 검색 근거를 찾을 수 없습니다.'})
                except (ValueError,KeyError,TypeError):return self.reply(400,{'error':'고정 원문과 일치하는 검색 기록만 문서 주장 목록을 만들 수 있습니다.'})
            if path.startswith('/api/run/'):
                try:return self.reply(200,presentation(saved_run(unquote(path[len('/api/run/'):]))))
                except (ValueError,FileNotFoundError):return self.reply(404,{'error':'저장된 결과를 찾을 수 없습니다.'})
            self.reply(404,{'error':'Not found'})
        def do_POST(self):
            origin=self.headers.get('Origin')
            if (not self.local() or self.headers.get('X-Demo-Token')!=token or
                (origin is not None and origin not in deploy.allowed_origins(self.server.server_port))):
                return self.reply(403,{'error':'요청 출처를 확인할 수 없습니다.'})
            if analysis_service is not None and self.path in UPLOAD_PATHS and self.over_budget(upload_budget):return
            if self.path=='/api/analyses/import' and analysis_service is not None:
                from .sensor_analysis import InputError
                from .analysis_archive import MAX_ZIP_BYTES
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=MAX_ZIP_BYTES:return self.reply(413,{'error':'묶음은 1바이트~32 MiB여야 합니다.'})
                    if self.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/zip':
                        return self.reply(415,{'error':'application/zip을 사용해 주세요.'})
                    self.connection.settimeout(15);body=self.rfile.read(size);self.connection.settimeout(None)
                    if len(body)!=size:raise InputError('incomplete_body','묶음 본문이 선언된 크기보다 짧습니다.')
                    return self.reply(200,analysis_service.import_bundle(body))
                except InputError as error:return self.reply(409 if error.code in ('analysis_conflict','dependency_mismatch') else 400,{'error':str(error),'code':error.code})
                except TimeoutError:return self.reply(408,{'error':'묶음 전송 시간이 초과됐습니다.'})
                except (ValueError,KeyError,TypeError,FileNotFoundError):return self.reply(400,{'error':'분석 묶음 또는 기존 런타임 자료를 확인해 주세요.'})
            if self.path=='/api/analyses' and analysis_service is not None:
                from .sensor_analysis import InputError, MAX_BYTES
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=MAX_BYTES:return self.reply(413,{'error':'입력 본문은 1바이트~4 MiB여야 합니다.'})
                    kind=self.headers.get('X-Input-Kind','uploaded_sensor_csv')
                    analysis_start=self.headers.get('X-Analysis-Start')
                    analysis_end=self.headers.get('X-Analysis-End')
                    content_type=self.headers.get('Content-Type','').split(';')[0].strip().lower()
                    self.connection.settimeout(15)
                    body=self.rfile.read(size)
                    self.connection.settimeout(None)
                    if len(body)!=size:raise InputError('incomplete_body','입력 본문이 선언된 크기보다 짧습니다.')
                    if content_type=='application/json':
                        data=json.loads(body)
                        if not isinstance(data,dict) or set(data)-{'csv','input_kind','analysis_start','analysis_end'} or not isinstance(data.get('csv'),str):
                            raise InputError('invalid_upload_json','csv 문자열과 선택적인 input_kind만 허용합니다.')
                        body=data['csv'].encode('utf-8');kind=data.get('input_kind',kind)
                        analysis_start=data.get('analysis_start',analysis_start);analysis_end=data.get('analysis_end',analysis_end)
                    elif content_type not in ('text/csv','application/csv'):
                        return self.reply(415,{'error':'text/csv 또는 application/json 입력을 사용해 주세요.'})
                except InputError as error:return self.reply(400,{'error':str(error),'code':error.code})
                except TimeoutError:return self.reply(408,{'error':'CSV 본문 전송 시간이 초과됐습니다.'})
                except (ValueError,TypeError,UnicodeError):return self.reply(400,{'error':'CSV 요청 형식을 확인해 주세요.'})
                try:return self.reply(202,analysis_service.submit(body,kind,analysis_start=analysis_start,analysis_end=analysis_end))
                except InputError as error:return self.reply(409 if error.code in ('analysis_queue_full','service_closed') else 400,{'error':str(error),'code':error.code})
                except Exception:return self.reply(500,{'error':'로컬 분석을 완료하지 못했습니다. 저장 기록을 확인해 주세요. 자동 재시도하지 않습니다.'})
            if self.path not in GENERATION_PATHS:return self.reply(404,{'error':'Not found'})
            if not generation_enabled:
                return self.reply(503,{'error':'읽기 전용 서버입니다. 저장된 결과 조회만 가능합니다.','code':'read_only'})
            if deploy.access_code and not hmac.compare_digest(self.headers.get('X-Access-Code','').encode(),deploy.access_code.encode()):
                return self.reply(401,{'error':'접근 코드가 올바르지 않습니다.','code':'access_code_required'})
            event_mode=self.path=='/api/explain-event'
            incident_mode=self.path=='/api/explain-incident'
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<=40000:raise ValueError()
                data=json.loads(self.rfile.read(n));q=data['event_id' if event_mode else 'incident_id' if incident_mode else 'question']
                if not isinstance(q,str) or not q.strip() or len(q.encode())>8000:raise ValueError()
                options={key:data[key] for key in (agent_options or {}) if key in data}
                if 'repair_incident' in options and type(options['repair_incident']) is not bool:raise ValueError()
                if any(value not in agent_options[key] for key,value in options.items()):raise ValueError()
                if event_mode and q not in {e['id'] for e in detection_presentation()['events']}:raise ValueError()
                if incident_mode and q not in {i['id'] for i in incident_presentation()['incidents']}:raise ValueError()
            except (ValueError,KeyError,TypeError):return self.reply(400,{'error':'질문은 1~8000 UTF-8 바이트로 입력해 주세요.'})
            if not busy.acquire(blocking=False):return self.reply(409,{'error':'다른 질문을 처리 중입니다. 완료 후 다시 시도해 주세요.'})
            if self.over_budget(generation_budget):
                busy.release();return
            run=saved_run('ui_'+uuid.uuid4().hex)
            try:
                if self.path=='/api/agent':agent_answer(q,run,**options)
                else:(explain if event_mode else explain_incident if incident_mode else answer)(q,run)
                self.reply(200,presentation(run))
            except Exception:
                self.reply(500,{'error':'처리를 완료하지 못했습니다. 자동 재시도하지 않습니다. 로컬 실행 기록을 확인해 주세요.','run_id':run.name})
            finally:busy.release()
    return ThreadingHTTPServer((deploy.bind_host,port),Handler)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args();server=make_server(args.port)
    print(f'IMAKS demo: http://127.0.0.1:{server.server_port} (Ctrl+C to stop)',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
