# 검증에서 선택한 평균 윈도우 3개 적용

후속으로 3개 윈도우의 변화량·변화율·통계 특징을 계산하고 기본 실행에도 특징 내보내기를 연결했다. [README_WINDOW3_FEATURES.md](README_WINDOW3_FEATURES.md)를 참조한다. 기존 탐지 판정식과 임계값은 유지한다.

2026-10-05. 검증에서 선택한 설정을 imaks_pipeline.py의 기본 센서 탐지에 연결했다. 현재 적용값은 **평균3/STUCK11, stride 1개, 관측·이동 간격 30초, 순간 임계값 6·평균 임계값 4**다. 평균3의 명목 길이는 90초, 실제 첫~끝 관측 시각 차이는 60초다. STUCK 판정은 11개 관측의 표준편차와 학습 중앙값 기반 허용 오차를 그대로 사용한다.

평균3은 이미 검증에서 고른 값이다. 이번 적용에서 임계값·윈도우를 다시 튜닝하지 않는다. window_sweep_v1의 selected_model.json·validation_selection.csv·protocol.json 해시와 선택 당시 입력의 provenance를 확인하고, 실제 계산된 윈도우와 저장할 설정이 다르면 오류를 낸다. 정규화는 학습 구간에서만 구한 median/MAD이며 정답·quality·raw 임계값을 사용하지 않는다.

## 실행 경로

```powershell
# 기본 탐지 전용: 평균3/STUCK11
.\.venv\Scripts\python.exe imaks_pipeline.py --detection-only
# 같은 설정의 룰/통계 정책 비교
.\.venv\Scripts\python.exe evaluate_threshold_policy.py
# 같은 설정의 문서·그래프 근거 연결 전체 파이프라인
.\.venv\Scripts\python.exe imaks_pipeline.py
```

탐지 전용 결과는 `experiments/common_v1_detection_window3`, 전체 결과는 `pipeline_outputs_window3`에 저장한다. 기존 평균10 결과 `experiments/common_v1_detection`, 기존 pipeline_outputs, 정규화/윈도우 데이터, 원래 window_sweep_v1, 공통 입력 common_v1을 보존한다. fit_scores에 mean_window_samples=10을 명시하면 이전 10개 평균도 재현할 수 있다. fit_scores를 직접 호출하면 기본적으로 파일을 쓰지 않고, 공식 실행 명령만 새 출력 폴더에 학습 파라미터를 저장한다.

## 결과와 검증

이전 3개 비교 결과와 실제 기본 코드의 전체 211,200행 점수·예측·분할별 지표를 대조한다. 적용한 설정의 평가 이벤트 탐지는 8/8, 이벤트 F1은 66.7%, 행 F1은 83.5%다. 실제 사건과 전혀 겹치지 않는 경보는 0개이고 같은 사건의 추가 경보 조각은 8개다. 10개보다 모든 지표가 좋아졌다고 해석하지 않는다. 평가 구간은 이전에 확인한 구간의 재평가이며 선택에 다시 사용하지 않는다.

```powershell
.\.venv\Scripts\python.exe -m unittest test_applied_window test_window_sweep test_normalized_windows test_pipeline test_common_detection_data -v
.\.venv\Scripts\python.exe verify_applied_window.py
```

verify_applied_window.py는 기본 탐지와 전체 파이프라인을 실행하고 3개 비교 결과와 일치하는지 검사한다. 명시적 10개 계산도 기존 점수·경보와 대조하고, 기존 5개 폴더의 파일 해시를 실행 전후 비교한다. application_verification.json에 결과를 기록한다. fixed_config_validation_metrics.csv는 이미 고정한 모델의 검증 지표이며 재선택 결과가 아니다.

2026-10-05 실행 결과: 관련 회귀 테스트 32개 통과. 기본 탐지와 전체 파이프라인의 211,200행 점수·예측 및 분할별 지표가 앞선 3개 실험과 일치했다. 명시적 10개 계산은 이전 비교 결과를 재현했고, 기존 5개 폴더의 총 245개 파일 해시가 실행 전후 동일했다.
