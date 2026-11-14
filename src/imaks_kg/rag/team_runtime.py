"""Selectable original detector implementations with one incident-tool contract."""
import importlib.util
from pathlib import Path

from rdflib import Graph, Literal, RDF, URIRef, XSD

from . import comparison as c, incident_tools as tools, vector as v
from ..detection import rules as original_input
from ..detection.engine import compiler, overlay, run as engine

PROFILES = {
    'main_v3_1': {'label': '기본 · v3.1 사건 엔진', 'owner': '유진·수민', 'config': 'v3_1'},
    'yujin_v3_2': {'label': '유진 · v3.2 감시·상관 개선', 'owner': '유진', 'config': 'v3_2'},
    'seongho_two_point': {'label': '성호 · 연속 2점 확인', 'owner': '성호', 'rules': 'rules_baseline.json'},
    'seongho_drift': {'label': '성호 · 연속 2점 + 변화량 DRIFT', 'owner': '성호', 'rules': 'rules_improved.json'},
}
SEARCH_MODES = {'auto': '자동 · 문서는 하이브리드 / 집합은 KG 질의',
                'vector': '문서 · Vector RAG', 'graph': '문서 · GraphRAG v5',
                'full': '문서 · 전체 원문 입력'}
SEONGHO = v.REPO_ROOT / 'experiments/rule_detector_20261106'
TEAM_ROOT = v.REPO_ROOT / 'kg_build/team_app'
DEFAULTS = {'detector_profile': 'main_v3_1', 'document_mode': 'auto'}


def application_config():
    return {'version': 'team-app-v1-20261113', 'defaults': DEFAULTS.copy(),
            'features': {'rule_boundaries': True, 'retrospective_closure_checks': True, 'extractive_document_claims': True,
                         'decision_evidence': True, 'window_trigger_checks': True, 'incident_claim_binding': True,
                         'claim_evidence_paths': True,
                         'repair_incident_default': False,
                         'repair_incident_max_attempts': 2},
            'detectors': [{'id': key, **value} for key, value in PROFILES.items()],
            'search_modes': SEARCH_MODES.copy(),
            'members': contributions(DEFAULTS['detector_profile'], DEFAULTS['document_mode'])['members']}


def directories(profile):
    if profile not in PROFILES:
        raise ValueError('Unknown detector profile')
    if profile == 'main_v3_1':
        return tools.ENGINE_RUN, tools.ENGINE_OVERLAY
    return TEAM_ROOT / profile / 'run', TEAM_ROOT / profile / 'overlay'


def store(profile='main_v3_1'):
    run_dir, overlay_dir = directories(profile)
    return tools.IncidentStore(run_dir, overlay_dir)


def contributions(profile, document_mode):
    if profile not in PROFILES or document_mode not in SEARCH_MODES:
        raise ValueError('Unknown application selection')
    return {'version': 'team-app-v1-20261113', 'detector_profile': profile,
            'detector_label': PROFILES[profile]['label'], 'document_mode': document_mode,
            'members': {
                '예원': '고정 v2 KG·문서 해시·출처 추적을 공통 지식 기반으로 사용',
                '유진': '사건 도구·KG 연결·v5 검색을 사용, v3.2는 선택 모드',
                '성호': '연속 2점 확인·정상 복귀·변화량 탐지의 원본 코드를 선택 모드로 실행',
                '수민': '문서 하이브리드·KG 전수 질의·전체 문서 대안으로 실험 분석을 설계에 반영',
            }, 'note': '새 통합 구성이다. 과거 실험 점수는 이 앱의 성능 점수로 승계하지 않는다.'}


def prepare_profile(profile):
    run_dir, overlay_dir = directories(profile)
    definition = PROFILES[profile]
    if not run_dir.exists():
        if 'config' in definition:
            engine.run(definition['config'], run_dir)
        else:
            prepare_seongho(profile, run_dir, overlay_dir)
    if not overlay_dir.exists():
        if 'rules' in definition:
            build_seongho_overlay(profile, run_dir, overlay_dir)
        else:
            overlay.load(run_dir, overlay_dir)
    loaded = store(profile)
    return {'profile': profile, 'label': definition['label'], 'incidents': len(loaded.incidents),
            'alarms': len(loaded.alarms), 'gold_loaded': False, 'new_model_calls': 0}


def prepare_seongho(profile, run_dir, overlay_dir):
    """Run Seongho's scanner unchanged; preserve each original rule event."""
    source = SEONGHO / 'code/detector.py'
    spec = importlib.util.spec_from_file_location('seongho_original_detector', source)
    detector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(detector)
    rules_path = SEONGHO / PROFILES[profile]['rules']
    raw_dir = run_dir.parent / 'original_detector'
    detector.run(v.REPO_ROOT / original_input.INPUT, rules_path, raw_dir)
    raw_seal = v.read(raw_dir / 'seal.json')
    for name, checksum in raw_seal.items():
        if v.digest((raw_dir / name).read_bytes()) != checksum:
            raise ValueError('Seongho output seal mismatch')
    rules = v.read(rules_path)['rules']
    rule_by = {(rule['rule_id'], rule['sensor_id']): rule for rule in rules}
    events, incidents = [], []
    prefix = '33' if profile == 'seongho_two_point' else '34'
    for original in v.read(raw_dir / 'events.json'):
        event = {**original, 'original_event_id': original['id'],
                 'id': f'det{prefix}-' + v.digest(original['id'].encode())[:20]}
        events.append(event)
        incidents.append({'id': f'inc{prefix}-' + v.digest(original['id'].encode())[:20],
            'sensor_id': original['sensor_id'], 'station_id': original['station_id'],
            'start': original['trigger_at'], 'end': original['last_positive_at'],
            'onset_estimate': original['condition_start'], 'anomaly_type': 'UNCLASSIFIED',
            'severity': 'ADVISORY', 'type_reason': '성호 원본은 SOP-002 사건 유형을 분류하지 않아 미분류로 유지',
            'severity_origin': '표시용 ADVISORY 기본값. 성호 원본은 심각도를 분류하지 않음',
            'flags': [original['status']], 'alarm_ids': [event['id']], 'rule_ids': [original['rule_id']],
            'source_status': original['status'], 'normal_confirmed_at': original['normal_confirmed_at']})
    ir_rules = []
    for rule in rules:
        parameters = {key: rule[key] for key in ('op', 'value', 'second', 'duration_seconds', 'window_seconds') if key in rule}
        parameters.update(confirm_observations=2, clear_observations=2)
        ir_rules.append({'ir_id': rule['rule_id'] + '@' + rule['sensor_id'], 'rule_id': rule['rule_id'],
            'sensor_id': rule['sensor_id'], 'kg_node': rule['kg_node'], 'kind': rule['kind'],
            'params': parameters, 'param_sources': {'document_condition': 'original Seongho rules JSON',
                'confirm_observations': 'original detector.scan default=2', 'clear_observations': 'original detector.scan default=2'}})
    run_dir.mkdir(parents=True, exist_ok=False)
    v.write(run_dir / 'events.json', events)
    v.write(run_dir / 'incidents.json', incidents)
    v.write(run_dir / 'correlations.json', [])
    v.write(run_dir / 'monitor_windows.json', [])
    v.write(run_dir / 'ir.json', {'rules': ir_rules, 'type_definitions': {}, 'correlation_pairs': []})
    v.write(run_dir / 'params.json', {'config': {'name': profile, 'sample_seconds': 30,
        'smooth_samples': None, 'maint_direction': 'positive_delta_only', 'monitor_anchor': None, 'slope_mode': None},
        'original_policy': detector.POLICY, 'original_rules_sha256': v.digest(rules_path.read_bytes()),
        'original_scanner_sha256': v.digest(source.read_bytes())})
    v.write(run_dir / 'summary.json', {'alarms': len(events), 'incidents': len(incidents), 'gold_loaded': False,
        'original_seal': raw_seal, 'mapping': 'one original rule event per UI candidate; no regrouping or type inference'})
    v.write(run_dir / 'complete.json', {path.name: v.digest(path.read_bytes()) for path in run_dir.iterdir() if path.is_file()})

    build_seongho_overlay(profile, run_dir, overlay_dir)


def build_seongho_overlay(profile, run_dir, overlay_dir):
    """Recover an interrupted mapping from sealed outputs, never rerun its scanner."""
    overlay.verify_seal(run_dir)
    incidents = v.read(run_dir / 'incidents.json')
    events = v.read(run_dir / 'events.json')
    rules = v.read(SEONGHO / PROFILES[profile]['rules'])['rules']
    rule_by = {(rule['rule_id'], rule['sensor_id']): rule for rule in rules}
    graph = Graph()
    base = c.load_graph()
    source_hash = v.digest((v.REPO_ROOT / original_input.INPUT).read_bytes())
    for incident, event in zip(incidents, events):
        node = URIRef(overlay.EVENT + incident['id'])
        sensor = next(base.subjects(c.IM.identifier, Literal(incident['sensor_id'])))
        provenance = URIRef(overlay.WINDOW + incident['id'])
        rule = rule_by[(event['rule_id'], event['sensor_id'])]
        graph.add((node, RDF.type, overlay.DET.RuleMatchCandidate))
        graph.add((node, overlay.DET.observedOnSensor, sensor))
        graph.add((node, overlay.DET.engineIncidentId, Literal(incident['id'])))
        graph.add((node, overlay.DET.matchedRule, URIRef(rule['kg_node'])))
        graph.add((node, overlay.DET.triggeredAt, Literal(incident['start'], datatype=XSD.dateTime)))
        graph.add((node, overlay.DET.lastPositiveAt, Literal(incident['end'], datatype=XSD.dateTime)))
        graph.add((node, overlay.DET.sourceWindow, provenance))
        for predicate, value in ((RDF.type, c.IM.Provenance), (c.IM.sourceKind, Literal('timeseries')),
            (c.IM.fileName, Literal(original_input.INPUT)), (c.IM.sensorId, Literal(incident['sensor_id'])),
            (c.IM.intervalStart, Literal(incident['onset_estimate'], datatype=XSD.dateTime)),
            (c.IM.intervalEnd, Literal(incident['end'], datatype=XSD.dateTime)),
            (c.IM.fileSha256, Literal(source_hash)), (c.IM.windowId, Literal('W-' + incident['id']))):
            graph.add((provenance, predicate, value))
    from pyshacl import validate
    candidate_shapes = Path(__file__).with_name('team_candidate_shapes.ttl')
    conforms, _, candidate_text = validate(base + graph, shacl_graph=Graph().parse(candidate_shapes),
                                          ont_graph=Graph().parse(overlay.ONTOLOGY), inference='none')
    report = {**overlay.shacl_checks(graph, base), 'loader_errors': overlay.loader_checks(graph, base),
              'engine_seal_sha256': v.digest(v.encoded(v.read(run_dir / 'complete.json'))),
              'events': len(incidents), 'candidate_shapes_conform': bool(conforms),
              'candidate_shapes_sha256': v.digest(candidate_shapes.read_bytes()),
              'candidate_validation': candidate_text,
              'note': 'det:RuleMatchCandidate is separate from im:AnomalyEvent; S2 remains unchanged'}
    if report['shacl_blocking'] or report['guards_L4'] or report['loader_errors'] or not conforms:
        v.write(run_dir.parent / 'overlay_rejection.json', report)
        raise ValueError('Seongho adapter overlay validation failed')
    overlay_dir.mkdir(parents=True, exist_ok=False)
    graph.serialize(overlay_dir / 'overlay.ttl', format='turtle')
    v.write(overlay_dir / 'overlay_report.json', report)
    v.write(overlay_dir / 'complete.json', {path.name: v.digest(path.read_bytes()) for path in overlay_dir.iterdir() if path.is_file()})
