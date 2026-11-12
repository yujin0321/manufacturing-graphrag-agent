# 룰 탐지 엔진 정답 비의존 평가 (2026-11-11)

데이터셋 라벨과 공개된 평가 결과는 읽지 않았다. 아래 두 지표만 쓴다.

## 1. 라벨 없는 지표 (원본 입력)

| 지표 | v3 | v3_1 | v3_2 | v3_literal |
|---|---|---|---|---|
| alarms | 124 | 120 | 120 | 3105 |
| alarms_per_sensor_day | 1.691 | 1.636 | 1.636 | 42.341 |
| incidents | 17 | 17 | 17 | 1775 |
| incidents_per_day | 5.1 | 5.1 | 5.1 | 532.5 |
| slope_signals | 2981 | 2979 | 2979 | 0 |
| monitor_windows | 0 | 3 | 3 | 0 |
| correlation_links | 0 | 2 | 2 | 15 |
| sensors_with_incidents | 12 | 13 | 13 | 22 |
| incidents_by_type | {"DRIFT": 10, "OUT_OF_RANGE": 3, "SPIKE": 3, "STUCK": 1} | {"CORRELATED": 2, "DRIFT": 8, "OUT_OF_RANGE": 3, "SPIKE": 3, "STUCK": 1} | {"CORRELATED": 2, "DRIFT": 8, "OUT_OF_RANGE": 3, "SPIKE": 3, "STUCK": 1} | {"CORRELATED": 15, "DRIFT": 1753, "OUT_OF_RANGE": 3, "SPIKE": 3, "STUCK": 1} |
| incidents_by_severity | {"ADVISORY": 3, "CRITICAL": 4, "WARNING": 10} | {"ADVISORY": 3, "CRITICAL": 4, "WARNING": 10} | {"ADVISORY": 3, "CRITICAL": 4, "WARNING": 10} | {"ADVISORY": 1761, "CRITICAL": 4, "WARNING": 10} |

## 2. 합성 주입 벤치마크

시드 [0, 1, 2], 단일 센서 유형마다 시드당 3건, 상관 2건(시차 20분 미세 저하, 60분 경고 이탈), 기준 시각 미끼 1건(원인 사건이 MAINT-02로 먼저 시작하고 WARNING은 20분 뒤, 결과 저하는 WARNING 10분 전 시작: 연결되면 오연결). 호스트 구간: 4시간 동안 WARN 대역 안, ±60분 안에 v2 알람 없음(설정과 무관). 판정: 주입 구간(끝 +10분)과 겹치는 같은 센서 사건. σ는 원본 입력으로 고정.

| 유형 | 지표 | v3 | v3_1 | v3_2 | v3_literal |
|---|---|---|---|---|---|
| ALL | detected | 48/51 | 51/51 | 51/51 | 51/51 |
| ALL | type_correct | 43/51 | 46/51 | 46/51 | 46/51 |
| ALL | median_latency_min | 4.5 | 4.5 | 4.5 | 0.0 |
| CORRELATED | detected | 3/6 | 6/6 | 6/6 | 6/6 |
| CORRELATED | type_correct | 3/6 | 6/6 | 6/6 | 6/6 |
| CORRELATED | median_latency_min | 23.5 | 9.5 | 9.5 | 7.8 |
| CORRELATED | link_correct | 3/6 | 6/6 | 6/6 | 3/6 |
| DECOY_NO_LINK | detected | 0/3 | 3/3 | 1/3 | 3/3 |
| DECOY_NO_LINK | type_correct | 0/3 | 0/3 | 0/3 | 0/3 |
| DECOY_NO_LINK | median_latency_min | - | 7.5 | 14.5 | 7.5 |
| DECOY_NO_LINK | false_link | 0/3 | 3/3 | 1/3 | 3/3 |
| DRIFT | detected | 18/18 | 18/18 | 18/18 | 18/18 |
| DRIFT | type_correct | 18/18 | 18/18 | 18/18 | 18/18 |
| DRIFT | median_latency_min | 25.5 | 25.5 | 25.5 | 3.5 |
| OUT_OF_RANGE | detected | 9/9 | 9/9 | 9/9 | 9/9 |
| OUT_OF_RANGE | type_correct | 4/9 | 4/9 | 4/9 | 4/9 |
| OUT_OF_RANGE | median_latency_min | 0.0 | 0.0 | 0.0 | -0.5 |
| SPIKE | detected | 9/9 | 9/9 | 9/9 | 9/9 |
| SPIKE | type_correct | 9/9 | 9/9 | 9/9 | 9/9 |
| SPIKE | median_latency_min | 0.0 | 0.0 | 0.0 | 0.0 |
| STUCK | detected | 9/9 | 9/9 | 9/9 | 9/9 |
| STUCK | type_correct | 9/9 | 9/9 | 9/9 | 9/9 |
| STUCK | median_latency_min | 4.5 | 4.5 | 4.5 | 4.0 |
| (전체) | 주입 부작용 사건 | 4 | 1 | 0 | 6 |

## 3. 해석 주의

- 합성 모양은 SOP-002 정의를 그대로 옮긴 것이라 실제 이상의 다양성을 대표하지 않는다.
- 호스트 구간은 WARN 대역 안이지만 라벨로 확인한 정상 구간은 아니다(라벨을 읽지 않음).
- 공개 정답(14건) 평가는 설계·합성 평가·봉인 뒤 마지막에 1회만 한다.
