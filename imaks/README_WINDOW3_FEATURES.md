# 3개 윈도우의 변화량·변화율·통계 특징

2026-10-05. 검증에서 선택한 평균3/STUCK11 설정에 맞춰 재사용할 센서 특징을 계산한다. 관측·이동 간격은 30초다. 3개 관측의 명목 길이는 90초이며 실제 첫~끝 시각 차이는 60초다. 정규화는 학습 구간에서만 구한 센서별 median/MAD를 그대로 사용한다.

## 특징 정의

| 특징 | 원래 단위의 필드 | 정규화값 필드 | 계산 |
|---|---|---|---|
| 평균 | mean_value_3 | mean_z_3 | 과거 2개+현재 관측의 평균 |
| 표준편차 | std_value_3 | std_z_3 | 3개 관측의 모집단 표준편차, ddof=0 |
| 최소·최대 | min_value_3 / max_value_3 | min_z_3 / max_z_3 | 3개 관측의 최소·최대 |
| 범위 | range_value_3 | range_z_3 | 최대−최소 |
| 직전 대비 변화량 | delta_value_1 | delta_z_1 | 현재−직전 관측 |
| 직전 대비 분당 변화율 | rate_value_1_per_min | rate_z_1_per_min | 직전 변화량 ÷ 0.5분 |
| 윈도우 처음~끝 변화량 | change_value_3 | change_z_3 | 현재−2개 전 관측 |
| 윈도우 처음~끝 분당 변화율 | rate_value_3_per_min | rate_z_3_per_min | 윈도우 변화량 ÷ 실제 시간차 1분 |

분당 변화율은 끝−처음의 변화율이며 선형회귀 기울기가 아니다. 부호를 보존하여 상승·하락 방향이 남는다. 원래 단위의 변화량은 센서 unit과 같고 변화율은 unit/분이다. 정규화 변화율은 z/분이다.

현재 정규화값 value_z와 절댓값 z_abs도 보존한다. 기존 STUCK용 std_z_11은 별도로 계산한 **11개 관측의 raw 표준편차 ÷ 학습 scale**이며 3개 표준편차 std_z_3과 구분한다. 시점별 숫자 특징은 총 21개, 3개 시퀀스에서 구할 수 있는 숫자 특징은 20개다. std_z_11은 3개 배열에서 계산한 값이 아니다.

## 초기 관측·경계·정답

센서·30초 시간 공백·학습/검증/평가 경계에서 다시 시작한다. 각 구간 첫 행의 직전 변화량은 NaN, 첫 2행의 3개 특징은 NaN, 첫 10행의 11개 특징은 NaN으로 유지한다. 원본 관측과 이상값은 그대로 보존하고 NaN을 0으로 채우거나 배열을 패딩하지 않는다.

sensor_id/timestamp/zone/station_id/sensor_type/unit/split/segment_id/normalized_row는 식별 메타데이터다. ready_1step/ready_3/ready_11/ready_all도 준비 상태이며 모델 숫자 피처로 자동 넣지 않는다. feature_schema.json의 숫자 목록을 명시적으로 선택한다. 원본 value는 보관값이며 모델 입력은 스키마의 피처 목록에 따라 고른다.

정답·quality/status/alarms·원본 임계값 5개는 특징 계산 입력에 없다. 특징을 계산한 뒤 sensor_id+timestamp로 정답을 연결하여 evaluation에 따로 저장한다. 기본 목표는 끝 시점 라벨이다. contains_anomaly는 창 안 어느 시점이든 이상이 있는지를 표현하는 별도 목표이며 피처로 사용하지 않는다.

## 재사용 데이터와 기본 코드 연결

생성 명령은 `build_selected_window_features.py`이며 `experiments/window3_features_v1`에 저장한다.

- normalized_observations.csv.gz / normalization_parameters.csv: 모든 관측·정규화값과 학습 기준.
- point_features.csv.gz: 모든 시점의 21개 특징과 준비 메타데이터. 초기 NaN 유지.
- combined_features_ready.csv.gz: 21개 특징이 모두 준비된 시점만 모은 별도 파일.
- window_3/windows.npz: X는 signed z, X_value는 원래 단위의 관측. 각각 `[윈도우, 3]`, 과거→현재, float64. start_row/end_row는 normalized_observations의 0부터 시작하는 행 인덱스다.
- window_3/index.csv.gz / features.csv.gz: 배열과 대응하는 키·시각·원본 행 대응 / 20개 특징.
- evaluation/: 전체 시점·윈도우 끝 시점 정답, 14개 이벤트. 탐지 입력과 분리.
- audit/warmup_rows.csv.gz: 부족한 관측의 시점과 특징 분기·사유.
- feature_schema.json / experiment_config.json: 수식·단위·피처 목록·분할·선택 설정·입력 해시.
- summary.json / verification.json / manifest.json: 생성 수·저장 후 검증·파일 해시.

기본 `imaks_pipeline.py --detection-only`와 전체 실행도 각각의 결과 폴더에 causal_features.csv.gz, causal_features_ready.csv.gz, feature_schema.json을 내보낸다. 기존 탐지기는 z_abs·평균3 rolling_z·STUCK11로 동작하며 새 변화량/통계 특징은 후속 모델 입력으로 준비했다. 탐지 임계값·판정식은 유지한다.

```powershell
.\.venv\Scripts\python.exe verify_applied_window.py
.\.venv\Scripts\python.exe build_selected_window_features.py
.\.venv\Scripts\python.exe -m unittest test_causal_features test_applied_window test_window_sweep test_normalized_windows test_pipeline test_common_detection_data -v
```

처음에는 기본 코드의 특징 내보내기까지 실행한 뒤 재사용 데이터를 생성한다. 기존 생성 파일만 재검증하려면 `verify_window3_features.py`를 실행한다.

## 실행 결과

2026-10-05에 생성·저장 후 검증을 완료했다. 시점별 원본 211,200행을 모두 유지했고 완전한 3개 윈도우는 211,068개다. 학습 47,476개 / 검증 63,316개 / 평가 100,276개이며 초기 3개 관측 부족 시점은 132행이다. std_z_11까지 포함한 21개 숫자 특징이 모두 준비된 시점은 210,540행이고 부족한 660행도 전체 시점 파일에는 그대로 남겨 두었다.

관련 회귀 테스트 39개가 통과했다. 저장된 raw/z 배열·인덱스·20개 윈도우 특징·분리된 끝 시점 정답을 재읽어 대조했고, 기본 탐지/전체 파이프라인에서 내보낸 21개 특징과도 일치했다. 실제 211,200행 탐지 점수·경보·분할별 지표는 앞선 평균3/STUCK11 실험과 같았다. 원본·공통 입력·기존 10/11 및 길이 비교 산출물 245개 파일의 해시도 유지됐다.
