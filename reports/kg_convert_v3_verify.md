# ③ 변환 v3 검증 보고서
- 판정: PASS

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| 1. sop003RowIndex = Provenance rowIndex, MAINT-01=2, MAINT-08=9, tables.jsonl 1부터 센 행의 ID | PASS | 8행 모두 일치(2~9). rows_normalized[idx-1][0]가 해당 MAINT ID, page도 일치. 독립 스크립트로 계산 |
| 2. 다른 열 동일 | PASS | seedAction은 nodes.csv와 일치, SOP 원문/정리 문구는 tables.jsonl 셀과 일치. 공백 정리 후 일치 3건(05,06,08)/불일치 5건, actionExactMatch 열과 같음 |
| 3. instances/summary 개수·장부 | PASS | Station 9, Sensor 22, hasSensor 22, feedsInto 3, MaintenanceRule 8, Document 7, appliesToSensor 8, Provenance 47. tripleCount 585, ledgerComplete true, triple_sources 585줄 |
| 4a. SHACL | PASS | Conforms: True (pyshacl, .venv) |
| 4b. raw 불변 / 누수 / 비밀키 | PASS | check_raw_unchanged, check_leakage, check_secrets 모두 PASS |
| 4c. 절대 경로 grep (src, tests) | PASS | 일치 0건 |
| 4d. 단위 테스트 | PASS | Ran 78 tests ... OK |
| 5. 재현성 | PASS | 변환 재실행 후 mapping, instances, summary.json이 실행 전 복사본과 diff/cmp 동일 |
| 6. 금지 경로 | PASS | git status ontology_v1, imaks_data 변경 없음 |
| 공통 나머지(git 추적, 이상값, 보고서 형식) | PASS | kg_build는 git ls-files에 없음. 변환 코드에 값 삭제·보간 없음(이번 변경 범위 확인 수준) |
| ③ 나머지(제외 대상, 출처, 원본 ID) | PASS(범위 한정) | 개수가 v2 결과와 동일하고 장부 누락·초과 0. 이번 변경 범위 밖은 v2 판정을 이어받음 |

## 불합격 사유
없음.

## 미확인
- 없음. 단, 처음 시스템 python(msys)에는 rdflib가 없어 .venv python으로 실행함.

## 판정 외 관찰
- 시스템 python으로 실행하면 rdflib 부재로 실패한다. 실행은 .venv 기준임을 문서에 명시해 두면 좋다.
