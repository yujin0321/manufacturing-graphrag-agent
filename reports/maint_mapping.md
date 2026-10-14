# MAINT-01~08 대조표: seed(nodes.csv/edges.csv) vs SOP-003 표

생성: `imaks_kg.kg.promote_rules` (직접 고치지 말 것). 2026-10-12 사용자 결정에 따라 KG의 `conditionText` = SOP-003 Trigger 셀, `responseText` = SOP-003 Action 셀 원문이다(셀 Provenance 연결). seed action은 KG 속성으로 두지 않고 이 표와 seed Provenance(nodes.csv 행)에만 남긴다. priority·센서는 seed와 SOP-003이 같아야 하며 다르면 변환이 멈춘다. 문구는 통일하지 않는다.

- seed 센서: edges.csv resolves(Maintenance→Sensor) 대상. triggers(Sensor→Maintenance)와 같은 쌍임을 코드가 확인했다.
- SOP-003 센서: 표의 Station 열 + Sensor 열 → seed monitors 엣지로 찾은 Sensor.
- seed 조건: nodes.csv Maintenance 행에는 조건(Trigger) 컬럼 값이 없다. 그래서 판정에서 조건은 제외하고 SOP-003 원문만 적는다.
- 판정은 센서·조치·우선순위의 문자열 정확 일치로 정한다.

| ID | seed 센서 | seed 조건 | seed 조치 | seed 우선순위 | SOP-003 셀(표 위치) | SOP-003 센서 | SOP-003 Trigger | SOP-003 Action | SOP-003 Priority | 판정 | 차이 설명 | KG conditionText·responseText 출처 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MAINT-01 | ST04_PACKAGING_VIB | (seed에 없음) | Inspect and lubricate main bearing | HIGH | SOP-003:p1:table1 행 2 | ST04_PACKAGING_VIB | VIB DRIFT >0.05 mm/s over 60 min | Inspect and lubricate bearing | HIGH | 다름 | 조치 문구: seed에만 'main' | SOP-003 (Trigger 열 4, Action 열 5) |
| MAINT-02 | ST02_SEALING_CUR | (seed에 없음) | Inspect sealing jaw alignment | HIGH | SOP-003:p1:table1 행 3 | ST02_SEALING_CUR | CUR DRIFT >1.0 A for 30+ min | Inspect sealing jaw | HIGH | 다름 | 조치 문구: seed에만 'alignment' | SOP-003 (Trigger 열 4, Action 열 5) |
| MAINT-03 | ST03_LABELLING_TEN | (seed에 없음) | Replace TEN sensor | MEDIUM | SOP-003:p1:table1 행 4 | ST03_LABELLING_TEN | TEN STUCK >10 samples | Replace sensor | MEDIUM | 다름 | 조치 문구: seed에만 'TEN' | SOP-003 (Trigger 열 4, Action 열 5) |
| MAINT-04 | ST01_FILLING_PRS | (seed에 없음) | Inspect inlet filter and pump | MEDIUM | SOP-003:p1:table1 행 5 | ST01_FILLING_PRS | PRS <3.3 bar for >15 min | Inspect filter and pump | MEDIUM | 다름 | 조치 문구: seed에만 'inlet' | SOP-003 (Trigger 열 4, Action 열 5) |
| MAINT-05 | SRV01_SERVERROOM_TMP | (seed에 없음) | Activate secondary cooling | CRITICAL | SOP-003:p1:table1 행 6 | SRV01_SERVERROOM_TMP | TMP >25°C for >5 min | Activate secondary cooling | CRITICAL | 같음 | - | SOP-003 (Trigger 열 4, Action 열 5) |
| MAINT-06 | WRH01_WAREHOUSE_TMP | (seed에 없음) | Inspect compressor; notify QC | CRITICAL | SOP-003:p1:table1 행 7 | WRH01_WAREHOUSE_TMP | TMP DRIFT >2°C over 2 h | Inspect compressor; notify QC | CRITICAL | 같음 | - | SOP-003 (Trigger 열 4, Action 열 5) |
| MAINT-07 | CHM01_CHEMICALSTORAGE_TMP | (seed에 없음) | Activate emergency ventilation; notify safety officer | CRITICAL | SOP-003:p1:table1 행 8 | CHM01_CHEMICALSTORAGE_TMP | TMP >20°C for >10 min | Emergency ventilation; notify safety officer | CRITICAL | 다름 | 조치 문구: 'Activate emergency'(seed) ↔ 'Emergency'(SOP-003) | SOP-003 (Trigger 열 4, Action 열 5) |
| MAINT-08 | RND01_RDLAB_HUM | (seed에 없음) | Activate dehumidifier; check HVAC drain | HIGH | SOP-003:p1:table1 행 9 | RND01_RDLAB_HUM | HUM DRIFT >10%RH over 60 min | Activate dehumidifier; check HVAC drain | HIGH | 같음 | - | SOP-003 (Trigger 열 4, Action 열 5) |

## 요약

- 행 수: 8, 같음 3, 다름 5
- 차이 유형 '조치 문구': 5행
