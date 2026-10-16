"""Record an authored AI source review; checks are integrity checks, not expert validation."""
import hashlib
import json
from pathlib import Path
from imaks_kg.kg.documents import units

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'kg_build/pre_benchmark_relations_20261016'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    protected = [OUT / n for n in ['candidates.json', 'candidate_kg.ttl',
                 'human_review.json', 'approved_relations.ttl']]
    protected.append(ROOT / 'kg_build/openai_sol_v2_20261016/llm_predictions.jsonl')
    before = {str(p.relative_to(ROOT)): digest(p) for p in protected}
    candidates = json.loads((OUT / 'candidates.json').read_text(encoding='utf-8'))
    source = {u['unit_id']: u for u in units()}
    reviews = []
    for c in candidates:
        rid = c['identifier']
        if rid == 'REL-01':
            continue
        for e in c['evidence']:
            actual = source[e['unit_id']]
            assert actual['text'] == e['text'], rid
            assert actual['source_file_sha256'] == e['source_file_sha256'], rid
        if rid == 'REL-02':
            decision = 'supported_document_instruction'
            reason = 'WARNING 발생 시 ST04 속도를 감시하라는 문장이 직접 존재한다. 센서가 다른 센서를 감시한다는 뜻이 아니라 조건에 따른 감시 의무이다.'
            normalized = {'trigger_sensor': c['subject'], 'trigger_state': 'WARNING',
                          'action': 'monitor', 'target': c['object']}
            limits = ['WARNING 수치와 지속시간을 이 문장만으로 추가하지 않는다.', '상관관계 문장을 인과관계로 승격하지 않는다.']
        elif rid == 'REL-03':
            decision = 'supported_document_instruction'
            reason = 'ST04 속도 저하 시 RULE-ST02-04를 확인하도록 명시되어 있어 참조 방향이 타당하다.'
            normalized = {'trigger_sensor': 'ST04_PACKAGING_SPD', 'operator': '<',
                          'value': 1.00, 'unit': 'm/s', 'without_operator_command': True,
                          'action': 'verify_rule', 'target': c['object']}
            limits = ['속도 조건과 운전자 명령 없음 조건을 함께 보존한다.', '참조 규칙을 확인하라는 지시가 원인 확정을 뜻하지 않는다.']
        elif rid in {'REL-04', 'REL-05', 'REL-06'}:
            decision = 'supported_with_action_label_clarification'
            reason = '원문이 ST02·ST03·ST04를 비상정지 대상으로 직접 열거한다. requiresShutdown은 포괄적이므로 emergency_stop 동작을 명시해야 한다.'
            normalized = {'trigger_sensor': c['subject'], 'operator': '>', 'value': 210,
                          'unit': 'degC', 'severity': 'CRITICAL', 'action': 'emergency_stop',
                          'target': c['object'], 'obligation_group': 'SOP-001::RULE-ST02-02',
                          'suggested_relation_type': 'requiresEmergencyStop'}
            limits = ['세 관계는 동일한 한 지시의 세 대상이며 독립적인 세 발견이 아니다.',
                      '자동 실행, 정지 순서·정확한 동시성, 복구 절차, 안전 인증을 추론하지 않는다.',
                      '210°C 초과를 이상(>=)으로 바꾸지 않는다. 임계값의 실제 안전성은 검증되지 않았다.']
        else:
            assert rid == 'REL-07'
            decision = 'retain_as_document_claim_only'
            reason = '의존성 표에 thermal fault → ST04 speed reduction이 직접 기록되어 있다. 문서 주장으로는 근거가 있으나 관측자료로 인과성을 검증한 결과가 아니다.'
            normalized = {'source_station': c['subject'], 'trigger_description': 'thermal fault',
                          'target_station': c['object'], 'effect_description': 'speed reduction',
                          'assertion_scope': 'document_claim', 'threshold': None, 'lag': None}
            limits = ['다른 규칙의 210°C를 이 관계의 임계값으로 가져오지 않는다.',
                      '전류 변화·전기적 결합 관계의 메커니즘을 열 이상 관계로 가져오지 않는다.',
                      '직접 Rule 노드가 없어도 표 행과 Document 근거로 보관 가능하다.']
        reviews.append({'identifier': rid, 'reviewer_type': 'AI', 'decision': decision,
                        'reason_ko': reason, 'proposed_normalization': normalized,
                        'limitations_ko': limits, 'evidence': c['evidence'],
                        'human_approved': False, 'empirical_causality_validated': False})
    assert {r['identifier'] for r in reviews} == {f'REL-{i:02}' for i in range(2, 8)}
    assert all(digest(ROOT / p) == h for p, h in before.items())
    result = {'date': '2026-10-16', 'method': 'AI-authored source-fidelity and semantic review; not an independent human/domain validation',
              'review_scope': 'six selected candidates only; no benchmark creation or model rerun',
              'protected_artifact_sha256': before, 'source_evidence_checks_passed': True,
              'reviewed_count': 6, 'independent_source_units': len({e['unit_id'] for r in reviews for e in r['evidence']}),
              'human_approved_count': 0, 'validated_new_causal_relations': 0,
              'normalization_applied_to_frozen_graph': False, 'reviews': reviews}
    (OUT / 'ai_review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'reviewed': 6, 'source_units': result['independent_source_units'],
                      'source_evidence_checks_passed': True, 'protected_artifacts_unchanged': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
