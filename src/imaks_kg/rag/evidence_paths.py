"""Claim paths over real RDF plus explicitly labelled runtime/file references."""
from pathlib import Path
import json
from rdflib import Graph, Literal, RDF, URIRef

from . import comparison as c, vector as v
from .chunking import provenance_row_number
from .window_evidence import checked_file

VERSION = 'claim-evidence-paths-v1-20261114'
DET = 'https://example.org/imaks/detection/engine#'
MESSAGES = {
    'missing_stored_relation': '필요한 방향의 관계가 실제 저장 그래프에 없습니다.',
    'graph_field_changed': '현재 그래프 필드가 고정된 원본과 달라졌습니다.',
    'missing_or_ambiguous_metadata': '필요한 메타데이터가 없거나 여러 값으로 나뉩니다.',
    'different_incident': '주장이 다른 사건을 가리킵니다.',
    'claim_content_id_mismatch': '주장 내용과 주장 ID가 일치하지 않습니다.',
    'alarm_not_in_incident': '해당 알람이 이 사건에 속하지 않습니다.',
    'observation_reference_mismatch': '원본 관측을 확인한 검사 결과와 연결되지 않습니다.',
    'observation_does_not_match_sealed_alarm': '관측 참조가 봉인 알람과 다릅니다.',
    'claim_source_metadata_mismatch': '원문 청크의 문서·쪽·해시 참조가 다릅니다.',
    'source_document_missing_or_wrong': '규칙에 연결된 원본 문서를 확인할 수 없습니다.',
    'provenance_path_unresolved': '출처에서 원문까지 연결되지 않습니다. 세부 실패 사유를 확인하세요.',
    'table_row_or_quote_mismatch': '표·행 위치와 인용문이 일치하지 않습니다.',
    'quote_hash_mismatch': '인용문의 해시가 일치하지 않습니다.',
    'IR_rule_binding_mismatch': '알람·실행 규칙·KG 규칙의 연결이 맞지 않습니다.',
    'monitor_dependency_binding_mismatch': '감시 알람과 원래 신호·규칙의 참조가 맞지 않습니다.',
    'document_reference_set_mismatch': '주장에 선언된 문서 참조가 필요한 출처 집합과 다릅니다.',
    'path_not_contiguous': '경로 단계의 시작점과 도착점이 이어지지 않습니다.',
    'branch_not_attached': '문서 분기가 주 경로에 붙어 있지 않습니다.'}


class BrokenPath(ValueError):
    def __init__(self, code, node, detail):
        super().__init__(code)
        self.data = {'code': code, 'message': MESSAGES.get(code, '해당 근거 경로의 참조나 메타데이터를 확인할 수 없습니다.'),
                     'at_node': str(node), 'detail': detail}


def norm(value):
    return ' '.join(str(value).split())


class PathContext:
    def __init__(self, evidence, proof, store):
        self.evidence, self.proof, self.store = evidence, proof, store
        if proof['status'] != 'consistent':
            raise ValueError('Inconsistent decision report')
        self.incident_id = evidence['incident']['id']
        self.incidents = {item['id']: item for item in checked_file(store, 'incidents.json')}
        self.alarms = {item['id']: item for item in checked_file(store, 'events.json')}
        self.bundle = checked_file(store, 'ir.json')
        self.ir = {item['ir_id']: item for item in self.bundle['rules']}
        self.base = c.load_graph()
        self.base_sha256 = v.digest((v.REPO_ROOT / c.KG_REL).read_bytes())
        overlay = store.overlay_dir / 'overlay.ttl'
        if v.digest(overlay.read_bytes()) != store.overlay_seal['overlay.ttl']:
            raise ValueError('Changed overlay')
        self.overlay = Graph().parse(overlay, format='turtle')
        records, self.chunks_sha256 = v.source_records()
        self.sources = {record['chunk_id']: record for record in records}
        self.links = {str(node): ids for node, ids in c.source_links(self.base, records).items()}
        self.items = {item['evidence_id']: item for item in proof['items']}
        self.proof_sha256 = v.digest(v.encoded(proof))
        self.incident = self.incidents.get(self.incident_id)
        if self.incident is None:
            raise ValueError('Unknown sealed incident')
        nodes = list(self.overlay.subjects(URIRef(DET + 'engineIncidentId'), Literal(self.incident_id)))
        if len(nodes) != 1:
            raise ValueError('Incident overlay identifier does not resolve uniquely')
        self.event = nodes[0]

    def values(self, node, predicate, *, overlay=False):
        current = self.store.overlay if overlay else self.store.base
        canonical = self.overlay if overlay else self.base
        actual, expected = set(current.objects(node, predicate)), set(canonical.objects(node, predicate))
        if actual != expected:
            raise BrokenPath('graph_field_changed', node, {'predicate': str(predicate)})
        return sorted(actual, key=str)

    def value(self, node, predicate, *, optional=False):
        values = self.values(node, predicate)
        if len(values) > 1 or (not values and not optional):
            raise BrokenPath('missing_or_ambiguous_metadata', node, {'predicate': str(predicate)})
        return str(values[0]) if values else None

    def rdf(self, subject, predicate, obj, *, inverse=False, overlay=False):
        triple = (subject, predicate, obj)
        actual = self.store.overlay if overlay else self.store.base
        canonical = self.overlay if overlay else self.base
        if triple not in actual or triple not in canonical:
            raise BrokenPath('missing_stored_relation', obj if inverse else subject,
                             {'subject': str(subject), 'predicate': str(predicate), 'object': str(obj)})
        return {'kind': 'rdf', 'from': str(obj if inverse else subject), 'to': str(subject if inverse else obj),
                'relation': str(predicate), 'traversal': 'inverse' if inverse else 'forward',
                'stored': {'s': str(subject), 'p': str(predicate), 'o': str(obj)},
                'source': {'layer': 'overlay' if overlay else 'frozen_KG',
                           'file': (self.store.overlay_dir / 'overlay.ttl').relative_to(v.REPO_ROOT).as_posix() if overlay else c.KG_REL,
                           'sha256': self.store.overlay_seal['overlay.ttl'] if overlay else self.base_sha256}}

    def reference(self, start, end, relation, source):
        return {'kind': 'runtime_reference', 'from': str(start), 'to': str(end),
                'relation': relation, 'validation': source}

    def file_ref(self, name, **selector):
        return {'file': (self.store.run_dir / name).relative_to(v.REPO_ROOT).as_posix(),
                'sha256': self.store.seal[name], 'selector': selector}

    def root(self, claim):
        if claim['incident_id'] != self.incident_id:
            raise BrokenPath('different_incident', claim['claim_id'], {})
        body = {key: claim[key] for key in ('incident_id', 'claim_type', 'text', 'evidence_refs', 'values', 'validation')}
        sha = v.digest(v.encoded(body))
        if claim['claim_id'] != 'CLM-' + sha[:16]:
            raise BrokenPath('claim_content_id_mismatch', claim['claim_id'], {})
        self.values(self.event, URIRef(DET + 'engineIncidentId'), overlay=True)
        return [self.reference('claim:' + claim['claim_id'], self.event, 'claim_incident',
                               {'claim_payload_sha256': sha, **self.file_ref('incidents.json', id=self.incident_id)})]

    def alarm_path(self, prefix, alarm_id):
        if alarm_id not in self.incident['alarm_ids'] or alarm_id not in self.alarms:
            raise BrokenPath('alarm_not_in_incident', self.event, {'alarm_id': alarm_id})
        return prefix + [self.reference(self.event, 'alarm:' + alarm_id, 'incident_alarm_membership',
                       self.file_ref('incidents.json', id=self.incident_id, alarm_id=alarm_id))]

    def raw_path(self, prefix, observed):
        items = [item for item in self.proof['items'] if item['observation'] == observed
                 and item['grounding_status'] == 'consistent' and item['alarm_id'] in self.incident['alarm_ids']]
        if not items:
            raise BrokenPath('observation_reference_mismatch', self.event, {})
        if any(any(observed[field] != self.alarms[item['alarm_id']][target] for field, target in
                   (('sensor_id', 'sensor_id'), ('at', 'trigger_at'), ('value', 'trigger_value'), ('unit', 'unit')))
               for item in items):
            raise BrokenPath('observation_does_not_match_sealed_alarm', self.event, {})
        sensor_id = observed['sensor_id']
        if sensor_id != self.incident['sensor_id']:
            raise BrokenPath('sensor_not_in_incident', self.event, {'sensor_id': sensor_id})
        sensors = list(self.base.subjects(c.IM.identifier, Literal(sensor_id)))
        if len(sensors) != 1:
            raise BrokenPath('sensor_not_unique', self.event, {'sensor_id': sensor_id})
        sensor = sensors[0]
        if (self.event, RDF.type, URIRef(DET + 'RuleMatchCandidate')) in self.overlay:
            edge = self.rdf(self.event, URIRef(DET + 'observedOnSensor'), sensor, overlay=True)
        else:
            edge = self.rdf(sensor, c.IM.triggers, self.event, inverse=True, overlay=True)
        anchor = 'sample:' + v.digest(v.encoded(observed))[:20]
        step = self.reference(sensor, anchor, 'sensor_sample_lookup',
            {'file': self.proof['input_file'], 'sha256': self.proof['input_sha256'], **observed,
             'method': 'prior_checked_raw_observation_and_sealed_alarm', 'decision_report_sha256': self.proof_sha256})
        # This is a file reference, never a newly asserted Sensor -> Sample RDF edge.
        step['kind'] = 'file_lookup'
        return prefix + [edge, step]

    def provenance_path(self, prefix, rule, ref):
        source = self.sources.get(ref['chunk_id'])
        fields = ('doc_id', 'page', 'text_sha256', 'source_file_sha256')
        if source is None or any(ref.get(key) != source[key] for key in fields):
            raise BrokenPath('claim_source_metadata_mismatch', rule, {'chunk_id': ref['chunk_id']})
        documents = [node for node in self.values(rule, c.IM.sourceDocument)
                     if self.value(node, c.IM.identifier) == source['doc_id']]
        if len(documents) != 1:
            raise BrokenPath('source_document_missing_or_wrong', rule, {'doc_id': source['doc_id']})
        doc = documents[0]
        if self.value(doc, c.IM.sourceSha256) != source['source_file_sha256']:
            raise BrokenPath('document_hash_mismatch', doc, {})
        branch = self.rdf(rule, c.IM.sourceDocument, doc)
        failures = []
        for prov in self.values(rule, c.IM.hasProvenance):
            try:
                edge = self.rdf(rule, c.IM.hasProvenance, prov)
                if (self.value(prov, c.IM.sourceKind) != 'document' or
                    self.value(prov, c.IM.fileSha256) != source['source_file_sha256'] or
                    int(self.value(prov, c.IM.page)) != source['page']):
                    raise BrokenPath('provenance_document_or_page_mismatch', prov, {})
                quote = self.value(prov, c.IM.sourceQuote)
                if v.digest(quote.encode()) != self.value(prov, c.IM.textSha256):
                    raise BrokenPath('quote_hash_mismatch', prov, {})
                table = self.value(prov, c.IM.tableId, optional=True)
                locator = {'doc_id': source['doc_id'], 'page': source['page']}
                if table:
                    index = self.value(prov, c.IM.rowIndex)
                    row = provenance_row_number(index)
                    lines = [line for line in source['text'].splitlines() if line.strip()]
                    if table != source.get('table_id') or row is None or row >= len(lines) or norm(quote) not in norm(lines[row]):
                        raise BrokenPath('table_row_or_quote_mismatch', prov, {'table_id': table, 'row_index': index})
                    column = int(self.value(prov, c.IM.colIndex))
                    if column < 1:
                        raise BrokenPath('invalid_recorded_column', prov, {})
                    locator.update(table_id=table, row_index=int(index), data_row_number=row,
                                   col_index=column, column_check='recorded_metadata_only',
                                   granularity='normalized_table_row')
                    bbox = self.value(prov, c.IM.bbox, optional=True)
                    if bbox and json.loads(bbox) != source.get('bbox'):
                        raise BrokenPath('bbox_metadata_mismatch', prov, {})
                else:
                    start, end = int(self.value(prov, c.IM.charStart)), int(self.value(prov, c.IM.charEnd))
                    a, b = source.get('char_start'), source.get('char_end')
                    if a is None or b is None or not a <= start <= end <= b:
                        raise BrokenPath('character_range_outside_chunk', prov, {})
                    excerpt = source['text'][start - a:end - a]
                    if norm(quote) not in norm(excerpt):
                        raise BrokenPath('quote_outside_recorded_span', prov, {})
                    locator.update(char_start=start, char_end=end,
                                   granularity='exact_quote_span' if excerpt == quote else 'enclosing_chunk_span')
                anchor = 'chunk:' + source['chunk_id']
                lookup = {'kind': 'file_lookup', 'from': str(prov), 'to': anchor,
                          'relation': 'provenance_resolves_to_frozen_chunk', 'validation':
                          {'file': v.SOURCE.relative_to(v.REPO_ROOT).as_posix(), 'sha256': self.chunks_sha256,
                           'chunk_id': source['chunk_id'], 'quote_sha256': v.digest(quote.encode()),
                           'text_sha256': source['text_sha256'], 'locator': locator,
                           'scope': 'frozen extracted text; PDF physical layout not independently reviewed'}}
                return {'kind': 'document_source', 'steps': prefix + [edge, lookup],
                        'branches': [{'starts_at': str(rule), 'steps': [branch]}]}
            except BrokenPath as error:
                failures.append(error.data)
        raise BrokenPath('provenance_path_unresolved', rule, {'chunk_id': ref['chunk_id'], 'failures': failures[:3]})

    def document_paths(self, prefix, rule, refs, *, require_all=True):
        ids = self.links.get(str(rule), [])
        targets = [ref for ref in refs if ref.get('kind') == 'document_chunk' and ref['chunk_id'] in ids]
        if not targets:
            raise BrokenPath('required_document_reference_missing', rule, {'expected_chunks': ids})
        if require_all and {ref['chunk_id'] for ref in refs if ref['kind'] == 'document_chunk'} != set(ids):
            raise BrokenPath('document_reference_set_mismatch', rule, {'expected_chunks': ids})
        return [self.provenance_path(prefix, rule, ref) for ref in targets]

    def condition_paths(self, claim, root):
        refs = [ref for ref in claim['evidence_refs'] if ref['kind'] == 'decision_check']
        if len(refs) != 1:
            raise BrokenPath('decision_reference_not_unique', self.event, {})
        ref = refs[0]
        item = self.items.get(ref['evidence_id'])
        if (item is None or item['alarm_id'] != ref['alarm_id'] or ref['audit_version'] != self.proof['version']
            or item['trigger_check']['state'] != 'consistent'):
            raise BrokenPath('decision_reference_mismatch', self.event, {})
        alarm_id, decision = item['alarm_id'], 'decision:' + item['evidence_id']
        runtime = self.alarm_path(root, alarm_id)
        runtime += [self.reference('alarm:' + alarm_id, decision, 'alarm_decision_check',
                                  {'decision_report_sha256': self.proof_sha256, 'evidence_id': item['evidence_id']})]
        paths = [{'kind': 'raw_observation', 'steps': self.raw_path(root, item['observation']), 'branches': []}]
        node = item['rule'].get('kg_node')
        if node:
            ir = self.ir.get(item['rule']['ir_id'])
            if (ir is None or ir['kg_node'] != node or ir['sensor_id'] != self.incident['sensor_id']
                or ir['rule_id'] != self.alarms[alarm_id]['rule_id'] or ir['params'] != item['rule']['params']):
                raise BrokenPath('IR_rule_binding_mismatch', decision, {})
            ir_node = 'ir:' + ir['ir_id']
            runtime += [self.reference(decision, ir_node, 'decision_IR_binding', self.file_ref('ir.json', ir_id=ir['ir_id'])),
                        self.reference(ir_node, node, 'IR_KG_node', self.file_ref('ir.json', ir_id=ir['ir_id'], field='kg_node'))]
            paths.append({'kind': 'runtime_rule_binding', 'steps': runtime, 'branches': []})
            prefix = root + [self.rdf(self.event, URIRef(DET + 'matchedRule'), URIRef(node), overlay=True)]
            paths += self.document_paths(prefix, URIRef(node), claim['evidence_refs'])
        else:
            check = item['trigger_check']
            if check.get('operator') != 'derived_monitor' or not check.get('source_rule_node'):
                raise BrokenPath('derived_dependency_unresolved', decision, {})
            alarm = self.alarms[alarm_id]
            pairs = [pair for pair in self.bundle['correlation_pairs'] if pair['effect_sensor'] == alarm['sensor_id']
                     and pair['rule_ids'][0] + ':monitor' == alarm['rule_id']]
            slope = [rule for rule in self.bundle['rules'] if rule.get('executor') == 'slope' and rule['sensor_id'] == alarm['sensor_id']]
            if (len(pairs) != 1 or len(slope) != 1 or check['source_rule_node'] != slope[0]['kg_node']
                or check['source_signal_id'] != alarm.get('source_signal')):
                raise BrokenPath('monitor_dependency_binding_mismatch', decision, {})
            pair, slope_ir = pairs[0], slope[0]
            definition = self.bundle['type_definitions']['CORRELATED']
            if pair['window_rule_id'] != definition['rule_id']:
                raise BrokenPath('monitor_window_definition_mismatch', decision, {})
            allowed = set(pair['kg_nodes']) | {definition['kg_node'], slope_ir['kg_node']}
            nodes = list(dict.fromkeys(check['evidence_rule_nodes'] + [check['source_rule_node']]))
            if set(nodes) != allowed:
                raise BrokenPath('monitor_dependency_set_mismatch', decision, {})
            expected_sources = {cid for node in nodes for cid in self.links.get(node, [])}
            if expected_sources != {ref['chunk_id'] for ref in claim['evidence_refs'] if ref['kind'] == 'document_chunk'}:
                raise BrokenPath('monitor_document_reference_set_mismatch', decision, {})
            for target in nodes:
                if target not in allowed:
                    raise BrokenPath('unknown_runtime_dependency', decision, {'node': target})
                if target == slope_ir['kg_node']:
                    signal = 'signal:' + check['source_signal_id']
                    prefix = runtime + [self.reference(decision, signal, 'checked_source_signal',
                        {'decision_report_sha256': self.proof_sha256, 'signal_id': check['source_signal_id'],
                         'reference_status': check['source_signal_reference_status'], 'method': 'prior_verified_exact_signal_hash'}),
                        self.reference(signal, target, 'source_signal_IR_rule', self.file_ref('ir.json', ir_id=slope_ir['ir_id']))]
                else:
                    pair_node = 'pair:' + v.digest(v.encoded(pair))[:16]
                    prefix = runtime + [self.reference(decision, pair_node, 'monitor_pair_binding',
                        self.file_ref('ir.json', rule_ids=pair['rule_ids'])),
                        self.reference(pair_node, target, 'pair_KG_dependency', self.file_ref('ir.json', dependency_node=target))]
                    if target in pair['kg_nodes']:
                        paths.append({'kind': 'runtime_pair_binding', 'steps': prefix, 'branches': []})
                        prefix = root + [self.rdf(self.event, URIRef(DET + 'matchedRule'), URIRef(target), overlay=True)]
                paths += self.document_paths(prefix, URIRef(target), claim['evidence_refs'], require_all=False)
        return paths

    def claim_paths(self, claim):
        result = {'version': VERSION, 'claim_id': claim['claim_id'], 'status': 'broken', 'paths': [], 'breaks': []}
        try:
            root = self.root(claim)
            if not claim['evidence_refs']:
                raise BrokenPath('claim_reference_missing', self.event, {})
            kind = claim['claim_type']
            if kind == 'observation':
                ref = next(ref for ref in claim['evidence_refs'] if ref['kind'] == 'raw_observation')
                if ref['file'] != self.proof['input_file'] or ref['file_sha256'] != self.proof['input_sha256']:
                    raise BrokenPath('observation_file_mismatch', self.event, {})
                observed = {key: ref[key] for key in ('sensor_id', 'at', 'value', 'unit')}
                result['paths'] = [{'kind': 'raw_observation', 'steps': self.raw_path(root, observed), 'branches': []}]
            elif kind == 'condition':
                result['paths'] = self.condition_paths(claim, root)
            elif kind == 'recommendation':
                ref = next(ref for ref in claim['evidence_refs'] if ref['kind'] == 'kg_fields')
                node = URIRef(ref['node'])
                for field, predicate in (('condition_text', c.IM.conditionText), ('response_text', c.IM.responseText)):
                    if self.value(node, predicate, optional=True) != ref[field]:
                        raise BrokenPath('KG_claim_field_mismatch', node, {'field': field})
                prefix = root + [self.rdf(self.event, URIRef(DET + 'matchedRule'), node, overlay=True)]
                result['paths'] = self.document_paths(prefix, node, claim['evidence_refs'])
            elif kind == 'interpretation':
                if all(ref['kind'] == 'validation_scope' for ref in claim['evidence_refs']):
                    for ref in claim['evidence_refs']:
                        if any(ref[key] != self.proof[key] for key in ('scope', 'not_verified') if key in ref):
                            raise BrokenPath('scope_reference_mismatch', self.event, {})
                    result.update(status='scope_only', paths=[], scope='validation limit, not a factual KG path')
                    return result
                ref = claim['evidence_refs'][0]
                if ref.get('incident_id') != self.incident_id or ref.get('anomaly_type') != self.incident['anomaly_type']:
                    raise BrokenPath('incident_metadata_mismatch', self.event, {})
                if (ref['kind'] == 'incident_metadata' and ref.get('severity_origin') !=
                    self.evidence['incident'].get('severity_origin', 'display-only default')):
                    raise BrokenPath('display_policy_reference_mismatch', self.event, {})
                step = self.reference(self.event, 'metadata:' + self.incident_id, 'sealed_incident_type_report',
                                      self.file_ref('incidents.json', id=self.incident_id, field='anomaly_type'))
                result['paths'] = [{'kind': 'metadata_only', 'steps': root + [step], 'branches': []}]
            else:
                raise BrokenPath('unsupported_claim_type', self.event, {'type': kind})
            for path in result['paths']:
                steps = path['steps']
                if not steps or any(a['to'] != b['from'] for a, b in zip(steps, steps[1:])):
                    raise BrokenPath('path_not_contiguous', claim['claim_id'], {})
                nodes = {step[key] for step in steps for key in ('from', 'to')}
                if any(branch['starts_at'] not in nodes or branch['steps'][0]['from'] != branch['starts_at'] for branch in path['branches']):
                    raise BrokenPath('branch_not_attached', claim['claim_id'], {})
                path['status'] = 'complete'
                path['uses_graph'] = any(step['kind'] == 'rdf' for step in steps)
            result['status'] = 'complete'
        except BrokenPath as error:
            result['breaks'].append(error.data)
        except (KeyError, StopIteration, TypeError, ValueError) as error:
            result['breaks'].append({'code': 'invalid_path_metadata', 'at_node': claim.get('claim_id'),
                                     'message': '경로 메타데이터 형식이 올바르지 않습니다.',
                                     'detail': {'error_type': type(error).__name__}})
        return result


def build(claims, evidence, proof, store):
    context = PathContext(evidence, proof, store)
    results = [context.claim_paths(claim) for claim in claims]
    return {'version': VERSION, 'incident_id': evidence['incident']['id'], 'claims': results,
            'status': 'broken' if any(item['status'] == 'broken' for item in results) else 'complete',
            'counts': {state: sum(item['status'] == state for item in results) for state in ('complete', 'scope_only', 'broken')},
            'scope': 'declared reference continuity and frozen extraction metadata; not semantic truth or causality'}


def for_saved_run(run):
    from . import claim_binding, decision_evidence, team_runtime
    answer = v.read(run / 'answer.json')
    if answer.get('claims') and answer.get('xai', {}).get('claim_binding', {}).get('published'):
        checked = decision_evidence.for_saved_run(run)
        store = team_runtime.store(answer['integration']['detector_profile'])
        evidence = v.read(run / 'retrieval.json')['context']
        decision_evidence.add_dependencies(evidence, store)
        report = build(answer['claims'], evidence, checked['decision_evidence'], store)
        scope = 'stored_published_claims_reference_paths'
        sha = checked['answer_unchanged_sha256']
    else:
        current = claim_binding.catalog_for_saved_run(run)
        catalog = current['catalog']
        report = {**catalog['path_summary'], 'incident_id': catalog['incident_id'],
                  'claims': [claim['evidence_paths'] for claim in catalog['claims']]}
        scope = 'current_admissible_catalog_not_a_validation_of_old_prose'
        sha = current['answer_unchanged_sha256']
    return {'run_id': run.name, 'new_api_calls': 0, 'path_scope': scope, 'evidence_paths': report,
            'past_answer_prose_revalidated': False, 'answer_unchanged_sha256': sha}
