# iMAKS 탐지 입력 정책

KG 질문 5개, Ontology v1 정의표·OWL, 핵심 SHACL 5그룹과 예제, 재현·누수·결함 기록은 [README_ONTOLOGY_V1.md](README_ONTOLOGY_V1.md)에 추가했다. 별도 RDF 초안이며 현재 탐지 코드의 공통 입력·윈도우 설정은 그대로 유지한다.

현재 평균3/STUCK11의 변화량·변화율·통계 특징도 보완했다. [README_WINDOW3_FEATURES.md](README_WINDOW3_FEATURES.md)에 피처 목록·수식·단위·초기 관측 처리와 재사용 배열을 기록했다.

개인별 첫 정규화·윈도우 실험 데이터도 생성했다. [README_NORMALIZED_WINDOWS.md](README_NORMALIZED_WINDOWS.md)를 참조한다. 학습 구간 센서별 median/MAD와 trailing 10/11개, stride 1개를 사용하며 공통 관측값은 보존한다.

평균 윈도우 3·5·10·15·20·30·60·120개 비교는 [README_WINDOW_SWEEP.md](README_WINDOW_SWEEP.md)에 기록했다. 검증 선택 3개와 기존 평가의 사건 단위 F1 최고 10개를 구분한다. 2026-10-05에 검증 선택 평균3/STUCK11을 기본 코드에 적용했다. [README_APPLIED_WINDOW.md](README_APPLIED_WINDOW.md)를 참조한다. 원래 비교 결과는 experiments/window_sweep_v1에 보존한다.

## 공통 전처리 완료 (2026-10-03)

탐지 입력 연결도 완료했다. [README_COMMON_DETECTION.md](README_COMMON_DETECTION.md)의 detection-only 명령으로 common_v1의 ML/룰 입력과 키로 연결된 평가 정답을 사용한다. 현재 평균3 결과는 experiments/common_v1_detection_window3에 저장하고, 기존 평균10 결과는 experiments/common_v1_detection에 보존한다.

공통 작업 결과는 `preprocessed/common_v1`에 별도로 생성했다. [COMMON_PREPROCESSING_REPORT.md](COMMON_PREPROCESSING_REPORT.md)에 센서·문서·KG·정답 처리 결과, 기존 작업과의 차이, 개인별 실험 기록 기준을 정리했다. 기존 산출물은 보존한다.

아래 초기 결함 점검의 '수정본 적용 전' 상태는 당시 기록이다. common_v1에는 별도 SPD 수정 평가 기준, 시간 메타데이터, KG 중복 정규화, access 범위 분리, 참조 오류 표시, severity 충돌 기록을 적용했다. 원본·이전 산출물은 여전히 변경하지 않았다.

## 확정 정책

**룰 베이스라인은 raw의 nominal, warn_hi, crit_hi, warn_lo, crit_lo 사용을 허용한다. 학습·통계 모델은 이 5개 컬럼을 입력 및 파생 피처 생성에 사용하지 않는다.**

- `quality`는 두 방식 모두 사용하지 않는다. STUCK 정답과 일치하는 누출 컬럼으로 처리한다.
- ML에서 임계값 초과 여부, value/nominal, 임계값까지의 거리, 임계값을 이용한 정상 구간 선별 등 간접 사용도 금지한다.
- 모델의 정규화·스케일 추정은 학습 구간 관측값으로 수행한다. 검증·평가 데이터에서 통계를 추정하지 않는다.
- 센서 ID와 시간 등은 구간·센서 식별용 메타데이터다. ML CSV의 모든 컬럼을 자동으로 피처로 사용하지 않는다. 현재 통계 탐지기는 sensor_id, timestamp, value만 사용한다.
- 제공 임계값은 룰 방식에 사전 제공된 설정으로 명시한다. 원문 SOP와의 일치 여부를 이번 단계에서 검증한 것은 아니다.

## 파일

### 구체적 결함 7건

일반적인 중복·결측 점검 외에 다음 7건을 필수 점검 대상으로 지정한다. 상세 값·근거·처리 정책은 [KNOWN_DATA_DEFECTS.md](KNOWN_DATA_DEFECTS.md)에 있다. 현재 상태는 **원본 대조·정책 명시 완료, 수정본 적용 전**이다.

1. ground_truth.csv SPD 3행의 임계값 5셀 오류.
2. shift·day 라벨과 timestamp 불일치; timestamp 기준 정렬·분할.
3. nodes_factory.csv 폐기(적재 제외); nodes.csv와 ID 충돌 6건.
4. monitors 양방향 44행을 22개 연결로 정규화.
5. access_events 센서 기간 밖 156건·UNKNOWN 2건을 구분 관리.
6. alarm_response_log의 존재하지 않는 SOP-001 §5 참조 2건.
7. GT-0007 원본 WARNING과 CRITICAL 하한 위반 3행의 충돌.

`audit_known_defects.py`로 이 7건을 다시 대조하고 `preprocessed/audit/known_defects_report.json`에 기록한다. 원본 정답을 자동으로 덮어쓰지 않는다.

원본 ZIP은 수정하지 않는다. `preprocess_detection_input.py`를 실행하면 `preprocessed/sensors`에 생성한다.

| 파일 | 용도 | quality | 임계값 5개 |
|---|---|---|---|
| timeseries_detection_input.csv | quality를 제거한 공통 보관본 | 제외 | 유지 |
| timeseries_rule_input.csv | 룰 베이스라인 입력 | 제외 | 유지 |
| timeseries_ml_input.csv | 학습·통계 탐지기 입력 | 제외 | 제외 |

각 파일의 행 수·순서·보존 컬럼 값이 원본과 같은지 검증하고 `input_policy_report.json`에 기록한다. 이는 위 6개 컬럼의 정책 적용이며, 다른 컬럼의 누출·인코딩·결측 처리를 완료했다는 뜻은 아니다.

## 두 조건의 보고

`evaluate_threshold_policy.py`는 같은 학습/검증/평가 분할과 정답으로 아래 두 방식을 비교한다.

1. **임계값 사용:** `sop_threshold`, value가 warn_hi보다 크거나 warn_lo보다 작으면 경보.
2. **임계값 미사용:** `robust_causal`, 학습 구간 median/MAD와 과거 윈도우 기반 통계 탐지. STUCK 허용 오차는 raw nominal 대신 학습 중앙값으로 계산한다.

현재 ML 계열 비교 대상은 강건 통계 방식이며 Isolation Forest/Autoencoder 등 학습 모델을 추가로 구현하거나 평가한 것은 아니다. 위 결과는 서로 다른 두 탐지기 비교다. 동일 모델에서 임계값 피처의 영향만 분리한 실험으로 해석하지 않는다.

행 단위 Precision/Recall, 이벤트 단위 Precision/Recall/F1, 누락 이벤트, 추가 경보, 탐지 지연을 함께 보고한다. 기존의 1/6 학습, 1/7 검증, 1/8~1/9 평가 분할을 유지하며 공식 dev/test 이벤트 분할과는 구분한다. 정답은 검증 단계 모델 선택과 평가에만 사용한다.

결과는 `preprocessed/threshold_policy_evaluation`에 별도 저장한다. 과거 `pipeline_outputs` 결과·노트북은 이전 nominal 사용 조건의 결과일 수 있으므로 새 조건 결과로 인용하지 않는다.

## 실행 결과 (2026-09-30)

입력 파일은 모두 211,200행이며, 남겨 둔 셀 값과 행 순서의 원본 일치를 검증했다. 정책 관련 회귀 검증을 포함한 테스트 8개가 통과했다.

평가 구간 1/8~1/9의 정답 이벤트는 8건이다.

| 방식 | raw 임계값 사용 | 행 Precision | 행 Recall | 이벤트 Precision | 이벤트 Recall | 이벤트 F1 | 탐지/정답 이벤트 | 생성 경보 |
|---|---|---:|---:|---:|---:|---:|---|---:|
| SOP 임계값 룰 | 사용 | 100.0% | 39.5% | 21.2% | 87.5% | 34.1% | 7/8 | 33 |
| 강건 통계 + 과거 윈도우 | 미사용 | 93.5% | 71.4% | 72.7% | 100.0% | 84.2% | 8/8 | 11 |

이벤트 매칭은 동일 센서·시간 구간 겹침에 대한 일대일 매칭이다. 한 사건에서 여러 경보 조각이 발생하면 추가 조각은 미매칭 경보로 계산하므로 행 정밀도와 이벤트 정밀도가 다를 수 있다. 작은 평가 집합의 결과이며 일반적인 모델 우열을 입증하지 않는다. 전체 split별 결과는 `preprocessed/threshold_policy_evaluation/detection_metrics.csv`에 있다.

## 실행

### MQTT 스트림 입력 (2026-10-03)

`preprocess_mqtt_input.py`는 원본 ZIP의 `sensors/mqtt_payloads.json`에서 별도 `preprocessed/sensors/mqtt_stream_input.json`을 생성한다.

- `status`와 `alarms`를 제거한다. 비어 있는 alarms도 포함하여 모든 메시지에서 키 자체를 제거한다. ALARM 메시지를 삭제하거나 RUNNING으로 바꾸지 않는다.
- 센서별 `readings.*.quality`도 앞서 정한 quality 미사용 정책에 따라 제거한다. 제거 대상 키는 중첩 위치에서도 제거한다.
- 룰·ML 방식 모두 이 스트림용 파일을 사용한다. 원본의 alarm type/severity/message를 탐지 또는 Agent의 관측 입력으로 사용하지 않는다. 원본은 평가·감사용으로 보존한다.
- 시각, 센서 관측값·단위, 메시지 ID, topic, device 정보, 메시지 순서는 보존한다. 관측값은 수정·재계산하지 않는다.
- 결과를 다시 읽어 모든 보존 값·자료형·순서를 원본과 대조하며, 제거 대상 키가 남지 않았는지 검증한다. 실행 기록은 `preprocessed/sensors/mqtt_removal_report.json`에 저장한다.
- 이번 작업은 위 키의 제거에 한정된다. CSV와 MQTT의 관측값 일치 여부·다른 컬럼 누출·단위 정규화는 별도 점검 대상이다.

```powershell
.\.venv\Scripts\python.exe preprocess_detection_input.py
.\.venv\Scripts\python.exe preprocess_mqtt_input.py
.\.venv\Scripts\python.exe evaluate_threshold_policy.py
```
