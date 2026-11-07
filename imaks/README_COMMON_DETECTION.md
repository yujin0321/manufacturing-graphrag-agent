# 공통 전처리 입력과 탐지 코드 연결

현재 평균3 설정의 변화량·변화율·통계 특징도 생성한다. 실행 결과의 causal_features.csv.gz에는 시점별 21개 숫자 특징과 준비 메타데이터가 있고 정답은 없다. [README_WINDOW3_FEATURES.md](README_WINDOW3_FEATURES.md)에 수식·단위·재사용 배열·분리 정답을 기록했다.

2026-10-05: **평균3/STUCK11을 현재 기본 탐지 설정으로 적용했다.** 이동 간격 1개/30초, 순간 임계값 6·평균 임계값 4를 사용하며 추가 튜닝하지 않는다. [README_APPLIED_WINDOW.md](README_APPLIED_WINDOW.md)에 적용·검증 내용을 기록했다. 평균10의 기존 결과는 비교용으로 보존했다.

후속 정규화·윈도우·특징 데이터는 별도 `experiments/robust_windows_v1`에 생성했다. [README_NORMALIZED_WINDOWS.md](README_NORMALIZED_WINDOWS.md)에 관측 수·stride·시간 범위·피처·정답 연결을 기록했다. 기존 탐지 결과를 덮어쓰지 않았다.

2026-10-03. imaks_pipeline.py와 evaluate_threshold_policy.py의 탐지 실행은 `preprocessed/common_v1`의 별도 ML/룰 입력을 읽는다. 원본 ZIP으로 자동 복귀하는 경로는 없다.

## 입력 경로와 분리

| 용도 | common_v1 내부 파일 |
|---|---|
| 강건 통계 탐지기 | inputs/sensors/timeseries_ml_input.csv |
| 임계값 룰 탐지기 | inputs/sensors/timeseries_rule_input.csv |
| 행 정답 | evaluation/row_labels.csv |
| 이벤트 정답 | evaluation/anomaly_events.csv |
| 분할 검증 | metadata/sensor_time_metadata.csv |

common_detection_data.py는 manifest의 SHA-256으로 파일을 확인한다. 파일 부재·해시 불일치·스키마 불일치·관측값 차이·정답 키 누락/중복/추가·분할 불일치 시 오류를 낸다. 새 데이터가 필요하면 원본에서 prepare_common_data.py로 재생성한다.

ML 입력은 정답·quality·시간 라벨·임계값 컬럼을 포함하지 않는다. fit_scores는 룰 입력이나 정답 입력을 넘기면 거부한다. ML 통계는 value만 사용하고 sensor_id/timestamp로 그룹화한다. 룰 방식의 value/warn_hi/warn_lo 비교는 별도 데이터에서 수행하며 룰 판정 플래그를 통계 탐지기의 scored 프레임에 추가하지 않는다.

행 정답과 룰 입력은 sensor_id + timestamp로 one-to-one 조인한다. 조인 후 탐지 관측의 순서와 인덱스를 유지한다. 원본 정답 파일의 행 번호로 정답을 붙이지 않는다. 메타데이터·행 정답·이벤트의 split이 탐지 코드의 기존 분할과 일치하는지도 확인한다.

## 실행

```powershell
.\.venv\Scripts\python.exe imaks_pipeline.py --detection-only
# 같은 연결을 사용한 임계값 정책 비교 진입점
.\.venv\Scripts\python.exe evaluate_threshold_policy.py
```

두 명령은 `experiments/common_v1_detection_window3`에 평균3/STUCK11 결과를 저장한다. 기존 `experiments/common_v1_detection`은 평균10 비교 결과로 보존한다. common_v1 원본 산출물도 수정하지 않는다.

`imaks_pipeline.py`를 옵션 없이 실행하는 전체 파이프라인도 동일한 평균3/STUCK11 설정을 사용하며 `pipeline_outputs_window3`에 저장한다. 기존 EDA 그래프·pipeline_outputs/sources/pages.json은 읽기만 한다. 기존 pipeline_outputs는 덮어쓰지 않는다. 센서 연결만 확인할 때는 위 detection-only 명령을 사용한다. legacy load_data의 첫 프레임은 **룰용**이며 ML에는 load_common_detection_data().ml을 사용한다.

## 기록되는 설정과 결과

- input_provenance.json: 실제 입력 경로·SHA-256·행 수·키 조인·피처 정책.
- experiment_config.json: 적용한 평균3/STUCK11·stride·정규화·분할 경계 초기화·선택 출처.
- detection_metrics.csv: 방식별·분할별 행/이벤트 지표, 임계값 사용 여부.
- temporal_splits.csv: 학습/검증/평가 행 수·시각·이벤트 수.
- selected_model.json: 앞서 검증으로 선택한 고정 설정과 원래 선택 기록의 SHA-256.
- fixed_config_validation_metrics.csv: 적용한 고정 설정의 검증 지표. 임계값이나 윈도우를 다시 선택한 표가 아니다.
- *_event_matches.csv와 *_predicted_events.csv: 탐지·누락·경보 상세.

현재 실행은 학습 구간 median/MAD, 3개 trailing 평균, 11개 trailing 표준편차, stride=1을 사용한다. sensor·시간 공백·분할 경계에서 윈도우를 초기화한다. 선택 JSON·검증 표·protocol의 해시와 실제 공통 입력이 선택 당시 입력과 같은지 확인한다. 점수의 실제 윈도우와 설정 기록이 다르면 오류를 낸다. 룰 비교는 서로 다른 두 탐지기 비교이며 같은 모델의 임계값 피처 ablation이 아니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m unittest test_applied_window test_pipeline test_common_detection_data -v
.\.venv\Scripts\python.exe verify_applied_window.py
```

정답 순서 변경·누락·추가·중복, 임계값의 ML 전달 거부, 공통 데이터 부재 시 raw로 돌아가지 않는 동작과 기존 시간/이벤트 평가를 확인한다. 연결 변경으로 모델 구조나 검색·Agent를 추가 구현하지 않았다.

2026-10-03 실행 검증: 테스트 15개 통과. 실제 공통 데이터 211,200행과 이벤트 14건으로 detection-only 실행 완료. 평가 이벤트 8건 중 룰은 7건, 통계 탐지기는 8건을 탐지했고 이벤트 F1은 각각 34.1%, 84.2%였다. 결과는 기존 임계값 미사용 통계 탐지기 실행과 같으며, 이번 입력 연결로 성능 개선을 주장하지 않는다.
