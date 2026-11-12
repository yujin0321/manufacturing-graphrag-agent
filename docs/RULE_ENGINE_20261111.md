# 룰 탐지 엔진: 구조 분리 → KG 오버레이 → Agent 도구 → 정답 비의존 평가 → v3.2

2026-11-11, `6th-yujin`. v1·v2·v3·v3.1 탐지기 코드와 산출물은 그대로 두고 엔진을 새로 추가했다. 이번 작업 전체에서 데이터셋 라벨(`evaluation/row_labels.csv` 등), 공개 평가 결과 파일, `scripts/evaluate_detector_events.py` 실행을 쓰지 않았다. 유료 API 호출도 없다(설명 경로는 모의 응답으로만 시험).

## 1. 흐름

```
센서 입력 ─┐
           ├─ compiler (KG → 규칙 IR) ─ executor (표본+IR → 알람) ─ postprocess (사건·유형·심각도·감시·상관)
KG ────────┘                                                        │
                                       sealed run (events/incidents/correlations/…, complete.json)
                                                                    │
                                       overlay (⑦: AnomalyEvent·Provenance·상관 후보 TTL, SHACL 검증 후 적재)
                                                                    │
                                       incident_tools (Agent 도구) · event_explain.answer_incident · demo /api/incidents
```

| 모듈 | 역할 |
|---|---|
| `detection/engine/compiler.py` | KG만 읽는다. 규칙마다 KG 노드, 실행 ID와 KG 규칙 ID, 원문, 해석, 파라미터 출처(`kg:conditionText`, `kg:ThresholdRule.*`, `config.*`, `calibration:*`), 원문 등급 표기(`severity_tag`)를 남긴다. |
| `executor.py` | IR과 표본만 쓴다(KG 접근 없음, 테스트로 확인). |
| `postprocess.py` | 묶기·보조 신호·유형·심각도·감시·상관을 함수로 분리. |
| `config.py`, `configs/*.json` | 해석 선택: `slope_mode`, `maint_direction`, `monitor_gate`, `monitor_anchor`, `link_policy`, `severity_policy`, 팀이 정한 값. |
| `overlay.py` | 봉인된 실행 → KG 오버레이(⑦), 검증 실패 시 적재 거부. |
| `rag/incident_tools.py` | `list_incidents`, `get_incident_evidence`, `get_correlated_incidents`. 기존 계약 한도(도구 3회, 근거 4,000토큰)와 선택 규칙 재사용. |
| `benchmark.py` | 라벨 없는 지표 + SOP-002 합성 주입 벤치마크. |

## 2. 설정

| 설정 | slope | MAINT | 감시 | 감시 시작 | 상관 연결 | 심각도 |
|---|---|---|---|---|---|---|
| `v3` | signal | abs | 없음 | - | legacy | SOP-002 대역 |
| `v3_literal` | alarm | abs | 없음 | - | legacy | SOP-002 대역 |
| `v3_1` | signal | away | warning_any | 사건 시작 | legacy | SOP-002 대역 |
| `v3_2` | signal | away | warning_any | **WARNING 알람 시각** | **verified** | **원문 등급 반영** |

v3.2는 라벨 없이 SOP 원문만 근거로 설계했다(v3·v3.1 공개 결과를 이미 본 뒤라 사후 설계임은 밝힌다).
- RULE-ST02-04 "whenever ST02 CUR triggers a WARNING": 감시 창을 원인 사건의 첫 경고 알람 시각에 맞추고 원인 알람 ID를 기록한다.
- 상관 연결(`verified`): 원인 경고 존재, 경고 뒤 90분 창, 결과 방향(속도 저하), 감시로 승격된 결과는 감시를 연 원인과 같아야 한다.
- 심각도(`with_document_tags`): 원문에 `(CRITICAL)`/`(WARNING)`이 적힌 문서 규칙이 일치하면 등급을 올린다(내리지 않음).

## 3. 결과

### 3.1 동등성 (구조 분리)
v3·v3-literal·v3.1의 `events`·`incidents`·`correlations`·`signals`(+`monitor_windows`) 13개 파일이 기존 모듈 출력과 바이트 일치. v3.2 옵션을 넣은 뒤에도 다시 확인했다(`tests/test_detector_engine.py`).

### 3.2 KG 오버레이 (v3.1)
사건 17개 → AnomalyEvent 17개(하위 유형 1개씩), timeseries Provenance 17개, 상관 후보 2개. SHACL S1~S8(기존 KG+오버레이, `inference="none"`)에서 오버레이가 새로 만든 위반 0개, 적재 검사 오류 0개, guards L4 0개.
- **CausalLink/`causallyAffects`는 만들지 않았다.** S5가 `likelihoodScore`를 요구하는데 SOP 규칙 일치 후보의 점수 정의가 없다. 임의로 만들지 않고 `det:CorrelationCandidate`로 둔다(미결).
- `guards/leakage_shapes.ttl`은 머리말대로 ⑥ 입력 그래프 전용이다(L1~L3은 AnomalyEvent·triggers·startTime을 금지). ⑦ 오버레이에는 L4(GT id)와 적재 검사(데이터셋 라벨 필드 금지, 규칙 참조·windowId 확인)를 적용했다.

### 3.3 정답 비의존 평가
상세: `reports/rule_detector_engine_benchmark_20261111_verify.md`.

- 원본 입력 라벨 없는 지표: v3.1과 v3.2는 알람 120·사건 17·감시 창 3·연결 2로 같다. 이 데이터에서는 경고가 원인 사건의 첫 알람이었고, 원문 CRITICAL 문서 규칙이 늘 SOP-002 위험 대역과 함께 울렸기 때문이다.
- 합성 벤치마크(시드 3개, 51건 + 미끼 3건): v3.1·v3.2 모두 51/51 탐지, 유형 46/51, 상관 연결 6/6. **기준 시각 미끼 오연결은 v3.1 3/3 → v3.2 1/3**, 주입 부작용 사건 1 → 0. 남은 1건은 결과 쪽 기울기 신호가 경고 뒤에 늦게 켜져 사건 시작이 경고 뒤로 잡힌 경우다.
- 합성 데이터에서 **OUT_OF_RANGE 계단 변화 9건 중 5건이 DRIFT로 분류**됐다. 정답 라벨 없이 드러난 유형 분류 약점이다. 이번에는 고치지 않았다(아래 4절).

벤치마크 구성 수정 2건(첫 실행 뒤, 탐지기 값은 바꾸지 않음): OUT_OF_RANGE 주입이 평평한 선이라 STUCK 정의에도 맞아서 센서 잡음을 유지하도록 고쳤다. 감시 시작 기준을 구분하는 시나리오가 없어 미끼 시나리오를 추가했다.

## 4. 미결·다음 후보

1. `likelihoodScore` 정의(규칙 일치 후보와 ⑥ 시계열 상관을 같은 척도로 둘지) → 그 뒤 CausalLink 적재.
2. 유형 분류: SOP-002 DRIFT 정의 "Monotonic deviation >15 min"을 판정에 반영(합성 OUT_OF_RANGE→DRIFT 5/9 근거). 새 판정 기준이 필요하므로 설계를 먼저 고정하고 합성 벤치마크와 분리된 시드로 평가한다.
3. 상관 연결에서 결과 사건의 `onset_estimate`와 경고 시각 비교(미끼 남은 1건).
4. v3.2 공개 정답 평가는 합성 평가·봉인 뒤 1회만(사용자 결정 후).
5. 실시간(as-of) 처리, ⑥ 시계열 상관 후보와의 결합.

## 5. 실행

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_detector_engine tests.test_detector_engine_stages tests.test_detector_v3 tests.test_detector_v3_1 tests.test_detector_kg tests.test_detector_rules
python scripts/compare_detector_engine.py --work kg_build/engine_equivalence_20261111
python -m imaks_kg.detection.engine.run --config v3_1 --out kg_build/rule_engine_v3_1 --quality-md reports/rule_detector_engine_kg_quality_20261111_verify.md
python -m imaks_kg.detection.engine.overlay --run kg_build/rule_engine_v3_1 --out kg_build/rule_engine_v3_1_overlay
python -m imaks_kg.detection.engine.run --config v3_2 --out kg_build/rule_engine_v3_2
python -m imaks_kg.detection.engine.benchmark --configs v3 v3_literal v3_1 v3_2 --out kg_build/engine_benchmark_20261111 --report-md reports/rule_detector_engine_benchmark_20261111_verify.md
```

Agent 도구와 데모의 기본 경로는 `kg_build/rule_engine_v3_1`과 `kg_build/rule_engine_v3_1_overlay`다. 데모: `GET /api/incidents`, `POST /api/explain-incident {"incident_id": ...}` (v1 `/api/detections`, `/api/explain-event`는 그대로). 화면(`demo.html`)은 아직 바꾸지 않았다.
