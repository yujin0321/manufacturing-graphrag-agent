# 슬라이딩 윈도우 길이 비교

2026-10-05 후속 적용: **평균3/STUCK11을 기본 탐지 코드에 연결했다.** [README_APPLIED_WINDOW.md](README_APPLIED_WINDOW.md)를 참조한다. 아래 비교는 2026-10-03 실험 기록이며 평균10의 기존 결과는 보존했다.

2026-10-03. 평균 윈도우 3·5·10·15·20·30·60·120개를 실제 공통 입력 211,200행으로 비교했다. 관측 간격 30초, stride 1개, 학습 구간 median/MAD, 순간 임계값 6·평균 임계값 4, STUCK 표준편차 11개는 동일하게 유지했다.

**검증 기준 선택은 평균 3개다.** 3·5·10·15개의 검증 이벤트 F1은 모두 100%였으며, 동률을 구분하는 검증 행 F1은 3개가 94.1%로 가장 높았다. 모든 후보를 같은 전체 행으로 평가했고, 준비되지 않은 평균 분기만 비활성으로 두었다. 정답 라벨·raw 임계값으로 정규화하거나 점수를 계산하지 않았다.

**기존 평가 구간에서 이벤트 F1이 가장 높았던 길이는 10개다.** 3개는 행 F1 83.5%·이벤트 F1 66.7%, 10개는 행 F1 81.0%·이벤트 F1 84.2%였다. 두 설정 모두 8개 사건을 탐지했지만, 3개에서는 두 DRIFT 사건의 경보가 더 자주 끊겼다. 평가값으로 검증 선택을 다시 바꾸지 않았다. 10/3 실험 산출물을 모두 보존하며 검증 선택 3개를 현재 기본 코드에 적용했다. 모든 목적에 최적인 길이라고 단정할 수는 없다.

[전체 결과·해석](experiments/window_sweep_v1/report_ko.md), [수치 비교](experiments/window_sweep_v1/comparison.csv), [검증 선택 기록](experiments/window_sweep_v1/selected_model.json), [비교 그림](experiments/window_sweep_v1/window_comparison.png)을 참조한다. 명목 길이 W×30초와 실제 첫~끝 관측 시간차 (W−1)×30초를 구분해서 기록했다. 3개 평균의 명목 길이는 90초, 실제 관측 시간차는 60초다.

```powershell
.\.venv\Scripts\python.exe sweep_window_sizes.py
.\.venv\Scripts\python.exe -m unittest test_window_sweep test_normalized_windows test_pipeline test_common_detection_data -v
```

결과는 `experiments/window_sweep_v1`에 저장한다. 선택 기록을 저장한 뒤 평가 지표를 계산한다. 평가 구간은 이전에 확인했던 구간의 재평가로, 새 맹검 시험은 아니다. 원본·공통 입력·기존 10/11 윈도우·기존 탐지 결과는 보존했다. 기존 평균10 결과와 점수·경보·지표가 일치하고 저장한 선택 특징의 관측값·점수·행 키를 재검증했다.
