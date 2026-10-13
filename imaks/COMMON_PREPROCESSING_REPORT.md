# iMAKS 공통 전처리 결과

후속 연결 완료: 탐지 코드가 common_v1 입력을 읽도록 연결했다. [README_COMMON_DETECTION.md](README_COMMON_DETECTION.md)에 실행 방법을 정리했다. 아래 '자동 연결하지 않았다'는 전처리 생성 시점의 기록이며 현재 탐지 코드의 센서 입력에는 적용되지 않는다. 기존 저장 결과·노트북은 새 실행 결과로 대체하지 않았다.

2026-10-03. 결과는 `preprocessed/common_v1`에 별도 저장했다. 원본 ZIP과 기존 `preprocessed/sensors`, `pipeline_outputs`, `eda_outputs`의 데이터를 덮어쓰지 않는다.

## 1. 센서 시계열

| 점검 | 결과 |
|---|---:|
| 관측 행 | 211,200 |
| 센서 | 22 |
| 잘못된 timestamp | 0 |
| 결측·비수치·무한 관측값 | 0 |
| 센서+시각 중복 행 | 0 |
| 센서별 30초 간격 이탈 | 0 |
| KG ID·소속·유형·단위 대응 오류 | 0 |
| 관측값 변경 | 0 |

시간 범위는 2026-01-06 06:00:00~2026-01-09 13:59:30이다. 시간대 정보는 원본에 없으므로 UTC/KST로 추정해 변환하지 않았다. 센서 ID를 임의로 변경하지 않았고 22개 모두 정식 KG와 대응했다. `°C`는 실제 UTF-8 파일에서 정상이다. 이전 터미널의 깨진 출력 때문에 단위를 수정하지 않는다.

`inputs/sensors/timeseries_ml_input.csv`는 timestamp, zone, station_id, sensor_id, sensor_type, value, unit만 포함한다. `timeseries_rule_input.csv`에는 nominal/warn_hi/crit_hi/warn_lo/crit_lo를 추가한다. quality와 annotated 정답 필드는 두 방식에서 제외한다. 현재 모델 피처는 value이며 나머지는 식별·설명용 메타데이터다. 임계값에서 만든 거리·초과 플래그나 문서·KG에서 가져온 임계값도 ML 피처로 사용하지 않는다.

센서별 timestamp로 정렬했으므로 이전 원본 순서의 정답 배열을 위치로 붙이면 안 된다. `sensor_id + timestamp`로 one-to-one 조인한다. `metadata/sensor_time_metadata.csv`의 source_row로 원본 CSV 논리 행을 추적할 수 있다.

잘못 해석될 수 있는 day/shift/batch_id는 입력에서 제외하고 메타데이터에 original_*로 보존했다. calendar_date, calendar_day_index, clock_shift를 별도로 파생했다. clock_shift는 Morning=[06:00,14:00), Afternoon=[14:00,22:00), 나머지 OFF_SHIFT라는 명시적 비교 정책이다. 야간 관측을 삭제하지 않았다. batch를 새로 추정하지 않았다.

이상값 삭제, 결측 보간, 평활화, 다운샘플링, 정규화는 수행하지 않았다. 각 팀원은 모델별 가공을 별도 파일로 만들고 기록한다. 윈도우도 공통 산출물로 고정하지 않았다. 길이·이동 간격·최소 관측 수·특징·분할 경계를 기록하고 실시간 실험은 과거와 현재만 사용한다. 메타데이터 segment_id는 센서/시간 공백/평가 분할 경계를 넘지 않게 윈도우를 만드는 데 사용한다.

### MQTT

`inputs/sensors/mqtt_stream_input.json`은 21,600건을 그대로 유지하고 status/alarms 및 readings 내부 quality를 제거했다. 관측값·메시지 순서는 보존했다.

MQTT 센서 관측 52,800개는 모두 CSV 키와 연결되지만 값이 같은 것은 27개, 다른 것은 52,773개다. 두 소스를 서로 같은 측정값으로 취급하거나 합쳐 중복 제거하지 않는다. CSV와 스트림 실험을 구분하고, 스트림의 severity를 CSV 관측값으로 재계산하지 않는다.

## 2. SOP·데이터시트

7개 PDF, 10페이지, 24개 표를 추출했다. 문서 ID·파일 SHA-256·페이지 ID를 기록하고 원본 PDF, 원문 텍스트, 레이아웃 텍스트, 표 셀과 bbox, 원문 줄의 문자 오프셋, 좌표가 있는 단어 목록을 저장했다. 청킹·임베딩·LLM 추출은 수행하지 않았다.

각 줄의 start/end는 저장된 pypdf text의 문자 위치이며 원본 PDF 바이너리 오프셋이 아니다. PDF 좌표는 point 단위로 왼쪽/위쪽 기준이다. 다른 텍스트 추출 방식의 위치를 혼용하지 않는다.

원문 전체 텍스트와 렌더링을 보존하며, 표 24개는 구조를 유지한다. pdfplumber가 σ·화살표를 잘못 읽은 6셀은 동일 페이지 pypdf 텍스트와 렌더링으로 대조해 복원했다. 변경 전 셀과 수정 로그를 함께 보존했다. 단어 좌표 목록은 pdfplumber의 원출력이므로 모델 입력은 pages의 원문 또는 보정된 tables.cells를 사용한다. SOP-002 p.2 첫 표는 p.1의 Server Room 표의 연속임을 명시했다.

SOP와 데이터시트의 상충 주장·단위·지속시간·부등호를 임의로 통일하거나 삭제하지 않았다. 후속 추출에서도 출처별로 유지한다. 원문 PDF에 있는 부품 언급은 보존했으나 근거 없는 부품 인스턴스를 생성하지 않았다.

## 3. 기존 KG

| 점검/분리 | 결과 |
|---|---:|
| 원본 노드/엣지 | 115 / 341 |
| 연결 대상이 없는 엣지 | 0 |
| 완전히 동일한 엣지 중복 | 0 |
| monitors 역방향 중복 정규화 | 44행 → 22개 has_sensor |
| 입력용 정적 노드/엣지 | 83 / 269 |
| 평가용으로 분리한 동적 노드/엣지 | 32 / 50 |

nodes_factory는 사용하지 않는다. 원본 Component는 스테이션 수준 의미를 기록하되 label·ID를 보존한다. 후속 온톨로지 매핑 시 Station으로 매핑한다.

기존 파이프라인과 같은 `Component(스테이션) → has_sensor → Sensor` 방향을 사용한다. 두 원본 monitors 행은 같은 정규 엣지에 연결하고 lineage를 저장했다. authorized_for 등 다른 유효 관계는 유지했다. 기존 correlates_with 한 건은 SOP의 ruleRef가 있는 사전 문서 지식으로 보존했으며 시계열에서 새로 발견했다고 주장하지 않는다.

AnomalyEvent 14개뿐 아니라 SafetyEvent 10개와 Maintenance 8개도 입력용 정적 KG에서 분리했다. 해당 노드에 연결된 관계와 gtId/severity/causedBy/시각/임계값 등의 속성도 입력에서 제외했다. 전체 원본 그래프는 evaluation/kg에 보존한다. Rule·Document 노드 승격, RDF·Neo4j 변환, OWL 설계, 관계 확장은 각자의 후속 구현 범위다.

## 4. 평가 정답·구체적 결함 적용

정답 211,200행(이상 1,460행), 이벤트 14개, 규칙 86건을 evaluation에 분리했다. 정답 디렉터리와 audit의 라벨·충돌 기록은 탐지 입력이나 GraphRAG 검색 코퍼스로 적재하지 않는다.

| 결함 | 적용 결과 |
|---|---|
| SPD 3행 오류 | 원본 기준을 보존하고 5셀만 바꾼 별도 평가 기준과 로그 생성 |
| shift/day 불일치 | 원본 메타데이터 보존, timestamp 기반 입력·분할과 파생 시간 정보 생성 |
| nodes_factory | 적재 제외 |
| monitors 양방향 | 기존 has_sensor 방향으로 정규화, 원본 대응 보존 |
| access 범위 이탈·UNKNOWN | 기간 안 292건/밖 156건 분리, UNKNOWN 2건은 미상으로 보존 |
| 허위 SOP 참조 | AR-0005/AR-0012의 참조 오류를 표시, 사후 기록은 보존 |
| GT-0007 severity | WARNING 유지, 별도 rule_severity=CRITICAL 및 critical_rows=3 기록 |

rule_severity는 이벤트 구간에서 엄격한 `value < crit_lo` 또는 `value > crit_hi`가 한 번이라도 있으면 CRITICAL, 아니면 WARN 초과가 있으면 WARNING, 없으면 NORMAL로 정의했다. 이 단순 수치 판정과 원본 라벨이 다른 이벤트는 6건이며, STUCK처럼 범위 안에서도 발생하는 이상이 있으므로 차이 전부를 정답 오류로 보지 않는다.

원본 규칙과 SPD 수정 기준으로 평가 결과를 구분한다. 수정 범위는 확인된 5셀뿐이며, 나머지 규칙 필드까지 완전 검증했다고 주장하지 않는다.

기존 평가 분할을 유지했다. Jan 6 학습 47,520행/2이벤트, Jan 7 검증 63,360행/4이벤트, Jan 8~9 평가 100,320행/8이벤트다. 14개 이벤트 모두 분할 경계를 가로지르지 않는다. 공식 dev/test 이벤트 분할로 명명하지 않는다. 정답 기반 튜닝은 검증 구간으로 제한한다.

## 기존 작업과의 관계

기존 파일은 수정하지 않았다. 새 ML/룰 CSV의 시간 라벨 제외·센서별 정렬은 기존 CSV와 다르므로 행 위치 대신 키로 연결한다. KG 관계 방향과 기존 평가 분할은 유지한다. 기존 imaks_pipeline 및 저장된 노트북을 새 데이터에 자동 연결하거나 이전 성능을 새 전처리 결과로 재기재하지 않았다.

개인별 실험은 `experiments`에 별도 저장하고 다음 설정을 남긴다.

- 입력 경로·해시, feature_columns, 모델·버전, seed.
- 정규화 방법, fit 구간, 결측·평활화 처리.
- 윈도우 길이(관측 수·초), stride, 최소 관측 수, 생성 특징, 경계 초기화.
- 사용한 학습/검증/평가 분할과 임계값 사용 여부.
- 문서 청킹 크기·겹침·임베딩/LLM·프롬프트 및 KG 매핑 버전.

공통 기준은 정규화·윈도우 크기·모델을 강제하지 않는다. 이전 탐지기의 10개 평균/11개 표준편차 윈도우도 공통 표준으로 확정한 것은 아니다.

## 재현

```powershell
.\.venv\Scripts\python.exe prepare_common_data.py
```

출력 관측값의 원본 일치, 행 수, 금지 컬럼·키 부재, 이벤트/규칙 수를 저장 후 다시 읽어 검증한다. manifest.json에 원본·출력 SHA-256, summary.json에 점검 결과를 기록한다. PDF 페이지 렌더링과 표 추출을 대조했다. 원본 문서 자체의 사실 정확성을 보증하는 절차는 아니다.
