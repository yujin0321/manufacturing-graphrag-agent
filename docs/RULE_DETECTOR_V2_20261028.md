# 룰 탐지기 v2 — KG에서 조건을 읽어 실행 + 이벤트 단위 평가

2026-10-28. v1(`detection/rules.py`)과 그 결과는 그대로 두고 `detection/kg_rules.py`를 추가했다.

## 바뀐 점

1. **조건을 KG에서 컴파일한다.** 규칙 노드의 `conditionText` + `appliesToSensor`를 작은 결정적 문법으로 해석한다. RULE-ST02-03의 명목값은 센서 노드가 아니라 같은 센서를 가리키는 SOP-002 ThresholdRule에서 가져온다(운영 규칙 → 센서 ← 임계값 규칙 조인).
2. **v1 표를 정답 대조용 테스트로 쓴다.** 사람이 검토한 30개 실행 조건과 KG 컴파일 결과가 하나라도 다르면 테스트가 실패한다. 개발 중 이 테스트가 문법 버그 2개를 잡았다(`for >15 min`의 15를 임계값으로 읽음, 명목값 위치).
3. **SOP-002 경고/위험 구간도 KG(ThresholdRule)에서 실행**하고 센서 메타데이터 CSV와 대조한다(차이 0건).
4. **train/validation/test 경계에서 지속 상태를 초기화하지 않는다.** 학습이 없으므로 구간은 보고용 표시일 뿐이다. 이 데이터에서는 결과가 바뀌지 않았다(문서 규칙 탐지 구간 43건이 v1과 동일).

미지원(추측하지 않음): RULE-ST04-03(작업자 명령 관측 불가), RULE-ST02-04(모니터링 지시), MAINT-01/02/06/08(DRIFT 기울기 미정의), SOP-003 상관 패턴 3개.

## 이벤트 단위 평가 (`scripts/evaluate_detector_events.py`)

정답 이벤트는 `row_labels.csv`에서 센서별로 연속된 비정상 라벨 구간이며 14건이다(데이터셋 이상 이벤트 수와 일치). 탐지 결과의 해시를 확인한 뒤에만 라벨을 읽는다.

| 규칙 계열 | 잡은 이벤트 | 오경보 | 중앙 지연 | 유형별 |
|---|---:|---:|---:|---|
| 문서 규칙(KG 컴파일) | 12/14 | 0 | 0.5분 | SPIKE 3/3, OUT_OF_RANGE 4/4, STUCK 1/1, DRIFT 4/5, CORRELATED 0/1 |
| SOP-002 경고 구간 | 12/14 | 1 | 0.5분 | DRIFT 5/5, STUCK 0/1 |
| SOP-002 위험 구간 | 4/14 | 0 | 0분 | SPIKE 3/3 |
| 전체 | 13/14 | 1 | 0.5분 | CORRELATED 0/1만 미탐 |

읽는 법:
- **놓친 1건은 GT-0009**(ST04 속도 저하, ST02 전류 드리프트가 원인인 상관 이상)이다. 이를 잡는 규칙(RULE-ST04-03)은 작업자 명령 정보가 없어 실행할 수 없다. 이 이벤트가 바로 ⑥(시계열 기반 `causallyAffects` 발굴)이 필요한 이유다.
- **DRIFT는 잡히지만 늦다**: 29분(ST01 압력), 40분(ST04 진동), 74.5분(연구실 습도), 108분(창고 온도). 임계값을 넘을 때까지 기다리기 때문이다. SOP-002의 DRIFT 기준(기울기 > 0.1σ/분, 5회 이상)을 팀이 운영 정의로 합의하면 MAINT-01/02/06/08을 실행할 수 있고 지연이 줄어들 것이다.
- 오경보 1건은 ST02 전류가 13.5668 A로 한 표본만 WARN_HI(13.5)를 넘은 경우다.
- 이 결과는 이미 공개된 데이터를 재현한 것이며 미노출 평가가 아니다. 규칙 기반이라 학습·튜닝은 없다.

## 실행

```powershell
$env:PYTHONPATH='src'
..\.venv\Scripts\python.exe -m unittest tests.test_detector_kg -v
..\.venv\Scripts\python.exe -m imaks_kg.detection.kg_rules --out kg_build\rule_detector_v2
..\.venv\Scripts\python.exe scripts\evaluate_detector_events.py --run kg_build\rule_detector_v2
# v1 결과도 같은 방식으로 평가 가능
..\.venv\Scripts\python.exe scripts\evaluate_detector_events.py --run kg_build\rule_detector_20261026
```
