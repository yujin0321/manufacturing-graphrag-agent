# 재현 가능한 작업 기록

## 코드와 산출물

| 단계 | 재현 코드 | 기록·산출물 | 상태 |
|---|---|---|---|
| 센서 quality·임계값 정책 | preprocess_detection_input.py | preprocessed/sensors의 ML/룰 입력과 input_policy_report | 기존 완료; 최신 통합 입력은 common_v1 |
| MQTT 누수 제거 | preprocess_mqtt_input.py | mqtt_stream_input.json, mqtt_removal_report | 기존 완료 |
| 구체적 결함 7건 확인 | audit_known_defects.py | preprocessed/audit, KNOWN_DATA_DEFECTS.md | 기존 완료 |
| 센서·문서·KG·평가 공통 분리 | prepare_common_data.py | preprocessed/common_v1, COMMON_PREPROCESSING_REPORT.md, manifest | 기존 완료 |
| 공통 탐지 입력 연결 | common_detection_data.py, imaks_pipeline.py | 공통 manifest·스키마·센서/시각 키 검사, ML/룰 비교 | 기존 완료 |
| 정규화·윈도우 선택 | build_normalized_windows.py, sweep_window_sizes.py | 학습 median/MAD, 검증 선택 기록, 이전 10개 설정 기록 | 기존 완료; 기본 평균 윈도우 3개, STUCK 11개, stride 1 |
| 3개 윈도우 특징 | causal_features.py, build_selected_window_features.py, verify_window3_features.py | experiments/window3_features_v1, 특징 공식·단위·warm-up·검증 | 기존 완료; 완전한 3개 윈도우 211,068개 |
| KG 질문 정의 | ontology_v1/competency_questions.md | 질문 5개·필요 데이터·판정 가능 범위 | 2026-10-05 작성 |
| Ontology v1 | ontology_v1/ontology.ttl, schema_tables.md | 클래스·관계·속성 표와 OWL 어휘 | 2026-10-05 초안 |
| 안전한 RDF 변환 | build_ontology_v1.py | generated의 입력 프로필 2개·rule_lineage·해시 | 2026-10-05 구현 |
| SHACL·질문 실행 | verify_ontology_v1.py, test_ontology_v1.py | examples, queries, validation의 결과·해시 | 실제 실행 결과는 validation_results.json |

현재 작업은 전처리·탐지 설정을 변경하지 않고 별도 `ontology_v1`에 결과를 저장한다. 기존 데이터와 실험 결과의 보존 해시는 `generated/preservation_check.json`에 기록한다.

## 최소 재현 명령

프로젝트 루트에서 실행한다. 기존 프로젝트 `.venv`와 공통 입력을 사용하며 SHACL 패키지는 프로젝트 환경에 설치한다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ontology.txt
.\.venv\Scripts\python.exe build_ontology_v1.py --record-date 2026-10-06
.\.venv\Scripts\python.exe verify_ontology_v1.py --record-date 2026-10-06
.\.venv\Scripts\python.exe -m unittest test_ontology_v1
```

공통 입력은 `prepare_common_data.py`로 원본 ZIP에서 다시 생성할 수 있다. 현 상태 확인에는 생성 명령을 다시 돌릴 필요가 없으며, v1 빌더가 읽는 공통 파일의 manifest 해시를 먼저 검사한다. 원본 ZIP과 이전 실험 결과는 수정하지 않는다. 새 RDF는 탐지 또는 QA 코드에 자동 연결하지 않는다.

`--record-date`에는 재현 작업의 클라이언트 날짜를 적는다. 생략하면 날짜는 null이며 호스트 시계를 임의로 사용하지 않는다. 초기 설계는 2026-10-05에 시작했고, 제출용 검증은 2026-10-06에 완료한다.

## 새 빌더의 입력과 처리 내역

- 공통 nodes_static 83개, edges_static 269개, sensor_id_mapping 22개를 읽는다.
- Component 9개를 Station으로 매핑하며 노드 IRI에 원본 nodeId, sourceLabel에 원본 타입을 보존한다. Sensor.identifier는 시계열 sensor_id다.
- 정적 관계 269개를 보존한다. 추가 locatedIn 9개는 원본 zone 필드와 Zone의 정확한 이름 대응에서 생성한다. 공통 정규 엣지 ID와 ruleRef를 RDF.Statement로 기록한다. 정규 엣지 ID는 전처리에서 부여했으며 원본 행 대응은 공통 audit/edge_lineage.csv에 있다.
- PDF 7개를 해시로 확인하고 Document로 만든다. pageCount·제목·원문 경로·전체 추출 텍스트를 보존한다.
- SOP-002의 보정된 표 cells에서 센서별 임계값 Rule 22개를 생성한다. p.2 첫 표는 Server Room HUM 연속표로 처리한다. nominal 중앙값과 ± 표기는 nominalTolerance·nominalText로 함께 저장한다.
- SOP-001 p.1의 RULE-ST02-02와 RULE-ST02-04를 원문 인용과 위치가 있는 수동 예제 2개로 저장한다. 추출 방식은 수동/결정적 표 변환으로 명시한다.
- 라벨 없는 ML CSV의 센서별 첫 관측을 22개 스키마 예제로 변환한다. 전체 211,200행의 검출 입력을 RDF 표본으로 대체하지 않는다.
- evaluation 파일·ground_truth·nodes_factory·사후 이벤트/응답 로그는 읽지 않는다. 실제 소비한 입력 경로와 SHA-256은 build_summary·build_manifest에 남긴다.
- 두 그래프, 5개 통과 예제, 5개 실패 예제 및 ML에 규칙 그래프를 잘못 넣은 예제를 실제 pySHACL로 검사한다. 질문 5개의 SPARQL 결과도 저장한다.

## 미결정 사항

| 항목 | 현재 선택·보류 이유 | 다음 결정에 필요한 근거 |
|---|---|---|
| 탐지 경보의 이벤트 스키마·그래프 연결 | 새 v1에는 평가 사건과 검출 경보를 모두 넣지 않았다 | 검출 시점·증거·모델 버전·경보 병합 방식 및 별도 입력 프로필 |
| 내부 부품 구조 | InternalComponent 클래스만 확장 후보로 선언, 인스턴스 없음 | BOM·도면·설치/정비 매뉴얼의 근거 |
| 실제 품질불량 | QualityDefect 클래스만 확장 후보로 선언, 인스턴스 없음 | 실제 검사 데이터와 판정 기준 |
| 실제 설치 센서와 데이터시트 대응 | 일반 문서 비교만 수행 | 설치 모델/품번 자료 |
| 출입 권한 조건 | 원본 authorized_for를 보존하되 교육 이수·문서 조건 충돌은 보류 | 교육 기록, 역할 조건의 우선순위 합의 |
| LLM 규칙 추출 | v1 Rule 24개는 LLM 결과가 아님 | 원문 입력·모델/프롬프트 버전·86건 독립 평가 절차 |
| 시간대 | 원본 timestamp 시간대 미지정 유지 | 데이터 생성 규약 확인 |
| 평가 분할·후속 튜닝 | 기존 시간 분할·평균 3개·STUCK 11개 유지. 테스트 결과는 이미 확인함 | 공식 이벤트 분할과의 비교 및 새 독립 평가 필요 여부 |
| Neo4j·GraphRAG 연결 | RDF와 질의 예제만 생성 | 선택한 그래프 저장소와 동일한 입력 격리·출처 규약 |

## 완료로 보고할 수 있는 범위

질문 정의, Ontology v1 어휘/표, 핵심 SHACL 5그룹과 예제, RDF 변환·검증 코드, 해시/누수/결함/미결정 기록은 이 제출물의 범위다. 전체 시계열 RDF 적재, Neo4j 서비스, 검출 이벤트 연결, LLM 추출 86건 평가, LLM/Vector RAG/GraphRAG의 최종 정확도 비교는 별도 작업이다.
