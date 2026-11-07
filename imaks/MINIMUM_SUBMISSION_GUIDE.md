# KG·Ontology·SHACL 최소 제출 안내

2026-10-06. 이 안내는 기존 산출물을 과제의 최소 요구사항에 맞춰 제출하기 위한 인덱스와 최신 작업 기록이다. 원래 ontology_v1의 설계·검증 파일은 수정하지 않는다.

## 요구사항과 제출 파일

| 과제 | 제출할 내용 | 현재 파일 |
|---|---|---|
| KG 질문 정의 | 질문 5개, 질문별 필요한 노드·관계·문서와 답변 한계 | ontology_v1/competency_questions.md, ontology_v1/queries/CQ1.rq~CQ5.rq |
| Ontology v1 설계 | 클래스 12개·관계 12개·속성 34개의 이름·의미·예시와 원본 대응 | ontology_v1/schema_tables.md, ontology_v1/ontology.ttl |
| SHACL 작성 | 핵심 제약 5그룹, 각각의 통과·실패 예제와 실제 실행 결과 | ontology_v1/shapes.ttl, ontology_v1/shacl_examples.md, ontology_v1/examples/의 10개 TTL |
| 재현 가능한 기록 | 코드·입력 파일/해시·처리 기록·실행 명령·미결정 사항 | ontology_v1/work_log.md, 이 안내의 최신 실행 기록, README_PREPROCESSING_IMPLEMENTATION.md, 관련 Python 코드 |
| 누수·결함 주의 | 입력/룰/평가 분리 정책, 구체적 결함 7건과 처리, 남은 한계 | ontology_v1/leakage_and_defects.md, KNOWN_DATA_DEFECTS.md |

이 최소 과제에 실제 Neo4j 서버 운영, 전체 LLM 추출86건 채점, 완성된 GraphRAG/Agent까지 포함해야 한다고 명시돼 있지는 않다. 이 단계들을 완료한 것으로 표시하지 않는다.

## 제출할 질문 5개

| ID | 질문 | 필요한 데이터 |
|---|---|---|
| CQ1 | ST02_SEALING은 어느 구역에 있고 어떤 센서·단위를 사용하는가? | Station,Zone,Sensor; locatedIn,hasSensor; sensorType,unit |
| CQ2 | ST02 전류 경고 때 추가로 확인할 센서와 근거 규칙은 무엇인가? | ST02_CUR→ST04_SPD 관계, RULE-ST02-04, SOP-001 원문 |
| CQ3 | ST02 온도가 212°C라고 가정하면 어떤 조치·대상 스테이션·문서 근거가 필요한가? | 온도 단위·임계값, RULE-ST02-02, actionTarget, sourceDocument |
| CQ4 | ST02 전류의 SOP 임계값과 전류 데이터시트의 연속 운전 사양은 어떻게 다른가? | SOP-002 표, DS_ELECTRICAL_SENSORS Note2, 문서 출처. 실제 설치 모델 확인 자료는 없음 |
| CQ5 | P043의 Chemical Storage 권한 기록이 있는가? 기록만으로 현재 입장을 허용할 수 있는가? | Person, Zone, authorizedFor, SOP-004 권한표, SOP-001 교육 조건. 교육 이수 자료는 없음 |

CQ3는 가정한 수치의 조회 예제이며 제어 명령을 실행하지 않는다. CQ2의 문서상 연결을 실제 고장 인과로 확정하지 않는다. CQ4·CQ5는 기록 조회와 현장 적용 판정을 구분하며, 없는 설치/교육 정보를 만들어내지 않는다.

## SHACL 제출 요약

| 제약 | 검사 대상 | 통과 예제 | 실패 예제 |
|---|---|---|---|
| C1 센서 정합성 | ID·센서 종류·단위·소속 | TMP/°C와 Station 소속 존재 | unit 누락 |
| C2 관측 정합성 | 센서·시각·유한값·단위 | 유한한 이상값도 올바른 형식/단위이면 통과 | TMP 단위를 A로 기록 |
| C3 문서 출처 | 규칙의 인용·문서·페이지·조건·조치 | 실제 SOP-001 p.1과 원문 인용 | 2쪽 문서에 p.99를 기록 |
| C4 임계값 정합성 | 유한한 5개 임계값·단위·순서 | 165 < 175 < 185 < 195 < 210°C | critLo=200, warnLo=175로 순서 위반 |
| C5 누수 차단 | 입력 프로필·정답/알람/GT 필드 | ML 입력에 정적 구조만 포함 | gt_id=GT-0007을 추가 |

C2는 관측이 정상 범위를 벗어났다는 이유로 실패시키지 않는다. 이상 탐지 대상값은 보존한다. C4는 관측값이 아니라 규칙 설정의 내부 순서를 검사한다. SHACL 통과는 고장 원인이나 자연어 추출 정확도의 증명이 아니다.

## 실제 실행 증거

- 최신 검증: experiments/joint_preprocessing_rerun_v1/graph/validation/validation_results.json
- 질문별 조회 결과: 같은 validation/competency_answers.json
- 각 제약의 SHACL 보고서: 같은 validation/C1_pass_report.ttl~C5_fail_report.ttl, 두 입력 그래프 보고서
- 합성 통과·실패 입력: ontology_v1/examples/의 10개 파일
- 기존 온톨로지 회귀 테스트: ontology_v1/validation/unit_test_results.json — 13개 통과
- 최신 RDF: experiments/joint_preprocessing_rerun_v1/graph/rdf/ml_metadata.ttl, rule_context.ttl

실제 입력 그래프 2개가 통과했고, 통과 예제 5개는 통과·실패 예제 5개는 거부됐다. 룰/문서 그래프를 ML 프로필로 바꾼 예제도 거부됐으며 질문 5개의 조회 결과를 확인했다.

## 최신 작업 기록 보충

기존 ontology_v1/work_log.md는 당시 기본3/11/1 기록을 포함한다. 제출에는 이 보충을 함께 넣어 설정을 혼동하지 않게 한다.

| 구분 | 설정·완료 내용 |
|---|---|
| 기존 기본 탐지 | 평균 3 / STUCK 11 / stride 1 유지 |
| 전체 조합 검증 선택 | 141,610개 탐색에서 2/10/2 선택; 2/11/2와 최상위 지표 동률 |
| 이번 보고 설정 | 사용자가 기존 평가 이벤트 F1 최고값 기준을 선택하여 10/11/1 재실행; 새 맹검 최적값은 아님 |
| 시계열 재실행 | 211,200행 원본 보존, 210,606개 10관측 윈도우, 시점별 21특징, 이벤트 F1 84.2% 재현 |
| 문서 재실행 | 공통 7문서/10쪽/24표 → 70청크와 70×384 임베딩, LLM 추출 입력 70건 |
| KG 재실행 | 기존 83정적 노드/269관계 보존, Document 7개/Rule 24개와 61관계 확장; RDF 2개 재검증 |
| Neo4j 변환 | 114노드/330관계 CSV와 적재 스크립트 생성; 실제 DB 적재 미실행 |
| 미완료 | LLM 문서 추출 및 86건 채점, 검출 경보의 KG 연결, 새 KG의 GraphRAG 연결, 3종 최종 평가 |

Rule 24개는 SOP 표 22개와 원문 수동 예제 2개다. LLM이 추출한 결과로 보고하지 않는다. 내부 부품·품질불량은 확장 후보 클래스만 있고 설치/불량 인스턴스를 추정해 추가하지 않았다.

## 결함과 누수 기록에 반드시 포함할 내용

1. quality는 STUCK 정답 프록시이므로 관측 입력에서 제외.
2. nominal/warn_hi/crit_hi/warn_lo/crit_lo는 룰용으로만 사용; 통계 탐지의 직접/유래 피처에서 제외.
3. MQTT status/alarms/readings quality 제거본을 입력으로 사용.
4. annotated 라벨, 정답 AnomalyEvent 14건, 추출 정답 86건은 평가용으로 분리. 사후 응답 로그는 참조용으로 격리.
5. 이상값 삭제·정상값 보정·평활화·결측 보간·패딩 미적용; 초기 특징 NaN과 처리 기록 보존.
6. ground_truth SPD 3행/5셀은 원본과 보정판을 별도 보관.
7. shift/day 불일치는 timestamp 기준으로 정렬/분할.
8. nodes_factory는 ID 충돌 6건으로 적재 제외.
9. monitors 양방향 44행을 Station→Sensor 22관계로 정규화하고 원본 lineage 보존.
10. access_events 범위 밖 156건·UNKNOWN 2건 분리.
11. AR-0005/AR-0012의 허위 SOP 참조를 표시하고 문서 근거 조치로 사용하지 않음.
12. GT-0007 dataset_severity와 rule_severity를 분리하고 정답을 일괄 재라벨링하지 않음.

미결정 사항에는 내부 부품 근거 자료/BOM, 실제 품질검사 자료, 설치 센서와 데이터시트 모델 대응, 교육 이수/권한 조건, 경보 연결 스키마, 시간대, 새 독립 평가 계획을 적는다. 기록해야 할 결정이 남았다는 뜻이며 이 최소 과제의 모든 작업이 미완료라는 뜻은 아니다.

## 재현 방법과 제출 순서

코드의 프로젝트 상대 경로를 보존한다. 필요한 원본 iMAKS_dataset.zip·preprocessed/common_v1의 공유 위치와 SHA-256을 함께 기록한다. 원본/모델 캐시가 없으면 그 조건을 적고 설치 환경·캐시 재사용 여부를 명시한다. .env·API 키·가상환경 전체는 제출물에 포함하지 않는다.

KG 최소 재현 코드: prepare_common_data.py, build_ontology_v1.py, verify_ontology_v1.py, test_ontology_v1.py, requirements-ontology.txt. 최신 별도 재검증은 rerun_joint_graph.py를 사용한다. 전체 전처리 기록에는 preprocess_detection_input.py, preprocess_mqtt_input.py, audit_known_defects.py, common_detection_data.py도 연결한다. 최신 센서/문서 코드의 의존 모듈과 명령은 README_PREPROCESSING_IMPLEMENTATION.md에 있다.

```powershell
.\.venv\Scripts\python.exe rerun_joint_graph.py --record-date 2026-10-06
.\.venv\Scripts\python.exe -m unittest test_ontology_v1 -v
```

제출 문서는 질문 정의 → 스키마 표 → SHACL 제약/예제 → 실행 결과 → 작업 기록/누수/결함/미결정 순으로 읽게 배치한다. TTL·예제·코드는 문서에 설명만 붙이지 말고 실제 파일을 함께 제출한다. 최종 검토에서 파일명/실행 경로/설정값이 같은지 확인한다.
