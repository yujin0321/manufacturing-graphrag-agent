# ③ 기존 KG 변환·Rule·Document 승격 검증 보고서
- 판정: PASS
- 근거 범위: 산출물과 imaks_data 원본, harness/checklist.md(공통 + ③)만 사용. 구현 보고서는 읽지 않았고 ground_truth도 열지 않았다.

## 항목별 결과
| 항목 | 결과 | 근거 |
| --- | --- | --- |
| 공통: check_raw_unchanged | PASS | "PASS: imaks_data/ 원본 불변 (1121개 파일)" |
| 공통: check_leakage | PASS | 기본 폴더와 `preprocessed ontology_v1 kg_build src` 지정 실행 모두 "PASS: 금지 컬럼 없음" (검사 CSV 44, JSON 8) |
| 공통: 절대 경로 없음 | PASS | `grep -rnE 'C:\\|/Users/|/home/' src tests` 결과 0건. 경로는 settings.py의 REPO_ROOT 기준 |
| 공통: 큰 산출물 git 미추적 | PASS | `git check-ignore -v`: kg_build/summary.json, instances.ttl 모두 `.gitignore:228:/kg_build/`. src/imaks_kg/kg/convert_seed.py, tests/test_kg_convert.py는 무시되지 않음. `git ls-files`에 kg_build·imaks_data 없음 |
| 공통: 이상값 삭제·보간 없음 | PASS | convert_seed.py에 interpolate/fillna/rolling/dropna/clip 없음. 센서 시계열은 다루지 않는 변환이며 값은 원본 문자열 그대로(아래 ID 대조) |
| ③-1 노드·엣지 수 | PASS | 독립 집계 nodes 115, edges 341. Station 9(Component 9와 이름·stationType·zone 전수 일치), Sensor 22, hasSensor 22(센서 22개 모두 정확히 1 스테이션, 별도로 monitors 엣지에서 구한 센서→스테이션과 22건 일치), feedsInto 3(ST01→02→03→04, 원본 feeds_into 3건과 동일), MaintenanceRule 8, Document 7, appliesToSensor 8. summary.json의 seed 집계(115/341, label·type별)와 일치. 차이(나머지 노드·엣지 미적재)는 CLAUDE.md 3장 확정 결정에 따름 |
| ③-1 적재 금지 항목 부재 | PASS | instances.ttl rdf:type 집계는 Provenance 39, Sensor 22, Station 9, MaintenanceRule 8, Document 7뿐. AnomalyEvent·Person·SafetyEvent·System·authorized_for 문자열 없음. `Zone` 매칭은 `im:zone` 속성 리터럴과 SOP_004_PersonnelZoneAccess.pdf 파일명뿐(클래스 아님) |
| ③-2 원본 ID 보존 | PASS | Station 9·Sensor 22·MaintenanceRule 8의 sourceNodeId가 nodes.csv의 같은 행(label, name/ruleId)과 전수 일치. Sensor sensorType·unit, Rule action→responseText·priority도 원문 일치. 엣지 출처 `edges.csv:L<n>`은 hasSensor 22건(각 2행), feedsInto 3건, appliesToSensor 8건(각 2행) 전수 확인: 행 번호=파일 순서+2, type(monitors/feeds_into/triggers/resolves)과 from/to가 일치 |
| ③-3 SHACL | PASS | run_shacl.py(--data instances.ttl --ont ontology.ttl --shapes shapes.ttl) 결과 "Conforms: True" |
| ③ MaintenanceRule/appliesToSensor | PASS | 산출물 8쌍이 edges.csv의 Sensor→Maintenance triggers 8건, Maintenance→Sensor resolves 8건과 집합 동일(양방향 일치). triggers 전체 22건 중 Maintenance 대상 8건만 사용 |
| ③ sourceDocument=SOP-003 근거 | PASS | tables.jsonl의 `SOP-003:p1:table1`(1쪽, "1. Predictive Maintenance Rules")에 MAINT-01~08이 행 1~8로 존재 |
| ③ action 원문 보존 | PASS | 매핑표 seedAction은 nodes.csv action과 8건 모두 동일, sop003ActionRaw는 표 text_raw의 줄바꿈까지 원문 그대로(`'Inspect and lubricate\nbearing'`). 임의 통일 없음 |
| ③ actionExactMatch | PASS | 공백 정리 후 직접 비교: MAINT-05·06·08 일치(true), 01·02·03·04·07 불일치(false). 열 값과 일치하여 3건 일치/5건 불일치 확인. 불일치 문구는 예를 들어 01 "main bearing" vs "bearing", 03 "Replace TEN sensor" vs "Replace sensor" |
| ③ Document 7개 | PASS | 7개 sourceSha256이 실제 PDF SHA-256과 일치. pageCount는 DS 3개 1쪽씩, SOP-001 2, SOP-002 2, SOP-003 1, SOP-004 2(합 10, 전처리 체크리스트의 쪽 합계 10과 일치). sourcePath는 `imaks_data/...` 상대 경로 |
| 공통/전체 테스트 | PASS | `unittest discover -s tests` 58개 OK |
| 재현성 | PASS | 변환 재실행 후 CSV 9개와 summary.json이 바이트 단위로 동일(cmp). instances.ttl은 505트리플 동형(rdflib isomorphic True) |

## 불합격 사유
없음.

## 미확인 항목
- 없음. (ground_truth는 지시에 따라 열지 않았고 이번 판정 항목에 포함되지 않음)

## 판정 외 추가 관찰
- 재현성 확인을 위해 변환을 한 번 재실행했으므로 kg_build가 같은 내용으로 다시 쓰였다(산출물 내용 불변 확인됨). 원본·구현 코드는 수정하지 않았다.
- Provenance 39건은 노드(Station 9+Sensor 22+MaintenanceRule 8) 단위이며, 엣지(hasSensor 등)의 출처는 CSV의 `sourceEdgeRow(s)` 열로만 있고 TTL 트리플에는 별도 provenance가 없다. 체크리스트 위반은 아니나 CLAUDE.md의 "모든 트리플에 출처" 기준을 엄격히 보면 후속 점검 대상이다.
- MaintenanceRule의 SOP-003 문서 내 위치(쪽·bbox)는 매핑표(sop003TableId/Page/RowIndex)에만 있고 Provenance는 seedCsv 출처다.
- 검증 스크립트: scratchpad v.py(저장소 밖).
