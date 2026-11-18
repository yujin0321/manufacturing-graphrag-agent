# iMAKS 구체적 결함 7건과 처리 정책

후속 적용 상태: `preprocessed/common_v1`에 처리 결과를 별도로 생성했다. [COMMON_PREPROCESSING_REPORT.md](COMMON_PREPROCESSING_REPORT.md)를 참조한다. 아래 내용의 '수정 적용 전'은 최초 감사 단계의 기록이다. 원본과 이전 산출물을 덮어쓰지 않았다.

2026-10-03 기준, 현재 프로젝트의 `iMAKS_dataset.zip`을 대조했다. 이 단계에서는 결함과 정책을 명시한다. 원본·정답 및 기존 전처리 산출물을 수정한 단계가 아니다. 자동 수정 완료와 혼동하지 않는다.

## B01. ground_truth.csv SPD 규칙 3행

SOP-002 p.1 및 raw 센서 설정과 비교한 수치 오류는 3행·5셀이다.

| ruleId | 필드 | 원본 | 근거 확인값 |
|---|---|---:|---:|
| RULE-ST04-03 | critLo | 1.25 | 0.85 |
| RULE-THR-ST03-SPD-CRIT | critLo | 1.05 | 0.65 |
| RULE-THR-ST03-SPD-CRIT | warnLo | 1.15 | 0.75 |
| RULE-THR-ST03-SPD-CRIT | warnHi | 1.35 | 0.95 |
| RULE-THR-ST04-SPD-CRIT | critLo | 1.25 | 0.85 |

처리 정책: 원본 ground_truth를 보존하고, 수정본을 만들 때 위 변경과 근거를 기록한다. 추출 평가에서는 원본 기준과 문서에 맞춘 수정 기준을 구분해 보고한다. 수정 제안은 `preprocessed/audit/spd_threshold_proposed_corrections.csv`에 저장한다. 다른 필드까지 검증이 완료된 것은 아니다.

## B02. shift·day 라벨과 timestamp 불일치

raw와 annotated의 `day`는 1~5이지만 실제 timestamp는 2026-01-06 06:00:00부터 2026-01-09 13:59:30까지다. `day=2, shift=Morning`인데 1/6 22시인 구간도 있다. 따라서 기존 day를 달력 날짜, shift를 실제 시간대라고 그대로 믿지 않는다. batch_id도 이 라벨에 연동되어 있으므로 검토 없이 시간 피처로 사용하지 않는다.

처리 정책: 정렬·분할·조인은 timestamp를 기준으로 수행한다. 필요하면 원본 day/shift/batch_id를 별도 보존하고 calendar_date/day_index/clock_shift를 파생한다. clock_shift를 만들 경우 Morning=[06:00,14:00), Afternoon=[14:00,22:00), 나머지 OFF_SHIFT라는 팀 정책을 명시한다. 야간 데이터를 삭제하거나 timestamp를 라벨에 맞춰 바꾸지 않는다. 생성 코드 확인 전에는 의도된 생산일 정의를 단정하지 않는다.

## B03. nodes_factory.csv 폐기 — 적재 대상 제외

24행의 nodes_factory와 115행의 nodes는 같은 ID에 다른 센서 이름을 배정한 충돌이 6건 있다. 예: N0018은 factory에서 ST03_LABELLING_TMP, nodes에서 ST03_LABELLING_SPD다. N0019/N0020/N0022/N0023/N0024도 충돌한다.

처리 정책: nodes.csv를 정식 노드 원본으로 사용하고 nodes_factory.csv를 KG 적재·조인에서 제외한다. 두 파일을 병합하지 않는다. 여기서 폐기는 사용 중단을 뜻하며, 감사용 원본 ZIP 내부 파일은 삭제하지 않는다.

## B04. monitors 양방향 중복

monitors 44행은 22개 센서–스테이션 쌍이 양방향으로 존재하는 구조다. 방향이 다르므로 단순 drop_duplicates로 해결되지 않는다.

처리 정책: Sensor → monitors → Station 한 방향으로 정규화한다. 역관계를 쓰면 Station → has_sensor → Sensor로 의미를 구분한다. 기존 pipeline의 has_sensor 방향도 허용한다. 같은 연결을 독립 사실 두 건으로 집계하지 않으며, 원본 양방향 엣지의 대응 정보를 보존한다. 나머지 관계까지 제거하지 않는다.

## B05. access_events 범위 이탈·UNKNOWN 2건

448건 중 센서 관측 기간 밖의 기록은 156건이며, 모두 센서 종료 이후다. access 로그는 1/11 04:09까지 존재한다. 이는 센서와의 공동 평가 범위를 벗어난 것이며 access 기록 자체의 무효를 뜻하지 않는다.

- AE-00443: 1/8 01:45, UNKNOWN visitor, General Warehouse, authorized=NO, 센서 기간 안.
- AE-00447: 1/9 22:20, UNKNOWN visitor, Production Area, authorized=NO, 센서 기간 밖.

처리 정책: 원본을 보존하며 센서 결합 실험에서는 범위 밖 기록을 별도 분리한다. UNKNOWN을 임의의 등록 작업자로 매핑하지 않는다. 미상 방문자 사건마다 event_id로 식별하며, 모든 UNKNOWN을 동일 인물로 합치지 않는다. authorized도 실제 역할 규칙과 별도로 검증한다.

## B06. alarm_response_log 허위 SOP 참조

AR-0005(GT-0005)와 AR-0012(GT-0012)는 `Production halted per SOP-001 §5. Supervisor alerted.`라고 기록되어 있다. 제공 SOP-001은 2페이지이며 1절과 2절(2.9까지)만 있어 §5를 확인할 수 없다.

처리 정책: action_taken은 사후 기록 원문으로 보존하되 reference_valid=false로 표시할 대상으로 지정한다. SOP에서 확인된 권장 조치와 구분하고, SOP 근거 정답으로 사용하지 않는다. 없는 참조를 추정한 참조로 바꾸지 않는다. `per SOP-003`처럼 문서만 지칭한 다른 기록까지 모두 허위라고 판정한 것은 아니다.

## B07. GT-0007 severity

GT-0007은 ST01_FILLING_FLW의 1/8 06:30~06:32 SPIKE다. nodes·annotated·대응 로그의 severity는 WARNING으로 일치한다. 그러나 annotated 5행 중 3행의 값(91.7036, 91.4678, 101.4783 L/min)이 CRIT_LO=105보다 낮다. 즉 파일 간 라벨 불일치가 아니라 제공 임계값으로 계산한 심각도와의 충돌이다.

처리 정책: dataset_severity=WARNING을 보존하고 관측값에서 계산한 rule_severity를 별도 필드로 관리한다. 이벤트에 한 번이라도 CRITICAL 초과가 있으면 이벤트 최대 rule_severity=CRITICAL로 집계하는 등의 규칙도 명시한다. 이번 단계에서 정답을 CRITICAL로 일괄 재라벨링하지 않는다. 심각도 평가 시 원본 라벨과 규칙 판정을 구분해 보고한다.

## 재현·증거

```powershell
.\.venv\Scripts\python.exe audit_known_defects.py
```

`preprocessed/audit/known_defects_report.json`에 각 결함의 수치·행·처리 정책과 원본 파일 SHA-256을 기록한다. 수정본 제작과 적용은 이후 별도 단계이며, 이미 생성한 탐지용 CSV의 day/shift 등은 아직 그대로다.
