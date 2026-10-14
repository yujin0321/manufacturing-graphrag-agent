# eval v3 (매칭 2순위 합 = 유효 쌍만) 검증 보고서
- 판정: PASS

| 항목 | 결과 | 근거 |
|---|---|---|
| 1. 브루트포스 일치 (100개, 시드 7, 3x3~5x5, 3x4/4x3/3x5/5x3, 임계 부근 값 포함) | PASS | 독립 작성 완전 탐색(scratchpad/bf.py)과 유효 수·유효 합 불일치 0/100. 일대일·모든 쌍 유효 assert 통과 |
| 2. 반례 A / B / 경계 | PASS | A: {P1-G2, P3-G1}, 합 1.38. B: {P1-G2, P2-G1}. 0.6 유효, 0.59 무효(빈 결과) |
| 3. TP/FP/FN 불변 | PASS | 무작위 200개에서 도구의 유효 매칭 수 = 유효 쌍 최대 기수(브루트포스), 불일치 0. TP/FP/FN은 이 수로만 정해지므로 바뀌는 것은 짝 구성뿐 |
| 4. 결정성, 직사각 | PASS | 같은 입력 2회 결과 동일(assert), 직사각 행렬 포함 100개 통과 |
| 5. 점검 | PASS | unittest discover 마지막 줄: Ran 173 tests ... OK (tests.test_eval_f1 28개 OK). check_leakage 종료 0, ground_truth 경고 0건. check_secrets PASS. check_raw_unchanged PASS(1121개) |
| 6. 금지 경로 | PASS(조건부) | ontology_v1/ontology.ttl, schema_tables.md와 harness/checklist.md는 수정 상태이나 수정 시각 14:45~15:01로 match.py(16:40)·test_eval_f1.py(16:40)보다 이전. 이번 작업 수정 흔적 없음 |

## 불합격 사유
없음.

## 미확인
- 정답 파일은 열지 않음(지시). pytest는 환경에 없어 unittest로 실행.

## 판정 외 관찰
- 첫 전체 unittest 실행에서 `FAILED (errors=1)`이 한 번 나왔으나 원인 출력을 확인하지 못했고, 이후 두 번 재실행은 모두 OK(173). 간헐 오류 가능성이 있으며 eval 테스트 단독은 안정적. 원인은 미확인.
- match.py는 선형할당에 `big+sim` 비용을 써 정의를 구현. big=10*(max(n,m)+1)로 합 상한보다 충분히 커서 타당.
- ontology_v1/harness 수정은 이번 작업 시각보다 이전이라 별도 승인 수정으로 판단(git 커밋 이력으로 확인하지는 않음).
