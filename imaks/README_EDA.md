# iMAKS EDA 시작하기

후속 구현은 `notebooks/02_graph_detection_retrieval.ipynb`와 `README_PIPELINE.md`에 있습니다. 설비 그래프·SOP 근거·시간순 탐지 평가·검색 비교까지 포함합니다.

VS Code에서 `imaks-eda.code-workspace`를 열고 `notebooks/01_imaks_eda.ipynb`를 엽니다.
노트북에는 실행 결과와 그래프가 저장됩니다. 다시 실행할 때 오른쪽 위 **커널 선택 → Python 환경 → .venv**를 선택하세요.
인터프리터 파일은 이 프로젝트의 `.venv/Scripts/python.exe`입니다.

## 읽는 순서

1. 노트북 1–2: 파일 지도와 컬럼·결측값
2. 노트북 3–5: 센서별 통계, 시간 간격, 이상 분포, ST02 온도 사례
3. 노트북 6–7: 그래프 연결과 대응 이력

`eda_outputs`에는 CSV 통계표, PNG 그래프, `summary.json`이 저장됩니다.
원본 ZIP은 변경하거나 전체 압축 해제하지 않습니다.

## 터미널에서 전체 재생성

```powershell
.\.venv\Scripts\python.exe build_eda.py
```

처음 준비한 가상환경은 이 컴퓨터의 번들 Python 및 pandas/numpy를 참조합니다. 다른 컴퓨터에서는 Python 3.12 이상으로 가상환경을 만든 뒤 `pip install -r requirements-eda.txt`를 실행하세요.

## 해석 주의

- 이상 행 비율과 이상 사건 수는 다릅니다.
- `ground_truth.csv`는 규칙 표입니다.
- 라벨, 경보 결과, 미래 대응 이력을 탐지 입력으로 사용하지 마세요.
- 결측 severity는 정상 행에서 의도된 빈 값일 수 있습니다.
- PDF 본문, MQTT 구조, CSI 신호 분석은 다음 단계입니다.
- 제공된 그래프 관계는 인과관계의 증거로 간주하지 않습니다.
