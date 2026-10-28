"""Loopback-only demo UI. No external web dependencies or automatic paid calls."""
import argparse
import json
import secrets
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote
from . import live, vector as v, event_explain, agent

PAGE = Path(__file__).with_name('demo.html')


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
        return {'id':path.name,'question':v.read(path/'input.json')['question'],'answer':a['answer'],
                'model':lock['config']['generation_model'],'usage':{'total_tokens':tokens},
                'context_tokens':trace['evidence_tokens'],'sources':a['sources'],
                'warnings':a['limitations'],'uncovered_documents':[], 'visited_nodes':nodes,
                'edges':edges,'source_links':{},'card_nodes':[], 'source_reasons':{},
                'agent_status':a['status'],'agent_steps':trace['steps'],'candidate_ids':a['candidate_ids']}
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


def make_server(port=8765, answer=live.answer, explain=event_explain.answer, agent_answer=agent.answer):
    token=secrets.token_urlsafe(32);busy=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,data,kind='application/json; charset=utf-8'):
            body=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(body)
        def local(self):
            return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
        def do_GET(self):
            if not self.local():return self.reply(403,{'error':'로컬 주소로 접속해 주세요.'})
            path=urlparse(self.path).path
            if path=='/':
                return self.reply(200,PAGE.read_text(encoding='utf-8').replace('__TOKEN__',token).encode(),'text/html; charset=utf-8')
            if path=='/api/history':
                rows=[]
                for p in sorted(live.LIVE_ROOT.glob('*/answer.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:50]:
                    a=v.read(p);question=a.get('question') or v.read(p.parent/'input.json')['question']
                    rows.append({'id':p.parent.name,'question':('Agent · ' if (p.parent/'agent_lock.json').exists() else '')+question})
                return self.reply(200,rows)
            if path=='/api/detections':
                try:return self.reply(200,detection_presentation())
                except (ValueError,FileNotFoundError):return self.reply(503,{'error':'탐지 결과가 없거나 무결성 검사를 통과하지 못했습니다.'})
            if path.startswith('/api/run/'):
                try:return self.reply(200,presentation(saved_run(unquote(path[len('/api/run/'):]))))
                except (ValueError,FileNotFoundError):return self.reply(404,{'error':'저장된 결과를 찾을 수 없습니다.'})
            self.reply(404,{'error':'Not found'})
        def do_POST(self):
            origin=self.headers.get('Origin')
            if (not self.local() or self.headers.get('X-Demo-Token')!=token or
                origin not in (None,f'http://127.0.0.1:{self.server.server_port}')):
                return self.reply(403,{'error':'요청 출처를 확인할 수 없습니다.'})
            if self.path not in ('/api/ask','/api/explain-event','/api/agent'):return self.reply(404,{'error':'Not found'})
            event_mode=self.path=='/api/explain-event'
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<=40000:raise ValueError()
                data=json.loads(self.rfile.read(n));q=data['event_id' if event_mode else 'question']
                if not isinstance(q,str) or not q.strip() or len(q.encode())>8000:raise ValueError()
                if event_mode and q not in {e['id'] for e in detection_presentation()['events']}:raise ValueError()
            except (ValueError,KeyError,TypeError):return self.reply(400,{'error':'질문은 1~8000 UTF-8 바이트로 입력해 주세요.'})
            if not busy.acquire(blocking=False):return self.reply(409,{'error':'다른 질문을 처리 중입니다. 완료 후 다시 시도해 주세요.'})
            run=saved_run('ui_'+uuid.uuid4().hex)
            try:
                (agent_answer if self.path=='/api/agent' else explain if event_mode else answer)(q,run)
                self.reply(200,presentation(run))
            except Exception:
                self.reply(500,{'error':'처리를 완료하지 못했습니다. 자동 재시도하지 않습니다. 로컬 실행 기록을 확인해 주세요.','run_id':run.name})
            finally:busy.release()
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args();server=make_server(args.port)
    print(f'IMAKS demo: http://127.0.0.1:{server.server_port} (Ctrl+C to stop)',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
