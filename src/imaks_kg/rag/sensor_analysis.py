"""Isolated CSV -> existing rule engine -> scoped XAI and paged chart data.

No labels, model calls, calibration fitting on uploads, or mutation of baseline data.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import io
import json
import math
import os
from pathlib import Path
import re
import threading
import uuid

from rdflib import RDF

from ..detection import rules
from ..detection.engine import compiler, config, overlay, run as engine
from . import comparison as c, decision_evidence as d, incident_tools, team_runtime, vector as v

VERSION = 'sensor-analysis-v2-20261115'
ROOT = v.REPO_ROOT / 'kg_build/sensor_analyses'
MAX_BYTES, MAX_ROWS, MAX_POINTS = 4 * 1024 * 1024, 20000, 10000
KINDS = ('historical_replay', 'uploaded_sensor_csv')
ID = r'ana-[0-9a-f]{32}'
WARNINGS = [
    '규칙 일치 후보이며 실제 고장 유형·원인·조치 효과를 확정하지 않습니다.',
    '계산용 선행 구간과 분석 대상을 구분합니다. 입력보다 앞선 이력은 알 수 없으며 시작·끝은 잘린 관측일 수 있습니다.',
    '이상 없음은 실행 가능한 규칙에서 후보가 없다는 뜻이며 설비 정상 인증이 아닙니다.',
    'historical_replay는 과거 자료 재입력 시연이며 새로운 미노출 성능 평가가 아닙니다.']


class InputError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def timestamp(value):
    try:
        at = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise InputError('invalid_timestamp', '시각은 ISO 형식이어야 합니다.') from None
    if at.tzinfo is not None or at.microsecond or at.second not in (0, 30):
        raise InputError('unsupported_time_grid', '프로젝트 현지시각 ISO 형식과 30초 격자를 사용해 주세요. 시간대 표기는 지원하지 않습니다.')
    return at


def schema(graph):
    result = {}
    for sensor in graph.subjects(RDF.type, c.IM.Sensor):
        sid = str(graph.value(sensor, c.IM.identifier))
        stations = list(graph.subjects(c.IM.hasSensor, sensor))
        if len(stations) != 1:
            continue
        station = stations[0]
        result[sid] = {'station_id': str(graph.value(station, c.IM.identifier)),
                       'zone': str(graph.value(station, c.IM.zone)),
                       'unit': str(graph.value(sensor, c.IM.unit)),
                       'sensor_type': str(graph.value(sensor, c.IM.sensorType))}
    return result


def parse_csv(raw, metadata):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise InputError('input_size_limit', 'CSV는 비어 있지 않아야 하며 4 MiB 이하여야 합니다.')
    try:
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''), strict=True)
        if reader.fieldnames != rules.FIELDS:
            raise InputError('invalid_columns', 'CSV 열은 timestamp,zone,station_id,sensor_id,sensor_type,value,unit 순서의 7개만 허용합니다.')
        groups, seen = defaultdict(list), set()
        for count, row in enumerate(reader, 1):
            if count > MAX_ROWS:
                raise InputError('row_limit', 'CSV는 최대 20,000행까지 지원합니다.')
            if set(row) != set(rules.FIELDS) or any(not isinstance(value, str) or not value.strip() or len(value) > 256 for value in row.values()):
                raise InputError('missing_or_extra_value', '빈 값·추가 셀·지나치게 긴 값은 지원하지 않습니다.')
            row = {key: value.strip() for key, value in row.items()}
            sid = row['sensor_id']
            if sid not in metadata:
                raise InputError('unknown_sensor', '고정 KG에 등록된 센서만 분석할 수 있습니다.')
            if any(row[key] != metadata[sid][key] for key in ('station_id', 'zone', 'unit', 'sensor_type')):
                raise InputError('sensor_metadata_mismatch', '센서의 공정·구역·유형·단위가 고정 KG와 다릅니다.')
            at = timestamp(row['timestamp'])
            row['timestamp'] = at.isoformat()
            key = sid, row['timestamp']
            if key in seen:
                raise InputError('duplicate_timestamp', '같은 센서의 중복 시각은 허용하지 않습니다.')
            seen.add(key)
            try:
                value = d.number(row['value'])
                if abs(value) > d.number('1e12') or not math.isfinite(float(value)):
                    raise ValueError('Numeric processing bound')
            except ValueError:
                raise InputError('invalid_value', '관측값은 결측이 없는 유한 숫자여야 하며 절댓값 1e12 이하여야 합니다.') from None
            groups[sid].append(row)
    except (UnicodeError, csv.Error):
        raise InputError('invalid_csv', 'UTF-8 CSV 형식을 확인해 주세요.') from None
    if not groups:
        raise InputError('empty_csv', 'CSV에 관측 행이 없습니다.')
    gaps, longest = [], {}
    for sid, rows in groups.items():
        rows.sort(key=lambda row: row['timestamp'])
        streak = longest[sid] = 1
        for a, b in zip(rows, rows[1:]):
            seconds = (timestamp(b['timestamp']) - timestamp(a['timestamp'])).total_seconds()
            if seconds != 30:
                gaps.append({'sensor_id': sid, 'after': a['timestamp'], 'before': b['timestamp'], 'missing_slots': int(seconds/30)-1})
                streak = 0
            streak += 1
            longest[sid] = max(longest[sid], streak)
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=rules.FIELDS, lineterminator='\n')
    writer.writeheader()
    for sid in sorted(groups):
        writer.writerows(groups[sid])
    return dict(groups), stream.getvalue().encode(), {'gaps': gaps, 'longest_contiguous_samples': longest}


def minimum_samples(rule, cfg):
    p, step = rule['params'], cfg['sample_seconds']
    kind = rule.get('executor')
    duration = int(float(p.get('duration_seconds', 0)) // step) + 2 if p.get('duration_seconds') else 1
    if p.get('op') == 'stuck_exact': return int(p['value']) + duration - 1
    if kind == 'slope': return int(p['window_min']*60/step) + int(p['readings']) - 1
    if kind == 'stuck_std': return int(p['window'])
    if kind == 'outside_run': return int(p['readings'])
    if kind == 'window_change': return int(p['window_min']*60/step) + cfg['smooth_samples']
    if kind == 'sustained_from_nominal': return int(p['min_minutes']*60/step) + 1
    return duration


def prepare_intervals(groups, metadata, analysis_start=None, analysis_end=None):
    first=min(rows[0]['timestamp'] for rows in groups.values())
    last=max(rows[-1]['timestamp'] for rows in groups.values())
    start,end=analysis_start or first,analysis_end or last
    if start<first or end>last or start>end:
        raise InputError('analysis_interval_outside_upload','분석 구간은 업로드에 기록된 시간 범위 안이어야 합니다.')
    original_rows=sum(map(len,groups.values()))
    processing={sid:[row for row in rows if row['timestamp']<=end] for sid,rows in groups.items()}
    processing={sid:rows for sid,rows in processing.items() if rows}
    if not any(start<=row['timestamp']<=end for rows in processing.values() for row in rows):
        raise InputError('empty_analysis_interval','분석 구간에 실제 관측값이 없습니다.')
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=rules.FIELDS,lineterminator='\n');writer.writeheader()
    for sid in sorted(processing):writer.writerows(processing[sid])
    processing,normalized,quality=parse_csv(stream.getvalue().encode(),metadata)
    sensors={}
    for sid,rows in processing.items():
        target=[i for i,row in enumerate(rows) if row['timestamp']>=start]
        prior=0
        if target:
            index=target[0]
            while index>0 and (timestamp(rows[index]['timestamp'])-timestamp(rows[index-1]['timestamp'])).total_seconds()==30:
                prior+=1;index-=1
        sensors[sid]={'warmup_samples':sum(row['timestamp']<start for row in rows),
                      'analysis_samples':len(target),'contiguous_prior_samples_at_first_target':prior,
                      'first_target_at':rows[target[0]]['timestamp'] if target else None,
                      'last_target_at':rows[target[-1]]['timestamp'] if target else None}
    intervals={'analysis':{'start':start,'end':end},'context':{
        'start':min(rows[0]['timestamp'] for rows in processing.values()),'end':max(rows[-1]['timestamp'] for rows in processing.values())},
        'upload':{'start':first,'end':last},'sensors':sensors,
        'excluded_after_analysis_end_rows':original_rows-sum(map(len,processing.values())),
        'scope':'prefix history is calculation context; observations after analysis end are never used'}
    return processing,normalized,quality,intervals


def in_interval(incident, interval):
    return incident['end']>=interval['start'] and incident['start']<=interval['end']


def incident_scope(incident, interval):
    if not in_interval(incident,interval):return 'warmup_only'
    return 'started_before_analysis' if incident['start']<interval['start'] else 'started_in_analysis'


def package_check(folder):
    seal = v.read(folder / 'complete.json')
    required = {'upload.csv', 'input.csv', 'input_manifest.json', 'calibration.json', 'summary.json',
                'run/complete.json', 'overlay/complete.json'}
    if not required <= set(seal):
        raise ValueError('Incomplete analysis package')
    for name, sha in seal.items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder.resolve()) or v.digest(path.read_bytes()) != sha:
            raise ValueError('Changed analysis package')
    return seal


class AnalysisStore(incident_tools.IncidentStore):
    def __init__(self, folder):
        self.folder = folder
        self.package_seal = package_check(folder)
        self.declared_input_source = v.read(folder/'input_manifest.json')['input_source']
        declared=self.declared_input_source
        origin=Path(declared['file'])
        if (declared['analysis_id']!=folder.name or origin.is_absolute() or '..' in origin.parts or
                '\\' in declared['file'] or not origin.parts or origin.parts[0]!='kg_build' or
                origin.name!='input.csv' or origin.parent.name!=folder.name):
            raise ValueError('Invalid declared analysis source')
        expected = (folder/'input.csv').relative_to(v.REPO_ROOT).as_posix()
        if declared['sha256'] != self.package_seal['input.csv']:
            raise ValueError('Input source outside this analysis')
        self.input_source={**declared,'file':expected}
        if declared['file']!=expected:
            self.input_source.update(origin_file=declared['file'],reference_resolution='hash_verified_local_restore')
        super().__init__(folder/'run', folder/'overlay')
        if v.read(self.run_dir/'params.json')['input_source'] != self.declared_input_source:
            raise ValueError('Run belongs to another input')
        self._groups = None

    def observation_rows(self, sensor_id):
        path = self.folder/'input.csv'
        if v.digest(path.read_bytes()) != self.input_source['sha256']:
            raise ValueError('Changed analysis observations')
        if self._groups is None:
            self._groups, _, _ = parse_csv(path.read_bytes(), schema(self.base))
        if sensor_id not in self._groups:
            raise InputError('sensor_not_in_analysis', '이 분석에 포함되지 않은 센서입니다.')
        return self._groups[sensor_id], self.input_source['sha256']

    def calibration_rows(self, sensor_id, recorded, cfg):
        receipt = v.read(self.folder/'calibration.json')
        path = (v.REPO_ROOT/receipt['params_file']).resolve()
        if not path.is_relative_to(v.REPO_ROOT.resolve()) or v.digest(path.read_bytes()) != receipt['params_sha256']:
            raise ValueError('Baseline calibration reference changed')
        baseline = v.read(path)
        if recorded != baseline['sigma_by_sensor'][sensor_id] or cfg['train_end'] != baseline['config']['train_end']:
            raise ValueError('Analysis calibration differs from sealed baseline')
        rows, sha = d.observations(sensor_id)
        if sha != receipt['input_sha256']:
            raise ValueError('Calibration observation hash changed')
        return rows, {**receipt, 'sensor_id': sensor_id, 'scope': 'pre-existing baseline, not fitted to upload'}


class AnalysisService:
    def __init__(self, root=ROOT, *, max_pending=3):
        self.root = Path(root).resolve()
        if not self.root.is_relative_to((v.REPO_ROOT/'kg_build').resolve()):
            raise ValueError('Analysis storage must stay inside local kg_build')
        if type(max_pending) is not int or not 1<=max_pending<=8:raise ValueError('Invalid queue capacity')
        self._slots=threading.BoundedSemaphore(max_pending)
        self._jobs_lock=threading.Lock()
        self._futures={}
        self._executor=None
        self._closed=False

    def _state(self, analysis_id, status, phase, **extra):
        file=self.folder(analysis_id)/'state.json'
        previous=v.read(file) if file.exists() else {}
        now=datetime.now(timezone.utc).isoformat()
        history=previous.get('phase_history',[])+[{'status':status,'phase':phase,'at_utc':now}]
        state={**previous,'analysis_id':analysis_id,'status':status,'phase':phase,
               'created_at_utc':previous.get('created_at_utc',now),'updated_at_utc':now,'phase_history':history,**extra}
        v.write(file,state)
        return state

    def _reserve(self, raw, input_kind, analysis_start=None, analysis_end=None):
        if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:raise InputError('input_size_limit','입력 크기를 확인해 주세요.')
        if input_kind not in KINDS:raise InputError('invalid_input_kind','입력 종류를 확인해 주세요.')
        if (analysis_start is None)!=(analysis_end is None):raise InputError('incomplete_interval','분석 시작과 끝을 함께 지정해 주세요.')
        if analysis_start is not None:
            analysis_start,analysis_end=timestamp(analysis_start).isoformat(),timestamp(analysis_end).isoformat()
            if analysis_start>analysis_end:raise InputError('reversed_interval','분석 시작이 끝보다 늦습니다.')
        aid='ana-'+uuid.uuid4().hex;folder=self.folder(aid);folder.mkdir(parents=True,exist_ok=False)
        (folder/'upload.csv').write_bytes(raw)
        v.write(folder/'request.json',{'input_kind':input_kind,'upload_sha256':v.digest(raw),
                                     'analysis_start':analysis_start,'analysis_end':analysis_end})
        self._state(aid,'queued','queued')
        return aid

    def _run(self, analysis_id, *, propagate=False):
        folder=self.folder(analysis_id)
        try:
            request=v.read(folder/'request.json');raw=(folder/'upload.csv').read_bytes()
            if v.digest(raw)!=request['upload_sha256']:raise ValueError('Queued upload changed')
            return self._execute(raw,request['input_kind'],analysis_id,
                                 analysis_start=request['analysis_start'],analysis_end=request['analysis_end'])
        except Exception as error:
            self._state(analysis_id,'failed','failed',error={'code':error.code if isinstance(error,InputError) else 'analysis_failed',
                'message':str(error) if isinstance(error,InputError) else '분석을 완료하지 못했습니다. 로컬 기록을 확인해 주세요.'})
            if propagate:raise
            return v.read(folder/'state.json')

    def create(self, raw, input_kind='uploaded_sensor_csv', *, analysis_start=None, analysis_end=None):
        aid=self._reserve(raw,input_kind,analysis_start,analysis_end)
        return self._run(aid,propagate=True)

    def submit(self, raw, input_kind='uploaded_sensor_csv', *, analysis_start=None, analysis_end=None):
        if not self._slots.acquire(blocking=False):raise InputError('analysis_queue_full','분석 대기열이 가득 찼습니다. 진행 중인 작업을 확인해 주세요.')
        aid=None
        try:
            with self._jobs_lock:
                if self._closed:raise InputError('service_closed','분석 서버가 종료 중입니다.')
                aid=self._reserve(raw,input_kind,analysis_start,analysis_end)
                if self._executor is None:
                    if os.name=='nt' and threading.stack_size()<8*1024*1024:threading.stack_size(8*1024*1024)
                    self._executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='imaks-analysis')
                future=self._executor.submit(self._run,aid)
                self._futures[aid]=future
            def done(_):
                with self._jobs_lock:self._futures.pop(aid,None)
                self._slots.release()
            future.add_done_callback(done)
            return {'analysis_id':aid,'status':'queued','phase':'queued','status_url':f'/api/analyses/{aid}','new_api_calls':0}
        except Exception:
            if aid is not None:self._state(aid,'failed','failed',error={'code':'queue_failed','message':'분석 작업을 시작하지 못했습니다.'})
            self._slots.release()
            raise

    def recover_interrupted(self):
        """Call once after binding the sole server for this storage root; never retry."""
        with self._jobs_lock:
            active=set(self._futures)
        recovered=[]
        for folder in self.root.glob('ana-*'):
            if not re.fullmatch(ID,folder.name) or folder.name in active:continue
            state_file=self.folder(folder.name)/'state.json'
            if state_file.exists() and v.read(state_file).get('status') in ('queued','processing'):
                self._state(folder.name,'interrupted','interrupted',error={'code':'server_restarted','message':'이전 서버 실행이 중단됐습니다. 자동 재실행하지 않습니다.'})
                recovered.append(folder.name)
        return recovered

    def close(self):
        with self._jobs_lock:self._closed=True;executor=self._executor
        if executor is not None:executor.shutdown(wait=True)

    def export_bundle(self, analysis_id):
        from .analysis_archive import export_bundle
        return export_bundle(self,analysis_id)

    def import_bundle(self, raw):
        from .analysis_archive import import_bundle
        return import_bundle(self,raw)

    def folder(self, analysis_id):
        if not isinstance(analysis_id, str) or not re.fullmatch(ID, analysis_id):
            raise InputError('invalid_analysis_id', '분석 ID 형식을 확인해 주세요.')
        folder = (self.root/analysis_id).resolve()
        if folder.parent != self.root:
            raise InputError('invalid_analysis_path', '허용되지 않은 분석 경로입니다.')
        return folder

    def store(self, analysis_id):
        if v.read(self.folder(analysis_id)/'state.json')['status']!='complete':
            raise InputError('analysis_not_ready','아직 완료되지 않은 분석입니다. 상태를 확인해 주세요.')
        return AnalysisStore(self.folder(analysis_id))

    def _execute(self, raw, input_kind, analysis_id, *, analysis_start=None, analysis_end=None):
        folder=self.folder(analysis_id)
        self._state(analysis_id,'processing','validating')
        if input_kind not in KINDS:
            raise InputError('invalid_input_kind', '입력 종류는 historical_replay 또는 uploaded_sensor_csv여야 합니다.')
        graph = c.load_graph()
        bundle, cfg = compiler.compile_ir(graph), config.load('v3_1')
        metadata = {sid:info for sid,info in schema(graph).items() if sid in bundle['sensors']}
        groups, normalized, quality = parse_csv(raw, metadata)
        groups,normalized,quality,intervals=prepare_intervals(groups,metadata,analysis_start,analysis_end)
        self._state(analysis_id,'processing','preparing_rules')
        base_store = team_runtime.store('main_v3_1')
        params_path = base_store.run_dir/'params.json'
        base_params = v.read(params_path)
        if v.read(base_store.run_dir/'ir.json')['kg_sha256'] != bundle['kg_sha256']:
            raise ValueError('Baseline calibration belongs to another KG')
        cfg = {key: value for key, value in cfg.items() if key != '_path'}
        skipped, eligible = [], []
        for rule in bundle['rules']:
            sid = rule['sensor_id']
            if sid not in groups: continue
            reason = None
            if rule['executor'] == 'slope' and (groups[sid][0]['timestamp'] < cfg['train_end'] or
                    base_params['sigma_by_sensor'][sid]['sigma'] <= 0):
                reason = 'baseline_unavailable_before_selected_window'
            elif quality['longest_contiguous_samples'][sid] < minimum_samples(rule, cfg):
                reason = 'insufficient_contiguous_samples'
            if reason:
                skipped.append({'ir_id':rule['ir_id'],'sensor_id':sid,'reason':reason})
            else: eligible.append(rule)
        pairs = [pair for pair in bundle['correlation_pairs'] if pair['cause_sensor'] in groups and pair['effect_sensor'] in groups]
        subset = {**bundle, 'rules':eligible, 'correlation_pairs':pairs,
                  'sensors':{sid:bundle['sensors'][sid] for sid in groups if sid in bundle['sensors']}}
        try:
            (folder/'upload.csv').write_bytes(raw)
            (folder/'input.csv').write_bytes(normalized)
            source = {'analysis_id':analysis_id,'file':(folder/'input.csv').relative_to(v.REPO_ROOT).as_posix(),
                      'sha256':v.digest(normalized),'input_kind':input_kind}
            manifest = {'version':VERSION,'analysis_id':analysis_id,'input_source':source,
                        'upload_sha256':v.digest(raw),'normalization':'UTF-8, trimmed cells, ISO naive timestamps, sensor/time sort; values not interpolated',
                        'sensor_ids':sorted(groups),'rows':sum(map(len,groups.values())), 'quality':quality,
                        'input_kind_is_caller_declared':True,'intervals':intervals,
                        'created_at_utc':datetime.now(timezone.utc).isoformat()}
            v.write(folder/'input_manifest.json',manifest)
            _, frozen_sha = d.observations(next(iter(groups)))
            receipt = {'params_file':params_path.relative_to(v.REPO_ROOT).as_posix(),
                       'params_sha256':v.digest(params_path.read_bytes()),'input_file':rules.INPUT,
                       'input_sha256':frozen_sha,'train_end':cfg['train_end']}
            v.write(folder/'calibration.json',receipt)
            sigmas = {sid:deepcopy(base_params['sigma_by_sensor'][sid]) for sid in groups}
            self._state(analysis_id,'processing','detecting')
            result, _ = engine.pipeline(groups, subset, cfg, sigmas=sigmas)
            if len(result['events']) > 10000 or len(result['incidents']) > 2000:
                raise InputError('result_size_limit','분석 결과가 너무 많습니다. 더 짧은 구간으로 나누어 주세요.')
            run = folder/'run';run.mkdir()
            v.write(run/'params.json',{'config':cfg,'config_file':'v3_1.json','sigma_by_sensor':sigmas,'input_source':source})
            v.write(run/'ir.json',subset)
            for key, name in engine.OUTPUT_FILES.items():v.write(run/name,result[key])
            summary = {'version':VERSION,'analysis_id':analysis_id,'status':'complete','input_kind':input_kind,
                       'rows':manifest['rows'],'sensors':sorted(groups),
                       'incidents':sum(in_interval(i,intervals['analysis']) for i in result['incidents']),
                       'alarms':sum(a['last_positive_at']>=intervals['analysis']['start'] for a in result['events']),
                       'processing_incidents':len(result['incidents']),'processing_alarms':len(result['events']),
                       'incidents_by_type':dict(Counter(i['anomaly_type'] for i in result['incidents'] if in_interval(i,intervals['analysis']))),
                       'intervals':intervals,
                       'scope':'v3.1 policy on this uploaded window; not independent accuracy or confirmed causes',
                       'coverage':{'eligible_rules':len(eligible),'skipped_rules':skipped,
                                   'excluded_pairs_missing_sensor':len(bundle['correlation_pairs'])-len(pairs),
                                   'unimplemented_rule_ids':[u['rule_id'] for u in bundle['unsupported']]},
                       'quality':quality,'input_source':source,'calibration':receipt,'warnings':WARNINGS,
                       'new_api_calls':0,'gold_loaded':False,'kg_sha256':bundle['kg_sha256']}
            summary['coverage']['start_boundary_checks']=[{
                'ir_id':rule['ir_id'],'required_prior_samples':minimum_samples(rule,cfg)-1,
                'available_contiguous_prior_samples':intervals['sensors'][rule['sensor_id']]['contiguous_prior_samples_at_first_target'],
                'sample_history_ready':intervals['sensors'][rule['sensor_id']]['first_target_at'] is not None and
                    intervals['sensors'][rule['sensor_id']]['contiguous_prior_samples_at_first_target']>=minimum_samples(rule,cfg)-1,
                'scope':'sample availability only; does not prove prior condition satisfaction or unseen history'} for rule in eligible]
            v.write(run/'summary.json',summary)
            v.write(run/'complete.json',{p.name:v.digest(p.read_bytes()) for p in run.iterdir() if p.is_file()})
            self._state(analysis_id,'processing','validating_graph')
            overlay.load(run,folder/'overlay',base=graph)
            self._state(analysis_id,'processing','sealing')
            v.write(folder/'summary.json',summary)
            v.write(folder/'complete.json',{p.relative_to(folder).as_posix():v.digest(p.read_bytes())
                    for p in folder.rglob('*') if p.is_file() and p.name!='state.json' and p!=folder/'complete.json'})
            self._state(analysis_id,'complete','complete')
            return self.summary(analysis_id)
        except Exception:raise

    def summary(self, analysis_id):
        folder = self.folder(analysis_id)
        state = v.read(folder/'state.json')
        if state['status'] != 'complete':return state
        store = self.store(analysis_id)
        result=v.read(folder/'summary.json')
        interval=result.get('intervals',{}).get('analysis')
        visible=[{**i,'window_scope':incident_scope(i,interval)} if interval else i for i in store.incidents
                 if interval is None or in_interval(i,interval)]
        ids={i['id'] for i in visible}
        return {**result,'input_source':store.input_source,'origin_input_source':store.declared_input_source,
                'job':state,'incident_items':visible,
                'history_incident_ids':[i['id'] for i in store.incidents if i['id'] not in ids],
                'correlation_candidates':[link for link in store.correlations if link['cause_incident'] in ids or link['effect_incident'] in ids],
                'endpoints':{
                    'series':f'/api/analyses/{analysis_id}/series',
                    'incident_template':f'/api/analyses/{analysis_id}/incidents/{{incident_id}}'}}

    def list(self):
        ids = sorted((p for p in self.root.glob('ana-*') if re.fullmatch(ID,p.name)),key=lambda p:p.stat().st_mtime,reverse=True)[:50]
        return {'items':[v.read(self.folder(p.name)/'state.json') for p in ids if (p/'state.json').is_file()], 'limit':50}

    def series(self, analysis_id, sensor_id, *, start=None, end=None, offset=0, limit=2000, include_warmup=False):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= MAX_POINTS:
            raise InputError('invalid_pagination','offset는 0 이상, limit는 1~10,000이어야 합니다.')
        if type(include_warmup) is not bool:raise InputError('invalid_warmup_flag','include_warmup은 boolean이어야 합니다.')
        if start: start=timestamp(start).isoformat()
        if end: end=timestamp(end).isoformat()
        if start and end and start>end:raise InputError('reversed_interval','시작 시각이 끝 시각보다 늦습니다.')
        store=self.store(analysis_id)
        rows,sha=store.observation_rows(sensor_id)
        manifest=v.read(store.folder/'input_manifest.json')
        intervals=manifest.get('intervals')
        if intervals:
            lower=intervals['context']['start'] if include_warmup else intervals['analysis']['start']
            upper=intervals['analysis']['end']
            start,end=start or lower,end or upper
            if start<lower or end>upper:raise InputError('outside_analysis_interval','계산 구간 조회에는 include_warmup=true가 필요하며 분석 끝 이후는 조회하지 않습니다.')
        selected=[row for row in rows if (not start or row['timestamp']>=start) and (not end or row['timestamp']<=end)]
        page=selected[offset:offset+limit]
        source=v.read(store.folder/'input_manifest.json')
        info=v.read(store.run_dir/'ir.json')['sensors'].get(sensor_id,{})
        alarms=[alarm for alarm in store.alarms.values() if alarm['sensor_id']==sensor_id and
                (not start or alarm['last_positive_at']>=start) and (not end or alarm['trigger_at']<=end)]
        return {'analysis_id':analysis_id,'sensor_id':sensor_id,'unit':schema(store.base)[sensor_id]['unit'],
                'points':[{'timestamp':row['timestamp'],'value':row['value']} for row in page],
                'value_encoding':'decimal_string','thresholds':{key:info[key] for key in ('nominal','warnLo','warnHi','critLo','critHi') if key in info},
                'threshold_source':{'kg_node':info.get('threshold_node'),'kg_sha256':v.digest((v.REPO_ROOT/c.KG_REL).read_bytes())},
                'total':len(selected),'offset':offset,'limit':limit,'next_offset':offset+len(page) if offset+len(page)<len(selected) else None,
                'returned_interval':{'start':page[0]['timestamp'] if page else None,'end':page[-1]['timestamp'] if page else None},
                'gaps':[gap for gap in source['quality']['gaps'] if gap['sensor_id']==sensor_id and
                        (not start or gap['before']>=start) and (not end or gap['after']<=end)],
                'alarms':alarms,'incident_intervals':[i for i in store.incidents if i['sensor_id']==sensor_id and
                        (not start or i['end']>=start) and (not end or i['start']<=end)],
                'markers_scope':'requested interval, not just the current points page; paginate points before drawing a continuous chart',
                'intervals':intervals,'include_warmup':include_warmup,
                'input_source':store.input_source,'input_sha256':sha,'new_api_calls':0,'warnings':WARNINGS}

    def detail(self, analysis_id, incident_id):
        from . import claim_binding as cb, rule_explanations as rx
        store=self.store(analysis_id)
        if incident_id not in store.by_id:
            raise InputError('incident_not_in_analysis','이 분석에 속하지 않은 사건입니다.')
        evidence=incident_tools.get_incident_evidence(store,{'incident_id':incident_id})
        d.add_dependencies(evidence,store)
        proof=d.build(evidence,store)
        checks=rx.build(store,incident_id)
        catalog=cb.build_catalog(evidence,proof,store) if proof['status']=='consistent' else None
        sources,_=v.source_records();by_id={row['chunk_id']:row for row in sources}
        binding={'status':'withheld','published':False,'claims':[],'issues':['inconsistent evidence']}
        text='근거 검사를 통과하지 못해 설명을 보류합니다.'
        if catalog and not checks['counts']['inconsistent'] and checks['incident_end_aggregation']['state']=='consistent':
            view=cb.selector_view(catalog)
            ids=[]
            for kind in ('observation','condition','recommendation'):
                ids += [cl['claim_id'] for cl in view if cl['claim_type']==kind][:4]
            binding=cb.bind(json.dumps({'claim_ids':ids}),catalog,'관측 조건 조치 설명')
            binding['published']=binding['status']=='bound'
            if binding['published']:text=cb.render(binding)
        intervals=v.read(store.folder/'input_manifest.json').get('intervals')
        return {'analysis_id':analysis_id,'incident_id':incident_id,'answer':text,'intervals':intervals,
                'window_scope':incident_scope(store.by_id[incident_id],intervals['analysis']) if intervals else 'legacy_full_input',
                'agent_status':'complete' if binding['published'] else 'insufficient_evidence',
                'explanation_mode':'deterministic_evidence_summary_no_LLM','answer_complete':False,
                'selection_policy':'at most four claims per kind plus mandatory limits; structured evidence contains all matched rules',
                'claims':binding['claims'] if binding['published'] else [],
                'sources':[by_id[source['chunk_id']] for source in evidence['untrusted_reference_documents']],
                'edges':evidence['graph_paths'],'xai':{'incident':evidence['incident'],'alarms':evidence['alarms'],
                    'matched_rules':evidence['matched_rules'],'decision_evidence':proof,'rule_explanations':checks,
                    'claim_binding':binding,'correlation_candidates':incident_tools.get_correlated_incidents(store,{'incident_id':incident_id})},
                'input_source':store.input_source,'origin_input_source':store.declared_input_source,'new_api_calls':0,'warnings':WARNINGS}
