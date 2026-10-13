# 센서 정규화·슬라이딩 윈도우 데이터

현재 적용한 평균3/STUCK11의 변화량·변화율·통계 특징과 재사용 배열은 [README_WINDOW3_FEATURES.md](README_WINDOW3_FEATURES.md)에 기록했다. 이 문서의 10/11 산출물은 최초 비교용으로 보존한다.

후속으로 평균 윈도우 3·5·10·15·20·30·60·120개를 실제 탐지기로 비교했다. 검증 기준은 3개를 선택했지만 기존 평가의 사건 단위 F1은 10개가 가장 높았다. [README_WINDOW_SWEEP.md](README_WINDOW_SWEEP.md)에 결과와 지표별 차이를 기록했다. 이 문서의 최초 10/11 산출물은 보존한다.

2026-10-03. `preprocessed/common_v1`의 ML 입력으로 별도 실험 데이터 `experiments/robust_windows_v1`을 생성했다. 기존 데이터와 탐지 결과는 보존했다. 이번 단계는 정규화·윈도우·특징 데이터 준비이며 새 ML 모델을 학습한 단계는 아니다.

## 정규화

센서별로 학습 구간(2026-01-07 이전)의 median과 MAD를 구한다.

```text
MAD = median(abs(value - median))
scale = max(1.4826 × MAD, 1e-8)
value_z = (value - median) / scale
```

학습 구간의 이상도 그대로 포함한다. 정답 라벨로 정상행을 선별하지 않고, 검증·평가 구간에서는 학습 때 저장한 기준만 적용한다. 부호를 보존하므로 상승·하락 방향이 남는다. 클리핑·평활화·보간·리샘플링은 하지 않았다. 현재 22개 센서에 scale 하한을 적용한 경우는 0개다.

`normalization_parameters.csv`에 센서별 median/MAD/scale, 학습 행 수·시작·종료, 하한 사용 여부를 기록했다. `normalized_observations.csv.gz`는 원본 관측값과 정규화값 211,200행을 모두 보존한다. sensor_id/timestamp/split/segment_id 등은 식별용이며 피처로 자동 사용하지 않는다.

## 윈도우 설정 — 반드시 실험과 함께 기록

| 설정 | 10개 윈도우 | 11개 윈도우 |
|---|---:|---:|
| 관측 수 | 10 | 11 |
| 관측 간격 | 30초 | 30초 |
| 명목 구간 길이(관측 수×30초) | 300초 | 330초 |
| 실제 첫 관측~마지막 관측 시간차 | 270초 | 300초 |
| 이동 간격(stride) | 1개 / 30초 | 1개 / 30초 |
| 완전한 윈도우 | 210,606 | 210,540 |
| 초기 관측 부족 행 | 594 | 660 |
| 학습 윈도우 | 47,322 | 47,300 |
| 검증 윈도우 | 63,162 | 63,140 |
| 평가 윈도우 | 100,122 | 100,100 |

각 윈도우는 한 센서의 현재와 과거 관측만 포함한다. 센서·30초 시간 공백·학습/검증/평가 경계를 넘지 않는다. 22개 센서×3개 분할로 현재 연속 구간은 66개다. 구간 시작에서 부족한 관측은 0으로 채우지 않는다. 원본·정규화 관측은 유지하고 배열에는 완전한 윈도우만 넣는다. 제외 사유는 `audit/warmup_rows.csv.gz`에 기록했다.

10/11은 기존 통계 탐지기를 재현하기 위한 첫 실험 설정이다. 모든 팀원이 같은 윈도우를 사용해야 한다는 뜻은 아니다. 다른 길이·stride는 별도 실험 버전으로 생성하고 검증 구간에서 선택한다. 평가 결과로 길이를 다시 튜닝하지 않는다.

## 생성 파일

| 파일 | 내용 |
|---|---|
| normalized_observations.csv.gz | 원본 값·단위·부호 있는 정규화값·구간 식별, 211,200행 |
| normalization_parameters.csv | 학습 구간에서 구한 센서별 변환 기준 |
| window_10/windows.npz | X 형태 `(210606, 10)`의 정규화 시퀀스 |
| window_11/windows.npz | X 형태 `(210540, 11)`의 정규화 시퀀스 |
| 각 window 폴더의 index.csv.gz | 윈도우 ID·센서·끝 시각·시작 시각·분할·관측 행 대응 |
| 각 window 폴더의 features.csv.gz | 윈도우별 숫자 특징과 식별 키 |
| point_features.csv.gz | 기존 탐지기와 대응되는 211,200행의 특징·준비 상태 |
| combined_features_ready.csv.gz | 평균10·표준편차11이 모두 준비된 210,540행 |
| evaluation/ | 윈도우·시점의 평가 정답, 모델 입력과 분리 |
| experiment_config.json | 정규화·피처·윈도우·stride·입력 해시·정답 정책 |
| summary.json / verification.json | 생성 수·저장 후 재읽기 검증 |

NPZ의 X는 float64, `[윈도우, 관측 수]` 순서다. 각 행은 과거→현재이며 라벨·ID·임계값을 포함하지 않는다. start_row/end_row는 정렬된 normalized_observations의 0부터 시작하는 행 인덱스다. 원본 CSV의 행 번호가 아니다. NPZ와 index/features/evaluation의 행은 같은 window_id에 대응한다.

## 모델에 사용할 숫자 특징

윈도우별 features의 피처 목록은 다음과 같다.

- z_current: 마지막 관측 정규화값.
- z_mean / z_std: 윈도우의 정규화 평균·모집단 표준편차(ddof=0).
- z_min / z_max: 윈도우 최소·최대 정규화값.
- z_change: 마지막−첫 번째 정규화값.
- z_rate_per_min: z_change를 실제 첫~끝 관측의 분 단위 시간차로 나눈 값. 선형회귀 기울기는 아니다.

point/combined의 피처 목록은 `value_z, z_abs, mean_z_10, mean_abs_z_10, std_z_11`이다. `mean_abs_z_10`은 **평균 정규화값의 절댓값**이며 정규화 절댓값들의 평균이 아니다. 초기 mean/std는 NaN으로 남기고 ready_10/ready_11/ready_both로 준비 여부를 표시했다. NaN을 0으로 채우지 않는다.

센서·시각·분할·ready·segment·normalized_row·window_id는 메타데이터다. 학습할 때 feature_columns 목록만 명시적으로 선택한다. quality/status/alarms, raw 임계값 5개, 정답, 원본 day/shift/batch_id는 피처에 없다.

## 정답 연결

정규화와 특징 계산에는 라벨을 사용하지 않았다. 평가용 정답은 생성 후 sensor_id+timestamp로 연결하여 `evaluation`에 별도로 저장했다.

`end_anomaly_label`은 윈도우 끝 시점의 정답이며 현재 시점 탐지의 기본 목표다. `contains_anomaly`는 윈도우 내 어느 시점이라도 이상이 있는지를 나타내는 별도 목표다. 둘을 같은 평가로 혼용하지 않으며 모델 피처로 사용하지 않는다. 정상 행의 빈 severity는 0으로 바꾸지 않는다.

## 실행·검증

```powershell
.\.venv\Scripts\python.exe build_normalized_windows.py
.\.venv\Scripts\python.exe -m unittest test_normalized_windows -v
```

생성 스크립트에서 저장 후 재읽기 검증도 수행한다. 이미 만든 파일만 다시 확인하려면 `verify_normalized_windows.py`를 실행한다.

7개 회귀 검증이 통과했다. 미래/평가 값 변경이 학습 파라미터나 이전 윈도우를 바꾸지 않는지, 센서·시간 공백·분할 경계 초기화, 짧은 구간의 패딩 금지, signed z 역변환, 임계값·라벨 거부를 확인했다. 실제 파일의 관측값 보존·CSV/NPZ/특징 대응·끝 시점 정답 연결도 검증했다. 생성된 파일 해시는 manifest.json에 기록했다.
