# KG 변환 및 고정 추출 결과의 첫 진단 대조

완료일: 2026-10-14. 브랜치: `2nd-yewon`.

## 완료 범위

API 호출 없이 기존 seed 구조와 이전 대화에서 고정한 172개 예측을 RDF KG로 변환했다. Rule·Document·Provenance 노드를 생성하고 SHACL(inference=none)을 통과했다. 원본 규칙 정답 86건은 평가 모듈에서만 읽었다. API 추출 테스트와 SBERT F1_content, Neo4j 서버 적재는 수행하지 않았다.

| 항목 | 결과 |
|---|---:|
| Station | 9 |
| Sensor | 22 |
| Rule | 172 |
| Document | 7 |
| Provenance | 274 |
| 서로 다른 노드 | 484 |
| RDF 트리플 | 4,697 |
| hasSensor | 22 |
| feedsInto | 3 |
| appliesToSensor | 86 |
| actionTarget | 105 |

Rule 172는 하위 클래스 172건과 같은 노드 집합이다. 상위/하위 클래스를 더해서 중복 집계하지 않는다. 모든 4,697개 트리플에 파일·행 또는 문서 단위·해시를 담은 출처 ledger가 있다. 정비 seed 8개는 예측 MAINT-01~08과 클래스·센서·우선순위가 모두 대응한다. 원본 정비 관계 16줄을 8개의 appliesToSensor 관계로 합치고 두 원본 행의 출처를 보존했다. seed 조치 문장이 추출 조치를 덮어쓰지는 않는다.

## 정답 86건 대조

**아래 수치는 F1_lexical_proxy이며, 프로젝트 주지표 SBERT F1_content가 아니다. 의미 정확도 또는 사람이 승인한 정답률로 해석하면 안 된다.**

- 입력: 고정 예측 172건, ZIP 내부 `kg_seed/ground_truth.csv` 원본 86건.
- 방법: condition+action의 소문자 유니코드 단어/숫자 다중집합 Dice 유사도, 문서별 Hungarian 일대일 할당 후 0.6 이상 연결. ID·인용문·클래스는 유사도 입력에 넣지 않았다.
- 연결 60건, 미연결 정답 26건, 미연결 예측 112건.
- 진단 Precision **0.3488**, Recall **0.6977**, F1_lexical_proxy **0.4651**.
- 정답 ID와 완전히 같은 예측 ID는 30건, 분할 전 원문 ID 계보로 연결되는 정답은 31건. ID 일치 자체는 내용 정답 판정이 아니다.

| 문서 | 예측 | 정답 | 텍스트 연결 | 진단 F1 |
|---|---:|---:|---:|---:|
| DS-ELEC-3300 | 5 | 0 | 0 | 평가 정답 없음 |
| DS-MECH-4400 | 2 | 0 | 0 | 평가 정답 없음 |
| DS-THERM-2200 | 4 | 0 | 0 | 평가 정답 없음 |
| SOP-001 | 30 | 29 | 26 | 0.8814 |
| SOP-002 | 49 | 27 | 8 | 0.2105 |
| SOP-003 | 11 | 11 | 11 | 1.0000 |
| SOP-004 | 71 | 19 | 15 | 0.3333 |

데이터시트 3개에는 이 정답 CSV의 대응 행이 없다. 전체 172건을 분모로 쓰는 수치는 이 11개 규칙도 미연결로 세므로 해당 규칙이 잘못됐다는 뜻이 아니다. SOP-004는 역할/구역과 심각도별로 원자화하여 71건, 정답은 19건이므로 일대일 비교의 분할 불일치도 크다. 부등호와 부정을 구별하지 못하는 토큰 지표의 한계를 테스트에 명시했다. 기존 예측을 정답에 맞춰 합치거나 고치지 않았다.

## 수치와 원문 차이에 대한 보충 진단

이 검사는 텍스트 대조 이후 별도로 추가한 진단이며 사전 고정된 주지표가 아니다. SOP-002의 같은 센서에 해당하는 경고/위험 상하한 88개 중 **84개 일치**, 센서 22개 중 **20개는 네 값 모두 일치**했다.

불일치 4개는 ST03_LABELLING_SPD의 critLo/warnLo/warnHi 및 ST04_PACKAGING_SPD의 critLo다. 예측 값은 제공된 원문 표와 일치한다. 원본 정답 CSV의 값이 다른 것이므로 추출 결과를 정답 수치로 수정하지 않았다. 상세 전후 값과 정확한 sourceQuote는 로컬 `evaluation/numeric_diagnostic.json`에 있다.

원본 정답의 일부 조치는 원문 규칙보다 추가적인 내용을 담는다. 예를 들어 운전 범위 유지 문장과 정답의 검사/정비 통보 조치가 다를 수 있다. 원문 근거 없는 조치를 추출 결과에 추가하지 않았다. 이 차이도 의미 평가의 별도 검토 대상이다.

## 검증과 한계

- 새 단위 테스트 10개 통과. Hungarian 구현은 작은 행렬의 완전 탐색 결과와 대조했다.
- 최종 RDF SHACL 통과 및 직렬화 후 재읽기 성공.
- 최종 구조·출처·정비 매핑·추출 불변성 검사 10개 통과.
- 기존 고정 산출물 56개와 predictions.jsonl의 해시가 모두 유지됐다.
- SBERT 라이브러리와 all-MiniLM-L6-v2 로컬 모델이 없고 새 설치/다운로드를 하지 않았으므로 **F1_content는 null(미실행)**이다.
- 사람 검토 미수행. 현재 대화 추출 결과를 사용했으며 OpenAI API로 생성한 결과가 아니다.
- Neo4j 가져오기용 Cypher 파일을 생성했지만 서버에 연결하거나 실행하지 않았다. 서버 적재/쿼리 검증 완료로 표시하지 않는다.
- `kg/`는 정비 seed 출처 보완 전의 첫 빌드이고 **최종본은 `kg_final/`**이다. 보완 전 빌드도 감사용으로 보존했다.

## 로컬 산출물

`kg_final/graph.ttl`, `kg_final/triple_lineage.jsonl`, `kg_final/neo4j_import.cypher`, `kg_final/shacl_report.txt`, `kg_final/maintenance_mapping.json`, `evaluation/metrics.json`, `evaluation/assignments.json`, 미연결 목록, `evaluation/numeric_diagnostic.json`, `verification.json`, `pre_evaluation_lock.json`, `evaluation_policy.md`, `contamination_log.json`, `manifest.json`.

Git에는 재현 코드·테스트·집계 보고서·평가 정책을 올린다. 원문, 정답 CSV, 개별 정답/예측 대조표, RDF 실데이터는 올리지 않는다.

## 다음 단계

1. 허용된 로컬 SBERT 환경을 준비한 뒤 사전 정의한 F1_content를 계산한다. 이번 진단 점수와 이름/결과를 분리한다.
2. 원자화 단위와 원문-정답 수치 차이에 대한 사람 검토를 기록한다. 기존 고정 추출은 유지하고 개선 실험은 새 버전으로 진행한다.
3. Neo4j 접속 환경에서 생성된 Cypher를 검토·적재하고 출처 및 Rule 검색 질의를 확인한다.
4. API 크레딧이 준비되면 별도의 API 추출 실험을 실행한다.
