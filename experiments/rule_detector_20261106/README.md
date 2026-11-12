# 성호 — 룰 기반 탐지기 고도화 (2026-11-06)

기존 유진 v2를 보존하고, 연속 두 관측으로 이상 확정·정상 복귀를 확인하는 처리와 변화량 DRIFT 네 규칙을 구현했다. 결측은 표시하고 연속성을 추정하지 않는다. 복구 조치는 “문서가 권고하는 대응”으로 전달하며 실제 수행·원인으로 단정하지 않는다. 외부 미정의 후보에는 전문가 확인 필요를 표시한다.

## 결과

| 조건 | 정답 사건 회수 | 정답 비중첩 경보 | 중앙 지연(분) |
| --- | ---: | ---: | ---: |
| 기존 유진 v2 | 13/14 | 1 | 0.5 |
| 연속 2점판 | 13/14 | 0 | 2.0 |
| 연속 2점 + 변화량 DRIFT판 | 13/14 | 18 | 2.0 |

사건 회수는 같은 센서·시간 구간의 겹침이며 이상 유형·근본 원인 정확도가 아니다. 비중첩 경보는 제공 라벨 기준이다. 중복·분절 경보를 일대일 평가한 별도 지표도 보고서에 있다. 연속 2점은 경보를 줄이지만 지연이 늘고, DRIFT는 일부 지연을 줄이지만 비중첩 경보가 증가했다. 확장판이 전반적으로 우수하다고 주장하지 않는다.

## 읽을 자료

- [결정 사항과 구현 설명](02_구현결정과설명.md)
- [규칙 구현 정확성·정답 이벤트 평가](03_평가결과.md)
- [코드·실행 근거·입력 묶음 ZIP](01_탐지기_코드와실행근거.zip)
- [탐지 코드](code/detector.py), [준비·KG 컴파일](code/prepare.py), [3조건 실행](code/run_experiment.py), [평가](code/evaluate.py), [테스트](code/test_detector.py)
- [실제 문항별 사건 비교](evaluation/event_comparison.csv), [전체 평가 JSON](evaluation/event_metrics.json)

## 실행

바로 재현하려면 위 ZIP을 내려받아 별도 폴더에 푼 뒤 **rule_detector_1106/README.md**를 따른다. 이 Git 폴더는 코드·보고서를 쉽게 읽도록 게시한 것이며, inputs/와 runs/의 전체 복사본은 ZIP 안에 있다. 이 폴더에서 입력을 준비하지 않고 reproduce.py를 실행하면 안 된다.

ZIP 내부에서:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s code -p test_detector.py -v
python reproduce.py --output ../rule_replay_new
# 원본 annotated CSV를 가진 평가 담당자만 아래처럼 별도 평가
python reproduce.py --output ../rule_replay_eval_new --labels "원본경로/timeseries_annotated.csv"
```

새 폴더를 지정하고 기존 결과를 덮어쓰지 않는다. 탐지는 관측 일곱 필드만 읽고, 세 출력 봉인 뒤 별도 평가 프로세스가 정답을 읽는다. API·학습·모델 다운로드는 없다. 정상 복귀는 해당 규칙의 해제 의미이며 실제 설비 안전 인증이 아니다.

## 검증과 한계

의미·경계 테스트28개, 별도 이벤트 매칭 완전탐색120사례, 새 폴더 재실행의 탐지·평가 바이트 동일성을 확인했다. 원문·기존 v1 조건30개와 KG 경고·위험 조건44개를 대조했다. 독립 전문가 검수는 없다.

MAINT-02의30+분은 고정30분 변화량으로 구체화한 운영 해석이다. SOP-002의 σ 기반 기울기 정의를 구현한 것은 아니다. 작업자 명령·상관 패턴·미지원 규칙은 rules_improved.json에 남겼다. GraphRAG/Agent/UI는 이 실행에서 변경하지 않았다. 원본·이전 결과·다른 브랜치는 수정하지 않았다.

실험 기준: 유진 5th-yujin 커밋2b19fc6a05be86485282266925b94b96ae0dd230 및 고정 KG2,806triple. 입력·코드·출력 해시와 평가 접근 기록을 포함했다.
