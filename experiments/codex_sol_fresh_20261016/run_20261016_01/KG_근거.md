# 규칙별 KG 연결과 원문 근거

AI가 원문을 검토한 기록이며 사람 승인 기록이 아닙니다. 전체 evidence 배열과 개별 SHA-256은 predictions.validated.jsonl 및 provenance.index.jsonl에 있습니다. 문자는 정규화 페이지 기준 0부터 시작하는 반열린 구간, 표 행·열은 헤더를 포함하여 1부터 시작합니다.

## RULE-ST01-01

- 문서/분류: SOP-001 / OperationalRule
- 조건: 명시 없음
- 조치/요구: FLW MUST be maintained between 112 and 128 L/min.
- 센서: ST01_FILLING_FLW
- 설비/제품 문맥: ST01_FILLING
- KG actionTarget: ST01_FILLING

> RULE-ST01-01: FLW MUST be maintained between 112 and 128 L/min.

위치: SOP-001 p1 · SOP-001:p1:RULE-ST01-01 · 문자 [997, 1060)  
인용 SHA-256: `d8ad78e87651a95826841915371587cad4f8e6b4160f8d06e055f4e66d1f5231`

## RULE-ST01-02

- 문서/분류: SOP-001 / OperationalRule
- 조건: If TMP exceeds 26°C
- 조치/요구: reduce speed by 10% and notify QC.
- 센서: ST01_FILLING_TMP
- 설비/제품 문맥: ST01_FILLING
- KG actionTarget: ST01_FILLING

> RULE-ST01-02: If TMP exceeds 26°C, reduce speed by 10% and notify QC.

위치: SOP-001 p1 · SOP-001:p1:RULE-ST01-02 · 문자 [1061, 1130)  
인용 SHA-256: `73ee97e31cfc87199c90371432c2676f2060989803b4b2c3bb07305003e2be3b`

## RULE-ST01-03

- 문서/분류: SOP-001 / OperationalRule
- 조건: PRS drop below 3.3 bar
- 조치/요구: inspect inlet valve within 5 min.
- 센서: ST01_FILLING_PRS
- 설비/제품 문맥: ST01_FILLING
- KG actionTarget: ST01_FILLING

> RULE-ST01-03: PRS drop below 3.3 bar — inspect inlet valve within 5 min.

위치: SOP-001 p1 · SOP-001:p1:RULE-ST01-03 · 문자 [1131, 1203)  
인용 SHA-256: `7715a13471accd30da4bf0acac0bbc99f239b32976e50a1c0bf701d3150f24d0`

## RULE-ST02-01

- 문서/분류: SOP-001 / OperationalRule
- 조건: 명시 없음
- 조치/요구: TMP MUST remain between 175°C and 195°C.
- 센서: ST02_SEALING_TMP
- 설비/제품 문맥: ST02_SEALING
- KG actionTarget: ST02_SEALING

> RULE-ST02-01: TMP MUST remain between 175°C and 195°C.

위치: SOP-001 p1 · SOP-001:p1:RULE-ST02-01 · 문자 [1221, 1275)  
인용 SHA-256: `13ca5b0d19263e1b5d194cc39150830d2c62febde76b2f4c97558cf824ccb7dd`

## RULE-ST02-02

- 문서/분류: SOP-001 / OperationalRule
- 조건: TMP > 210°C (CRITICAL)
- 조치/요구: emergency stop ST02, ST03, ST04.
- 센서: ST02_SEALING_TMP
- 설비/제품 문맥: ST02_SEALING
- KG actionTarget: ST02_SEALING, ST03_LABELLING, ST04_PACKAGING

> RULE-ST02-02: TMP > 210°C (CRITICAL) — emergency stop ST02, ST03, ST04.

위치: SOP-001 p1 · SOP-001:p1:RULE-ST02-02 · 문자 [1276, 1347)  
인용 SHA-256: `0e2de067573be179dcdc1b180dfe071c0fae3ea3a91f47df1418cadab40ce6e7`

## RULE-ST02-03

- 문서/분류: SOP-001 / OperationalRule
- 조건: CUR increase >1.5 A above nominal sustained >5 min
- 조치/요구: schedule maintenance.
- 센서: ST02_SEALING_CUR
- 설비/제품 문맥: ST02_SEALING
- KG actionTarget: ST02_SEALING

> RULE-ST02-03: CUR increase >1.5 A above nominal sustained >5 min — schedule maintenance.

위치: SOP-001 p1 · SOP-001:p1:RULE-ST02-03 · 문자 [1348, 1436)  
인용 SHA-256: `f3ab1bc29e8930a8b3d257bca6d35f392e414958ac5a9bf193baa259edcb3acd`

## RULE-ST02-04

- 문서/분류: SOP-001 / OperationalRule
- 조건: ST02_SEALING-CUR triggers a WARNING.
- 조치/요구: Monitor ST04_PACKAGING-SPD
- 센서: ST02_SEALING_CUR, ST04_PACKAGING_SPD
- 설비/제품 문맥: ST02_SEALING, ST04_PACKAGING
- KG actionTarget: 없음

> RULE-ST02-04: CUR drift at ST02_SEALING CORRELATES with speed reduction at ST04_PACKAGING due to shared electrical coupling. Monitor ST04_PACKAGING-SPD whenever ST02_SEALING-CUR triggers a WARNING.

위치: SOP-001 p1 · SOP-001:p1:RULE-ST02-04 · 문자 [1437, 1634)  
인용 SHA-256: `558ac58da1b9e1221da3d1fa761aa2b1ad4fe0b7379c7c0325a40231ae3f3a7d`

## RULE-ST03-01

- 문서/분류: SOP-001 / OperationalRule
- 조건: 명시 없음
- 조치/요구: TEN MUST be between 1.8 and 2.6 N.
- 센서: ST03_LABELLING_TEN
- 설비/제품 문맥: ST03_LABELLING
- KG actionTarget: ST03_LABELLING

> RULE-ST03-01: TEN MUST be between 1.8 and 2.6 N.

위치: SOP-001 p1 · SOP-001:p1:RULE-ST03-01 · 문자 [1654, 1702)  
인용 SHA-256: `50f6c1b9bf7749bf8cfd7b588fc4f114c3c43adfa4f320516295cd3e1bbdb3da`

## RULE-ST03-02

- 문서/분류: SOP-001 / OperationalRule
- 조건: CNT below 110 pcs/min; Below 100 (CRITICAL)
- 조치/요구: check for label jam.; halt.
- 센서: ST03_LABELLING_CNT
- 설비/제품 문맥: ST03_LABELLING
- KG actionTarget: ST03_LABELLING
- 분기: CNT below 110 pcs/min → check for label jam. / Below 100 (CRITICAL) → halt.

> RULE-ST03-02: CNT below 110 pcs/min — check for label jam. Below 100 (CRITICAL): halt.

위치: SOP-001 p1 · SOP-001:p1:RULE-ST03-02 · 문자 [1703, 1789)  
인용 SHA-256: `10f1e0bdc52639ba51ef6e37af3a52661fb365aab136ec3b4d09acf0e40520c6`

## RULE-ST03-03

- 문서/분류: SOP-001 / OperationalRule
- 조건: TEN STUCK >10 consecutive samples
- 조치/요구: 명시 없음
- 센서: ST03_LABELLING_TEN
- 설비/제품 문맥: ST03_LABELLING
- KG actionTarget: 없음

> RULE-ST03-03: TEN STUCK >10 consecutive samples — sensor failure.

위치: SOP-001 p1 · SOP-001:p1:RULE-ST03-03 · 문자 [1790, 1855)  
인용 SHA-256: `c0e8d93331c8c89ffa3526cbf4500958de207047c09bb60349a669c935a0d767`

## RULE-ST04-01

- 문서/분류: SOP-001 / OperationalRule
- 조건: VIB > 0.20 mm/s (WARNING)
- 조치/요구: schedule maintenance within 24 h.
- 센서: ST04_PACKAGING_VIB
- 설비/제품 문맥: ST04_PACKAGING
- KG actionTarget: ST04_PACKAGING

> RULE-ST04-01: VIB > 0.20 mm/s (WARNING) — schedule maintenance within 24 h.

위치: SOP-001 p1 · SOP-001:p1:RULE-ST04-01 · 문자 [1875, 1950)  
인용 SHA-256: `99d7497ab5f32a3e8f5325803496b1b4e935224205d34a37d63340cc12b4f9c9`

## RULE-ST04-02

- 문서/분류: SOP-001 / OperationalRule
- 조건: VIB > 0.35 mm/s (CRITICAL)
- 조치/요구: emergency stop; inspect bearings.
- 센서: ST04_PACKAGING_VIB
- 설비/제품 문맥: ST04_PACKAGING
- KG actionTarget: ST04_PACKAGING

> RULE-ST04-02: VIB > 0.35 mm/s (CRITICAL) — emergency stop; inspect bearings.

위치: SOP-001 p1 · SOP-001:p1:RULE-ST04-02 · 문자 [1951, 2027)  
인용 SHA-256: `642a28ef1a6c1b2f948b33a5f558fece7d827dded713dff5cf03f6eda53622c5`

## RULE-ST04-03

- 문서/분류: SOP-001 / OperationalRule
- 조건: SPD drops below 1.00 m/s without operator command
- 조치/요구: verify RULE-ST02-04.
- 센서: ST04_PACKAGING_SPD
- 설비/제품 문맥: ST04_PACKAGING
- KG actionTarget: 없음

> RULE-ST04-03: SPD drops below 1.00 m/s without operator command — verify RULE-ST02-04.

위치: SOP-001 p2 · SOP-001:p2:RULE-ST04-03 · 문자 [0, 86)  
인용 SHA-256: `250c09598246046f2ca766eef449b1340a89115bcbdae9cad0bbac1d1c6c03bc`

## RULE-SRV01-01

- 문서/분류: SOP-001 / OperationalRule
- 조건: 명시 없음
- 조치/요구: TMP MUST NOT exceed 25°C.
- 센서: SRV01_SERVERROOM_TMP
- 설비/제품 문맥: SRV01_SERVERROOM
- KG actionTarget: SRV01_SERVERROOM

> RULE-SRV01-01: TMP MUST NOT exceed 25°C.

위치: SOP-001 p2 · SOP-001:p2:RULE-SRV01-01 · 문자 [108, 148)  
인용 SHA-256: `c612095d691618b98a6e5fce1d52bdc384f66c3dedee7fca9e935f8093158dc9`

## RULE-SRV01-02

- 문서/분류: SOP-001 / OperationalRule
- 조건: TMP > 28°C (CRITICAL)
- 조치/요구: automatic controlled shutdown of all PLC nodes.
- 센서: SRV01_SERVERROOM_TMP
- 설비/제품 문맥: SRV01_SERVERROOM
- KG actionTarget: 없음

> RULE-SRV01-02: TMP > 28°C (CRITICAL) — automatic controlled shutdown of all PLC nodes.

위치: SOP-001 p2 · SOP-001:p2:RULE-SRV01-02 · 문자 [149, 235)  
인용 SHA-256: `fd53e57f0030686e7a5b67a898f1f958e7395b08b319b8c427b169837d8b59bc`

## RULE-WRH01-01

- 문서/분류: SOP-001 / OperationalRule
- 조건: CRITICAL above 12°C
- 조치/요구: TMP MUST remain between 0.5°C and 8°C.; notify QC and quarantine batch.
- 센서: WRH01_WAREHOUSE_TMP
- 설비/제품 문맥: WRH01_WAREHOUSE
- KG actionTarget: WRH01_WAREHOUSE
- 분기: 명시 없음 → TMP MUST remain between 0.5°C and 8°C. / CRITICAL above 12°C → notify QC and quarantine batch.

> RULE-WRH01-01: TMP MUST remain between 0.5°C and 8°C. CRITICAL above 12°C — notify QC and quarantine batch.

위치: SOP-001 p2 · SOP-001:p2:RULE-WRH01-01 · 문자 [276, 383)  
인용 SHA-256: `e089ebc01404931dbf293b8226e9eff734c60a14893ddae5eab5828f4b5205ca`

## RULE-WRH01-02

- 문서/분류: SOP-001 / OperationalRule
- 조건: HUM above 85%RH
- 조치/요구: inspect door seals and activate dehumidifier.
- 센서: WRH01_WAREHOUSE_HUM
- 설비/제품 문맥: WRH01_WAREHOUSE
- KG actionTarget: WRH01_WAREHOUSE

> RULE-WRH01-02: HUM above 85%RH — inspect door seals and activate dehumidifier.

위치: SOP-001 p2 · SOP-001:p2:RULE-WRH01-02 · 문자 [384, 462)  
인용 SHA-256: `80e86efa6cb0f94b3419445fce02ae11753203e847371c486e48ba84029b314c`

## RULE-CHM01-01

- 문서/분류: SOP-001 / OperationalRule
- 조건: CRITICAL above 25°C
- 조치/요구: TMP MUST remain between 10°C and 20°C.; activate emergency ventilation and notify safety officer immediately.
- 센서: CHM01_CHEMICALSTORAGE_TMP
- 설비/제품 문맥: CHM01_CHEMICALSTORAGE
- KG actionTarget: CHM01_CHEMICALSTORAGE
- 분기: 명시 없음 → TMP MUST remain between 10°C and 20°C. / CRITICAL above 25°C → activate emergency ventilation and notify safety officer immediately.

> RULE-CHM01-01: TMP MUST remain between 10°C and 20°C. CRITICAL above 25°C — activate emergency ventilation and notify safety officer immediately.

위치: SOP-001 p2 · SOP-001:p2:RULE-CHM01-01 · 문자 [508, 653)  
인용 SHA-256: `2b61de2aa19e5c44df35cf8577bc42fef697557cbfab05c2d94233db1066e0c2`

## RULE-CHM01-02

- 문서/분류: SOP-001 / OperationalRule
- 조건: HUM >45%RH.
- 조치/요구: HUM MUST NOT exceed 50%RH.; Activate desiccant system
- 센서: CHM01_CHEMICALSTORAGE_HUM
- 설비/제품 문맥: CHM01_CHEMICALSTORAGE
- KG actionTarget: CHM01_CHEMICALSTORAGE
- 분기: 명시 없음 → HUM MUST NOT exceed 50%RH. / HUM >45%RH. → Activate desiccant system

> RULE-CHM01-02: HUM MUST NOT exceed 50%RH. Elevated humidity accelerates degradation of hygroscopic reagents. Activate desiccant system if HUM >45%RH.

위치: SOP-001 p2 · SOP-001:p2:RULE-CHM01-02 · 문자 [654, 803)  
인용 SHA-256: `6b1ed550e4d2bc38adfed86bb698993361b59a21a90cd3af60a741231657e7e3`

## RULE-CHM01-03

- 문서/분류: SOP-001 / AccessRule
- 조건: UNAUTHORIZED_ACCESS
- 조치/요구: Only personnel with hazmat training (technician/supervisor/manager role) are authorised to enter Chemical Storage.; UNAUTHORIZED_ACCESS must be escalated within 2 minutes.
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: CHM01_CHEMICALSTORAGE
- KG actionTarget: 없음
- 분기: 명시 없음 → Only personnel with hazmat training (technician/supervisor/manager role) are authorised to enter Chemical Storage. / UNAUTHORIZED_ACCESS → must be escalated within 2 minutes.

> RULE-CHM01-03: Only personnel with hazmat training (technician/supervisor/manager role) are authorised to enter Chemical Storage. UNAUTHORIZED_ACCESS must be escalated within 2 minutes.

위치: SOP-001 p2 · SOP-001:p2:RULE-CHM01-03 · 문자 [804, 989)  
인용 SHA-256: `4efa3fcacd7db6289a5e3d4d4c08ae9561ce3905f2a71f3c67b54a089c2d235c`

## RULE-RND01-01

- 문서/분류: SOP-001 / OperationalRule
- 조건: 명시 없음
- 조치/요구: TMP MUST remain between 18°C and 26°C for experimental validity.
- 센서: RND01_RDLAB_TMP
- 설비/제품 문맥: RND01_RDLAB
- KG actionTarget: RND01_RDLAB

> RULE-RND01-01: TMP MUST remain between 18°C and 26°C for experimental validity.

위치: SOP-001 p2 · SOP-001:p2:RULE-RND01-01 · 문자 [1016, 1095)  
인용 SHA-256: `1ccc808cfbb4522fdef5d468b165eb3116523c264f677f347fcb33d76e0c1967`

## RULE-RND01-02

- 문서/분류: SOP-001 / OperationalRule
- 조건: HUM drift above 65%RH; Above 75%RH (CRITICAL)
- 조치/요구: activate dehumidifier.; suspend sensitive experiments and inspect HVAC system.
- 센서: RND01_RDLAB_HUM
- 설비/제품 문맥: RND01_RDLAB
- KG actionTarget: RND01_RDLAB
- 분기: HUM drift above 65%RH → activate dehumidifier. / Above 75%RH (CRITICAL) → suspend sensitive experiments and inspect HVAC system.

> RULE-RND01-02: HUM drift above 65%RH — activate dehumidifier. Above 75%RH (CRITICAL) — suspend sensitive experiments and inspect HVAC system.

위치: SOP-001 p2 · SOP-001:p2:RULE-RND01-02 · 문자 [1096, 1237)  
인용 SHA-256: `9016740037971fa9c46d813f0be59ef2e5655e0311dddba71dbe2f4247e666c0`

## RULE-CAF01-01

- 문서/분류: SOP-001 / OperationalRule
- 조건: TMP above 26°C
- 조치/요구: check ventilation system.
- 센서: CAF01_CAFETERIA_TMP
- 설비/제품 문맥: CAF01_CAFETERIA
- KG actionTarget: CAF01_CAFETERIA

> RULE-CAF01-01: TMP above 26°C — check ventilation system. Occupant comfort is the primary criterion.

위치: SOP-001 p2 · SOP-001:p2:RULE-CAF01-01 · 문자 [1258, 1358)  
인용 SHA-256: `f2e1bf23f599c7b467635895cccd6582da08cab28f4e30f315ec5ba502642080`

## RULE-CAF01-02

- 문서/분류: SOP-001 / OperationalRule
- 조건: HUM above 70%RH
- 조치/요구: inspect drainage and activate ventilation.
- 센서: CAF01_CAFETERIA_HUM
- 설비/제품 문맥: CAF01_CAFETERIA
- KG actionTarget: CAF01_CAFETERIA

> RULE-CAF01-02: HUM above 70%RH — inspect drainage and activate ventilation.

위치: SOP-001 p2 · SOP-001:p2:RULE-CAF01-02 · 문자 [1359, 1434)  
인용 SHA-256: `79f33a60a505d4124e2db5272ef361b4411198feec1e853cae6305001f3a1198`

## THR-ST01_FILLING_TMP

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=15.0; WARN_LO=18.0; Nominal=22.0 ± 0.4; WARN_HI=26.0; CRIT_HI=30.0
- 조치/요구: Inspect and notify maintenance
- 센서: ST01_FILLING_TMP
- 설비/제품 문맥: ST01_FILLING
- KG actionTarget: 없음

> TMP

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 2, 열 1 · bbox [65.2, 207.87, 107.72, 225.87]  
인용 SHA-256: `e789e660565bca113731795aaedba3f8dd95cdef51c3e0e83a014529b4e4334d`

> °C

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 2, 열 2 · bbox [107.72, 207.87, 141.73, 225.87]  
인용 SHA-256: `11c4350690a30002a4e786d72aa960ec0ad75b34dfa4cfe144c78c449d5e918a`

> 15.0

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 2, 열 3 · bbox [141.73, 207.87, 181.42, 225.87]  
인용 SHA-256: `c72ae9676454d7cc0014583a9d0a2e28553d5c62f087c7562b5307ebd1cc84c8`

> 18.0

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 2, 열 4 · bbox [181.42, 207.87, 221.1, 225.87]  
인용 SHA-256: `566afbb607a8f17b7cdf2d7f1632a2a810c06b128e8b81b6c6a8780eb9955dd1`

> 22.0 ± 0.4

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 2, 열 5 · bbox [221.1, 207.87, 289.13, 225.87]  
인용 SHA-256: `6d7cf55faf4f41036221c66b8ee4bba84d1efd4b357b632fa507fc21a37cfadb`

> 26.0

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 2, 열 6 · bbox [289.13, 207.87, 328.82, 225.87]  
인용 SHA-256: `80a753d4a473696b282e7cb81174a543a0973254e831f8c93e83a218f6045543`

> 30.0

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 2, 열 7 · bbox [328.82, 207.87, 368.5, 225.87]  
인용 SHA-256: `26c9a96ce053a14dd88a71a4830c9cbed7e1fed7e3f3f8a0b0b6a58f3f0f02e6`

> Inspect and notify maintenance

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 2, 열 8 · bbox [368.5, 207.87, 530.08, 225.87]  
인용 SHA-256: `491fc2ec197ce42f4e2a47587ab17b63d73d614e4cd418eafb5424aa721687d3`

## THR-ST01_FILLING_PRS

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=3.0; WARN_LO=3.3; Nominal=3.8 ± 0.05; WARN_HI=4.2; CRIT_HI=4.8
- 조치/요구: Inspect and notify maintenance
- 센서: ST01_FILLING_PRS
- 설비/제품 문맥: ST01_FILLING
- KG actionTarget: 없음

> PRS

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 3, 열 1 · bbox [65.2, 225.87, 107.72, 243.87]  
인용 SHA-256: `b5c84667baa4d9be1c7b42d7d7579fb93702f9b47a5d556dcd5de48d83da26e0`

> bar

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 3, 열 2 · bbox [107.72, 225.87, 141.73, 243.87]  
인용 SHA-256: `fcde2b2edba56bf408601fb721fe9b5c338d10ee429ea04fae5511b68fbf8fb9`

> 3.0

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 3, 열 3 · bbox [141.73, 225.87, 181.42, 243.87]  
인용 SHA-256: `a416ea84421fa7e1351582da48235bac88380a337ec5cb5a9239dc7d57908b4b`

> 3.3

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 3, 열 4 · bbox [181.42, 225.87, 221.1, 243.87]  
인용 SHA-256: `8c92bebd740430af1b95f3b0deb80df3b03cc6f9d8417b1dffb75d5c37c707b5`

> 3.8 ± 0.05

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 3, 열 5 · bbox [221.1, 225.87, 289.13, 243.87]  
인용 SHA-256: `afb4f096328d8795fdf121d116bc95304ed4eab30c5dbb33f09d8e28c60bf3aa`

> 4.2

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 3, 열 6 · bbox [289.13, 225.87, 328.82, 243.87]  
인용 SHA-256: `2912aa729c973b7d68a2deda6cb5595fdb1e0368cffffaf6a8c135cdea63c83d`

> 4.8

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 3, 열 7 · bbox [328.82, 225.87, 368.5, 243.87]  
인용 SHA-256: `9c7f38a9ac4f5de592be486948ac944aff688f914e3b74e6917c7fe4715a561e`

> Inspect and notify maintenance

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 3, 열 8 · bbox [368.5, 225.87, 530.08, 243.87]  
인용 SHA-256: `491fc2ec197ce42f4e2a47587ab17b63d73d614e4cd418eafb5424aa721687d3`

## THR-ST01_FILLING_FLW

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=105.0; WARN_LO=112.0; Nominal=120.0 ± 1.5; WARN_HI=128.0; CRIT_HI=135.0
- 조치/요구: Inspect and notify maintenance
- 센서: ST01_FILLING_FLW
- 설비/제품 문맥: ST01_FILLING
- KG actionTarget: 없음

> FLW

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 4, 열 1 · bbox [65.2, 243.87, 107.72, 261.87]  
인용 SHA-256: `06cd8a964b70b40a855882693ce12cc22bff7e4ef2b145a3bebdbcb22abbff2e`

> L/min

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 4, 열 2 · bbox [107.72, 243.87, 141.73, 261.87]  
인용 SHA-256: `57c8fa26050c1c6f07cc908883055b9563f8a2f1e0d34e136f767ce2f88287b3`

> 105.0

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 4, 열 3 · bbox [141.73, 243.87, 181.42, 261.87]  
인용 SHA-256: `11a86311d39aaaf9c4d289b5b616d72150b83042889b92e1cd330a32d763995f`

> 112.0

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 4, 열 4 · bbox [181.42, 243.87, 221.1, 261.87]  
인용 SHA-256: `0b9d95512b4384db85d664b9894206b8a4a9b35394449ea7614b55375f016e1b`

> 120.0 ± 1.5

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 4, 열 5 · bbox [221.1, 243.87, 289.13, 261.87]  
인용 SHA-256: `f731c0cd6a2f91663f81a4228d1d15dcbb986cf9944faabe56ff99c6c7afad6c`

> 128.0

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 4, 열 6 · bbox [289.13, 243.87, 328.82, 261.87]  
인용 SHA-256: `39a755661b40f12eee048ea095818a5c8027643bc29ebf2acdca77c14f1e8d22`

> 135.0

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 4, 열 7 · bbox [328.82, 243.87, 368.5, 261.87]  
인용 SHA-256: `e1b1b8a0c864da5bd09443c79f1de7b7fa7ce6e7a73b4a7f9572753931a36074`

> Inspect and notify maintenance

위치: SOP-002 p1 · SOP-002:p1:table1 · 행 4, 열 8 · bbox [368.5, 243.87, 530.08, 261.87]  
인용 SHA-256: `491fc2ec197ce42f4e2a47587ab17b63d73d614e4cd418eafb5424aa721687d3`

## THR-ST02_SEALING_TMP

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=165.0; WARN_LO=175.0; Nominal=185.0 ± 1.2; WARN_HI=195.0; CRIT_HI=210.0
- 조치/요구: E-STOP ST02/ST03/ST04; inspect element
- 센서: ST02_SEALING_TMP
- 설비/제품 문맥: ST02_SEALING
- KG actionTarget: ST02_SEALING, ST03_LABELLING, ST04_PACKAGING

> TMP

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 2, 열 1 · bbox [65.2, 334.87, 107.72, 362.87]  
인용 SHA-256: `e789e660565bca113731795aaedba3f8dd95cdef51c3e0e83a014529b4e4334d`

> °C

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 2, 열 2 · bbox [107.72, 334.87, 141.73, 362.87]  
인용 SHA-256: `11c4350690a30002a4e786d72aa960ec0ad75b34dfa4cfe144c78c449d5e918a`

> 165.0

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 2, 열 3 · bbox [141.73, 334.87, 181.42, 362.87]  
인용 SHA-256: `041e391c69640edb931a7a84c3c0f6725d03f53a574fd96763d327cb2d8b97cf`

> 175.0

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 2, 열 4 · bbox [181.42, 334.87, 221.1, 362.87]  
인용 SHA-256: `10abc2d0fe99e21094416150b7e416cd443ee85169703112054901299db12a9e`

> 185.0 ± 1.2

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 2, 열 5 · bbox [221.1, 334.87, 289.13, 362.87]  
인용 SHA-256: `3b8c4a00916cbad8eb1d1ec11df33bcf20053ad0511de93b8574e279f479fc6a`

> 195.0

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 2, 열 6 · bbox [289.13, 334.87, 328.82, 362.87]  
인용 SHA-256: `f8aa7c4aac45462c6b70e2ca0b619a470a48010589650eb80ce290c02c5edb29`

> 210.0

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 2, 열 7 · bbox [328.82, 334.87, 368.5, 362.87]  
인용 SHA-256: `75f0c1dfd1a75d28b7e077c2b47d5520467d7c256caf1a7f9719baef35bc1ef2`

> E-STOP ST02/ST03/ST04; inspect element

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 2, 열 8 · bbox [368.5, 334.87, 530.08, 362.87]  
인용 SHA-256: `3974d323cacd09c1b74afd2a0d194422ba617ea9e2e32ce2a3851888830bfc64`

## THR-ST02_SEALING_PRS

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=4.2; WARN_LO=4.6; Nominal=5.2 ± 0.08; WARN_HI=5.7; CRIT_HI=6.2
- 조치/요구: Inspect and notify maintenance
- 센서: ST02_SEALING_PRS
- 설비/제품 문맥: ST02_SEALING
- KG actionTarget: 없음

> PRS

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 3, 열 1 · bbox [65.2, 362.87, 107.72, 380.87]  
인용 SHA-256: `b5c84667baa4d9be1c7b42d7d7579fb93702f9b47a5d556dcd5de48d83da26e0`

> bar

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 3, 열 2 · bbox [107.72, 362.87, 141.73, 380.87]  
인용 SHA-256: `fcde2b2edba56bf408601fb721fe9b5c338d10ee429ea04fae5511b68fbf8fb9`

> 4.2

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 3, 열 3 · bbox [141.73, 362.87, 181.42, 380.87]  
인용 SHA-256: `2912aa729c973b7d68a2deda6cb5595fdb1e0368cffffaf6a8c135cdea63c83d`

> 4.6

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 3, 열 4 · bbox [181.42, 362.87, 221.1, 380.87]  
인용 SHA-256: `8bf40d0515e8461bd30866c2eb8ac250ad268195b2f141cc4e8b640d5c81d406`

> 5.2 ± 0.08

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 3, 열 5 · bbox [221.1, 362.87, 289.13, 380.87]  
인용 SHA-256: `aa4869815e2dcdd3b64c134f423b68352df09916b90471148b96da157ee0f430`

> 5.7

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 3, 열 6 · bbox [289.13, 362.87, 328.82, 380.87]  
인용 SHA-256: `d64b9aeca5ff892d8bee19b7ba43dafd3b9d51ec24cc150fbb3152d5fc40d152`

> 6.2

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 3, 열 7 · bbox [328.82, 362.87, 368.5, 380.87]  
인용 SHA-256: `69dfc187e2e6d907a0546f7e76f8ee3f44d60e2a192c58fd76117d6de13a3065`

> Inspect and notify maintenance

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 3, 열 8 · bbox [368.5, 362.87, 530.08, 380.87]  
인용 SHA-256: `491fc2ec197ce42f4e2a47587ab17b63d73d614e4cd418eafb5424aa721687d3`

## THR-ST02_SEALING_CUR

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=9.5; WARN_LO=11.0; Nominal=12.4 ± 0.3; WARN_HI=13.5; CRIT_HI=15.0
- 조치/요구: E-STOP; inspect load; verify ST04-SPD (RULE-ST02-04)
- 센서: ST02_SEALING_CUR
- 설비/제품 문맥: ST02_SEALING
- KG actionTarget: ST02_SEALING

> CUR

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 4, 열 1 · bbox [65.2, 380.87, 107.72, 408.87]  
인용 SHA-256: `66d2af90645aa5197e4541bb208343e3ddcce962b02697e59014e3d93ea721f8`

> A

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 4, 열 2 · bbox [107.72, 380.87, 141.73, 408.87]  
인용 SHA-256: `559aead08264d5795d3909718cdd05abd49572e84fe55590eef31a88a08fdffd`

> 9.5

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 4, 열 3 · bbox [141.73, 380.87, 181.42, 408.87]  
인용 SHA-256: `e0b04046fbfbc96f3437e4718a8a15e7eb5936298a36a8c2039226d1c5f41845`

> 11.0

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 4, 열 4 · bbox [181.42, 380.87, 221.1, 408.87]  
인용 SHA-256: `56824d16dcb61c982fc31a731cf6f20594c0a3f1da2aff349ee804bf1c4544d1`

> 12.4 ± 0.3

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 4, 열 5 · bbox [221.1, 380.87, 289.13, 408.87]  
인용 SHA-256: `08584169abefb4052fe2ede59ceb24a514282a344080adec62be95783d1d7473`

> 13.5

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 4, 열 6 · bbox [289.13, 380.87, 328.82, 408.87]  
인용 SHA-256: `49dd409d9fb9b718d70f9b826b855a65202b6d3a47378e0ac0501c928fe5ba92`

> 15.0

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 4, 열 7 · bbox [328.82, 380.87, 368.5, 408.87]  
인용 SHA-256: `c72ae9676454d7cc0014583a9d0a2e28553d5c62f087c7562b5307ebd1cc84c8`

> E-STOP; inspect load; verify ST04-SPD (RULE-ST02-04)

위치: SOP-002 p1 · SOP-002:p1:table2 · 행 4, 열 8 · bbox [368.5, 380.87, 530.08, 408.87]  
인용 SHA-256: `fa85e670b708d2b25a1fb205c04966a8ef951e2481013c0048559e51e0c5c7d6`

## THR-ST03_LABELLING_SPD

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=0.65; WARN_LO=0.75; Nominal=0.85 ± 0.01; WARN_HI=0.95; CRIT_HI=1.05
- 조치/요구: Inspect and notify maintenance
- 센서: ST03_LABELLING_SPD
- 설비/제품 문맥: ST03_LABELLING
- KG actionTarget: 없음

> SPD

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 2, 열 1 · bbox [65.2, 481.87, 107.72, 499.87]  
인용 SHA-256: `94424ddcbe29778d37a03e605a90a0e1c0f6f2c9e0f473b69f68be2b21d30d36`

> m/s

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 2, 열 2 · bbox [107.72, 481.87, 141.73, 499.87]  
인용 SHA-256: `cf54a2919ff82f0dab808decc39899e017647935bb89f13ed6e6be7408ed15a0`

> 0.65

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 2, 열 3 · bbox [141.73, 481.87, 181.42, 499.87]  
인용 SHA-256: `4942870d7312d707982f792e63180e31f72925b998dec46f7ce23db6f16e2d3b`

> 0.75

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 2, 열 4 · bbox [181.42, 481.87, 221.1, 499.87]  
인용 SHA-256: `ce5d3aa79ae56155078af52e8fac68eb2d0a78489f82bc26c1e1bbc667ba9fde`

> 0.85 ± 0.01

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 2, 열 5 · bbox [221.1, 481.87, 289.13, 499.87]  
인용 SHA-256: `40f19368d96d982c7a38442cef26c85838801dfdfc7906f469217e4a7e3ce54e`

> 0.95

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 2, 열 6 · bbox [289.13, 481.87, 328.82, 499.87]  
인용 SHA-256: `22fa3ce4995af8d96fcd771f0e1f5d74d8a98f36c3eec8e95bdf7524926b0141`

> 1.05

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 2, 열 7 · bbox [328.82, 481.87, 368.5, 499.87]  
인용 SHA-256: `00fef940a6aaf1e03dc157bcb46b818823ad5b5928a9011d7006809f08931eb4`

> Inspect and notify maintenance

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 2, 열 8 · bbox [368.5, 481.87, 530.08, 499.87]  
인용 SHA-256: `491fc2ec197ce42f4e2a47587ab17b63d73d614e4cd418eafb5424aa721687d3`

## THR-ST03_LABELLING_TEN

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=1.5; WARN_LO=1.8; Nominal=2.2 ± 0.05; WARN_HI=2.6; CRIT_HI=3.0
- 조치/요구: Inspect and notify maintenance
- 센서: ST03_LABELLING_TEN
- 설비/제품 문맥: ST03_LABELLING
- KG actionTarget: 없음

> TEN

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 3, 열 1 · bbox [65.2, 499.87, 107.72, 517.87]  
인용 SHA-256: `5a15b6c4e2f863171b809f269c66c5fa8abf9ffcac6f6ff79a83a26f1c59ee55`

> N

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 3, 열 2 · bbox [107.72, 499.87, 141.73, 517.87]  
인용 SHA-256: `8ce86a6ae65d3692e7305e2c58ac62eebd97d3d943e093f577da25c36988246b`

> 1.5

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 3, 열 3 · bbox [141.73, 499.87, 181.42, 517.87]  
인용 SHA-256: `9f29a130438b81170b92a42650f9a94291ecad60bd47af2a3886e75f7f728725`

> 1.8

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 3, 열 4 · bbox [181.42, 499.87, 221.1, 517.87]  
인용 SHA-256: `a97b042d7bd59d92a46e8ab17f7dff7326067c74b938e6f6daabf1768932330d`

> 2.2 ± 0.05

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 3, 열 5 · bbox [221.1, 499.87, 289.13, 517.87]  
인용 SHA-256: `b0d4aaf1f32daa759ade99c7f97dc42b40d07511f78d01127c4e8edf43290f7c`

> 2.6

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 3, 열 6 · bbox [289.13, 499.87, 328.82, 517.87]  
인용 SHA-256: `af3266e6d0f3bba206c2e954c21ff72182e440557702a3f79f4c6bdfb577fed5`

> 3.0

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 3, 열 7 · bbox [328.82, 499.87, 368.5, 517.87]  
인용 SHA-256: `a416ea84421fa7e1351582da48235bac88380a337ec5cb5a9239dc7d57908b4b`

> Inspect and notify maintenance

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 3, 열 8 · bbox [368.5, 499.87, 530.08, 517.87]  
인용 SHA-256: `491fc2ec197ce42f4e2a47587ab17b63d73d614e4cd418eafb5424aa721687d3`

## THR-ST03_LABELLING_CNT

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=100; WARN_LO=110; Nominal=120 ± 2.0; WARN_HI=130; CRIT_HI=140
- 조치/요구: E-STOP labelling; inspect label path
- 센서: ST03_LABELLING_CNT
- 설비/제품 문맥: ST03_LABELLING
- KG actionTarget: ST03_LABELLING

> CNT

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 4, 열 1 · bbox [65.2, 517.87, 107.72, 545.87]  
인용 SHA-256: `2fa210d13e5f0b01b115f1e24da41a8f6527eae4f0dbbb27fcc0d7f9c14ebe2e`

> pcs/min

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 4, 열 2 · bbox [107.72, 517.87, 141.73, 545.87]  
인용 SHA-256: `9251c7f3b898ca28d57cde26d49d3bcb6bc5f6082478e48481b2276a91406f49`

> 100

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 4, 열 3 · bbox [141.73, 517.87, 181.42, 545.87]  
인용 SHA-256: `ad57366865126e55649ecb23ae1d48887544976efea46a48eb5d85a6eeb4d306`

> 110

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 4, 열 4 · bbox [181.42, 517.87, 221.1, 545.87]  
인용 SHA-256: `9bdb2af6799204a299c603994b8e400e4b1fd625efdb74066cc869fee42c9df3`

> 120 ± 2.0

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 4, 열 5 · bbox [221.1, 517.87, 289.13, 545.87]  
인용 SHA-256: `782ceafcbb95f9b6c1235ce09db4e3f092251a40a4d23a5477d29625811a534f`

> 130

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 4, 열 6 · bbox [289.13, 517.87, 328.82, 545.87]  
인용 SHA-256: `38d66d9692ac590000a91b03a88da1c88d51fab2b78f63171f553ecc551a0c6f`

> 140

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 4, 열 7 · bbox [328.82, 517.87, 368.5, 545.87]  
인용 SHA-256: `dbae772db29058a88f9bd830e957c695347c41b6162a7eb9a9ea13def34be56b`

> E-STOP labelling; inspect label path

위치: SOP-002 p1 · SOP-002:p1:table3 · 행 4, 열 8 · bbox [368.5, 517.87, 530.08, 545.87]  
인용 SHA-256: `95caa4a4e6602bbb597b01dd122af3aa0053163a99238fd4e7d2216c16069997`

## THR-ST04_PACKAGING_VIB

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=0.01; WARN_LO=0.02; Nominal=0.12 ± 0.005; WARN_HI=0.2; CRIT_HI=0.35
- 조치/요구: E-STOP; inspect main bearing
- 센서: ST04_PACKAGING_VIB
- 설비/제품 문맥: ST04_PACKAGING
- KG actionTarget: ST04_PACKAGING

> VIB

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 2, 열 1 · bbox [65.2, 618.87, 107.72, 636.87]  
인용 SHA-256: `ff1264aaa35d2e0c29c7e25e1d06e6d64f64dd98ef1f6894105bc6cd0cf3f0c4`

> mm/s

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 2, 열 2 · bbox [107.72, 618.87, 141.73, 636.87]  
인용 SHA-256: `b15b658ebc842824c0ca5240b32f27b5619cef5c7f293311e1954b2091bc0958`

> 0.01

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 2, 열 3 · bbox [141.73, 618.87, 181.42, 636.87]  
인용 SHA-256: `312b95ee5a344d2f7a16ad817ff70788980da6e30b9bb04b651d53847abd476f`

> 0.02

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 2, 열 4 · bbox [181.42, 618.87, 221.1, 636.87]  
인용 SHA-256: `a7e46abf169710b34fe8898b950d57ec0863c3a4190e4b38c56b1f9f257d50e7`

> 0.12 ± 0.005

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 2, 열 5 · bbox [221.1, 618.87, 289.13, 636.87]  
인용 SHA-256: `53ced8fdd8ab245b2cd85e6e1da7fa76e630a76ad65c3edc807439c9fcb9a814`

> 0.2

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 2, 열 6 · bbox [289.13, 618.87, 328.82, 636.87]  
인용 SHA-256: `44896b09365746b5f7167ee4d64988a38f7f4628803cbf86224e74eeb7c69e9d`

> 0.35

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 2, 열 7 · bbox [328.82, 618.87, 368.5, 636.87]  
인용 SHA-256: `a976726b1d1bda3e1f271287f3aa7229ca3204ff8bf9cb2b581c610b9c811bef`

> E-STOP; inspect main bearing

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 2, 열 8 · bbox [368.5, 618.87, 530.08, 636.87]  
인용 SHA-256: `b1fb27274b7da523a514f1cd3a6c86cbb4db424f9caa133a0f73471c9a11f9be`

## THR-ST04_PACKAGING_CUR

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=6.5; WARN_LO=7.5; Nominal=8.7 ± 0.2; WARN_HI=9.8; CRIT_HI=11.0
- 조치/요구: Inspect and notify maintenance
- 센서: ST04_PACKAGING_CUR
- 설비/제품 문맥: ST04_PACKAGING
- KG actionTarget: 없음

> CUR

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 3, 열 1 · bbox [65.2, 636.87, 107.72, 654.87]  
인용 SHA-256: `66d2af90645aa5197e4541bb208343e3ddcce962b02697e59014e3d93ea721f8`

> A

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 3, 열 2 · bbox [107.72, 636.87, 141.73, 654.87]  
인용 SHA-256: `559aead08264d5795d3909718cdd05abd49572e84fe55590eef31a88a08fdffd`

> 6.5

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 3, 열 3 · bbox [141.73, 636.87, 181.42, 654.87]  
인용 SHA-256: `a22eea496bce0154f2e2dc5e652100cd8a0f9571b95ed89dd48599e76d339657`

> 7.5

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 3, 열 4 · bbox [181.42, 636.87, 221.1, 654.87]  
인용 SHA-256: `c4495da75095c64bf4e0587e45d7426f496ca4fc9fe72111715005361cfe0041`

> 8.7 ± 0.2

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 3, 열 5 · bbox [221.1, 636.87, 289.13, 654.87]  
인용 SHA-256: `bb69f48b80e2d7dbc0cddbd78902ff9efabbf3094312672b20ffe12f58ebe9f3`

> 9.8

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 3, 열 6 · bbox [289.13, 636.87, 328.82, 654.87]  
인용 SHA-256: `fd263f51d2398f2219b7f31c9c964dc7eff00b31bab1a7b7e59426fd52500de0`

> 11.0

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 3, 열 7 · bbox [328.82, 636.87, 368.5, 654.87]  
인용 SHA-256: `56824d16dcb61c982fc31a731cf6f20594c0a3f1da2aff349ee804bf1c4544d1`

> Inspect and notify maintenance

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 3, 열 8 · bbox [368.5, 636.87, 530.08, 654.87]  
인용 SHA-256: `491fc2ec197ce42f4e2a47587ab17b63d73d614e4cd418eafb5424aa721687d3`

## THR-ST04_PACKAGING_SPD

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=0.85; WARN_LO=1.0; Nominal=1.2 ± 0.02; WARN_HI=1.4; CRIT_HI=1.6
- 조치/요구: Inspect and notify maintenance
- 센서: ST04_PACKAGING_SPD
- 설비/제품 문맥: ST04_PACKAGING
- KG actionTarget: 없음

> SPD

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 4, 열 1 · bbox [65.2, 654.87, 107.72, 672.87]  
인용 SHA-256: `94424ddcbe29778d37a03e605a90a0e1c0f6f2c9e0f473b69f68be2b21d30d36`

> m/s

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 4, 열 2 · bbox [107.72, 654.87, 141.73, 672.87]  
인용 SHA-256: `cf54a2919ff82f0dab808decc39899e017647935bb89f13ed6e6be7408ed15a0`

> 0.85

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 4, 열 3 · bbox [141.73, 654.87, 181.42, 672.87]  
인용 SHA-256: `1e181f0934d441445f03ff51c972ef44275b830c10a80401e53b27bf5baf327a`

> 1.0

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 4, 열 4 · bbox [181.42, 654.87, 221.1, 672.87]  
인용 SHA-256: `d0ff5974b6aa52cf562bea5921840c032a860a91a3512f7fe8f768f6bbe005f6`

> 1.2 ± 0.02

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 4, 열 5 · bbox [221.1, 654.87, 289.13, 672.87]  
인용 SHA-256: `0909728cab0d696ba6848c40bf91bbe21f98c1547b4581e29c80e891fe42f1f2`

> 1.4

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 4, 열 6 · bbox [289.13, 654.87, 328.82, 672.87]  
인용 SHA-256: `1a948f1b4374f4e3f02501c7feb43784021718a93c1ed5f9f19adf357bb2d20e`

> 1.6

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 4, 열 7 · bbox [328.82, 654.87, 368.5, 672.87]  
인용 SHA-256: `ec6c168f4411ec8fa9ab8d47dd25954ce53728404fed0e7a9bc7f29dab38c30d`

> Inspect and notify maintenance

위치: SOP-002 p1 · SOP-002:p1:table4 · 행 4, 열 8 · bbox [368.5, 654.87, 530.08, 672.87]  
인용 SHA-256: `491fc2ec197ce42f4e2a47587ab17b63d73d614e4cd418eafb5424aa721687d3`

## THR-SRV01_SERVERROOM_TMP

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=16.0; WARN_LO=18.0; Nominal=21.0 ± 0.3; WARN_HI=25.0; CRIT_HI=28.0
- 조치/요구: Activate backup cooling; prepare controlled PLC shutdown
- 센서: SRV01_SERVERROOM_TMP
- 설비/제품 문맥: SRV01_SERVERROOM
- KG actionTarget: 없음

> TMP

위치: SOP-002 p1 · SOP-002:p1:table5 · 행 2, 열 1 · bbox [65.2, 745.87, 107.72, 773.87]  
인용 SHA-256: `e789e660565bca113731795aaedba3f8dd95cdef51c3e0e83a014529b4e4334d`

> °C

위치: SOP-002 p1 · SOP-002:p1:table5 · 행 2, 열 2 · bbox [107.72, 745.87, 141.73, 773.87]  
인용 SHA-256: `11c4350690a30002a4e786d72aa960ec0ad75b34dfa4cfe144c78c449d5e918a`

> 16.0

위치: SOP-002 p1 · SOP-002:p1:table5 · 행 2, 열 3 · bbox [141.73, 745.87, 181.42, 773.87]  
인용 SHA-256: `e38e216cb55bf07f1b4188684ef9d47945ad0247c1bb6314fe03f2b99a0c7145`

> 18.0

위치: SOP-002 p1 · SOP-002:p1:table5 · 행 2, 열 4 · bbox [181.42, 745.87, 221.1, 773.87]  
인용 SHA-256: `566afbb607a8f17b7cdf2d7f1632a2a810c06b128e8b81b6c6a8780eb9955dd1`

> 21.0 ± 0.3

위치: SOP-002 p1 · SOP-002:p1:table5 · 행 2, 열 5 · bbox [221.1, 745.87, 289.13, 773.87]  
인용 SHA-256: `f564fed4dfe9ea23d6f25f6749465b946caf26116eccd212f2f5e365abdcf927`

> 25.0

위치: SOP-002 p1 · SOP-002:p1:table5 · 행 2, 열 6 · bbox [289.13, 745.87, 328.82, 773.87]  
인용 SHA-256: `00c10b58d5c431fee46080cd1ce96bf2fd15a683255e9fc30ee0f672dad91424`

> 28.0

위치: SOP-002 p1 · SOP-002:p1:table5 · 행 2, 열 7 · bbox [328.82, 745.87, 368.5, 773.87]  
인용 SHA-256: `3884d73b84f2e88d36a540aa9587c500a76922cf48463d3c130917896b5fcac4`

> Activate backup cooling; prepare controlled PLC shutdown

위치: SOP-002 p1 · SOP-002:p1:table5 · 행 2, 열 8 · bbox [368.5, 745.87, 530.08, 773.87]  
인용 SHA-256: `1af5c6bf1fa43e9ed346471838ee2c5f607bf27da19a10c74cb2a666cdb6a727`

## THR-SRV01_SERVERROOM_HUM

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=25.0; WARN_LO=30.0; Nominal=45.0 ± 1.0; WARN_HI=60.0; CRIT_HI=70.0
- 조치/요구: Inspect and notify maintenance
- 센서: SRV01_SERVERROOM_HUM
- 설비/제품 문맥: SRV01_SERVERROOM
- KG actionTarget: 없음

> HUM

위치: SOP-002 p2 · SOP-002:p2:table1 · 행 1, 열 1 · bbox [65.2, 76.87, 107.72, 94.87]  
인용 SHA-256: `c985ea35c7c867fdded4528ec701eb53de48ef7558a9d91218148a41e88a2e9b`

> %RH

위치: SOP-002 p2 · SOP-002:p2:table1 · 행 1, 열 2 · bbox [107.72, 76.87, 141.73, 94.87]  
인용 SHA-256: `f52ab883875e9391646d21772e85a046e48eecd3331f981780605a9fc87f5912`

> 25.0

위치: SOP-002 p2 · SOP-002:p2:table1 · 행 1, 열 3 · bbox [141.73, 76.87, 181.42, 94.87]  
인용 SHA-256: `00c10b58d5c431fee46080cd1ce96bf2fd15a683255e9fc30ee0f672dad91424`

> 30.0

위치: SOP-002 p2 · SOP-002:p2:table1 · 행 1, 열 4 · bbox [181.42, 76.87, 221.1, 94.87]  
인용 SHA-256: `26c9a96ce053a14dd88a71a4830c9cbed7e1fed7e3f3f8a0b0b6a58f3f0f02e6`

> 45.0 ± 1.0

위치: SOP-002 p2 · SOP-002:p2:table1 · 행 1, 열 5 · bbox [221.1, 76.87, 289.13, 94.87]  
인용 SHA-256: `3da8615fff63cacf0eb9db6824abe6d4030078598418aa65b49ec4966f54cb05`

> 60.0

위치: SOP-002 p2 · SOP-002:p2:table1 · 행 1, 열 6 · bbox [289.13, 76.87, 328.82, 94.87]  
인용 SHA-256: `db58b6c40698d7371bbcff35d085e1bac5fa439d0de31eb8e0da7c47d27cb2a7`

> 70.0

위치: SOP-002 p2 · SOP-002:p2:table1 · 행 1, 열 7 · bbox [328.82, 76.87, 368.5, 94.87]  
인용 SHA-256: `2e12c864ec5ae8d3f0e2921625d48a7ef0adf5b5ba4eeb561cf409fc11c888f6`

> Inspect and notify maintenance

위치: SOP-002 p2 · SOP-002:p2:table1 · 행 1, 열 8 · bbox [368.5, 76.87, 530.08, 94.87]  
인용 SHA-256: `491fc2ec197ce42f4e2a47587ab17b63d73d614e4cd418eafb5424aa721687d3`

## THR-WRH01_WAREHOUSE_TMP

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=-1.0; WARN_LO=0.5; Nominal=4.0 ± 0.5; WARN_HI=8.0; CRIT_HI=12.0
- 조치/요구: Activate backup refrigeration; notify QC
- 센서: WRH01_WAREHOUSE_TMP
- 설비/제품 문맥: WRH01_WAREHOUSE
- KG actionTarget: 없음

> TMP

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 2, 열 1 · bbox [65.2, 167.87, 107.72, 185.87]  
인용 SHA-256: `e789e660565bca113731795aaedba3f8dd95cdef51c3e0e83a014529b4e4334d`

> °C

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 2, 열 2 · bbox [107.72, 167.87, 141.73, 185.87]  
인용 SHA-256: `11c4350690a30002a4e786d72aa960ec0ad75b34dfa4cfe144c78c449d5e918a`

> -1.0

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 2, 열 3 · bbox [141.73, 167.87, 181.42, 185.87]  
인용 SHA-256: `f006c4915bce75dd9588871a11328f1acac2cba2af8b786e66f70b6301469193`

> 0.5

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 2, 열 4 · bbox [181.42, 167.87, 221.1, 185.87]  
인용 SHA-256: `d2cbad71ff333de67d07ec676e352ab7f38248eb69c942950157220607c55e84`

> 4.0 ± 0.5

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 2, 열 5 · bbox [221.1, 167.87, 289.13, 185.87]  
인용 SHA-256: `b469e647425d0a633036017242c3fadafffdc5d0a54468ef7e3ae1d08e31f8d2`

> 8.0

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 2, 열 6 · bbox [289.13, 167.87, 328.82, 185.87]  
인용 SHA-256: `7b1bd53949b752d143d871408483b5382371b5bc48d195d0c040ec93cfa2748b`

> 12.0

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 2, 열 7 · bbox [328.82, 167.87, 368.5, 185.87]  
인용 SHA-256: `77c52f3feed5acdd119b1f8449d5ccc2d39be94bd0314d5b7302f36e20b6cea9`

> Activate backup refrigeration; notify QC

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 2, 열 8 · bbox [368.5, 167.87, 530.08, 185.87]  
인용 SHA-256: `fb34645e8667a100604385fca0ba9cfa4c95ea2256cd72cedda550d1dcb2f5c4`

## THR-WRH01_WAREHOUSE_HUM

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=55.0; WARN_LO=60.0; Nominal=75.0 ± 1.5; WARN_HI=85.0; CRIT_HI=90.0
- 조치/요구: Inspect and notify maintenance
- 센서: WRH01_WAREHOUSE_HUM
- 설비/제품 문맥: WRH01_WAREHOUSE
- KG actionTarget: 없음

> HUM

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 3, 열 1 · bbox [65.2, 185.87, 107.72, 203.87]  
인용 SHA-256: `c985ea35c7c867fdded4528ec701eb53de48ef7558a9d91218148a41e88a2e9b`

> %RH

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 3, 열 2 · bbox [107.72, 185.87, 141.73, 203.87]  
인용 SHA-256: `f52ab883875e9391646d21772e85a046e48eecd3331f981780605a9fc87f5912`

> 55.0

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 3, 열 3 · bbox [141.73, 185.87, 181.42, 203.87]  
인용 SHA-256: `40b2ddd4fee0a4778f262e809498e83d2b3345e6e104a2b2faa879e3f3be5884`

> 60.0

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 3, 열 4 · bbox [181.42, 185.87, 221.1, 203.87]  
인용 SHA-256: `db58b6c40698d7371bbcff35d085e1bac5fa439d0de31eb8e0da7c47d27cb2a7`

> 75.0 ± 1.5

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 3, 열 5 · bbox [221.1, 185.87, 289.13, 203.87]  
인용 SHA-256: `db517385fe11038c791d1721c1279bcd0e2304937aa32f49aa47743fc86eaf54`

> 85.0

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 3, 열 6 · bbox [289.13, 185.87, 328.82, 203.87]  
인용 SHA-256: `cce84368b6d089e0bd359d3167cd71d8d2f4fb7eb55018d07b2b8015f5651597`

> 90.0

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 3, 열 7 · bbox [328.82, 185.87, 368.5, 203.87]  
인용 SHA-256: `17e70b2fd0afd679e7d0c9741b940b06fff6bc980929f83ce4991be53b09dbbd`

> Inspect and notify maintenance

위치: SOP-002 p2 · SOP-002:p2:table2 · 행 3, 열 8 · bbox [368.5, 185.87, 530.08, 203.87]  
인용 SHA-256: `491fc2ec197ce42f4e2a47587ab17b63d73d614e4cd418eafb5424aa721687d3`

## THR-CHM01_CHEMICALSTORAGE_TMP

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=5.0; WARN_LO=10.0; Nominal=15.0 ± 0.3; WARN_HI=20.0; CRIT_HI=25.0
- 조치/요구: Activate emergency ventilation; notify safety officer immediately
- 센서: CHM01_CHEMICALSTORAGE_TMP
- 설비/제품 문맥: CHM01_CHEMICALSTORAGE
- KG actionTarget: 없음

> TMP

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 2, 열 1 · bbox [65.2, 276.87, 107.72, 304.87]  
인용 SHA-256: `e789e660565bca113731795aaedba3f8dd95cdef51c3e0e83a014529b4e4334d`

> °C

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 2, 열 2 · bbox [107.72, 276.87, 141.73, 304.87]  
인용 SHA-256: `11c4350690a30002a4e786d72aa960ec0ad75b34dfa4cfe144c78c449d5e918a`

> 5.0

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 2, 열 3 · bbox [141.73, 276.87, 181.42, 304.87]  
인용 SHA-256: `a19a1584344c1f3783bff51524a5a4b86f2cc09356c9dbfb6af9cd236e314362`

> 10.0

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 2, 열 4 · bbox [181.42, 276.87, 221.1, 304.87]  
인용 SHA-256: `f1e42019aecc858ffbcca7fddec511b761b474916fde37b1a6ff321a9b459330`

> 15.0 ± 0.3

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 2, 열 5 · bbox [221.1, 276.87, 289.13, 304.87]  
인용 SHA-256: `9a172300bebd0195f17e335b9b9b107aec7f86240f0c9ae70b36aa0233ecf15b`

> 20.0

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 2, 열 6 · bbox [289.13, 276.87, 328.82, 304.87]  
인용 SHA-256: `585348dbd28810f9a34f57be46f000c5f9effab894d074713d93fe7ccfeb3b76`

> 25.0

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 2, 열 7 · bbox [328.82, 276.87, 368.5, 304.87]  
인용 SHA-256: `00c10b58d5c431fee46080cd1ce96bf2fd15a683255e9fc30ee0f672dad91424`

> Activate emergency ventilation; notify safety officer immediately

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 2, 열 8 · bbox [368.5, 276.87, 530.08, 304.87]  
인용 SHA-256: `f5713680c7147a4b298c01454416598a77cbc97c768fe3cab8a23d0dbf48b043`

## THR-CHM01_CHEMICALSTORAGE_HUM

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=15.0; WARN_LO=20.0; Nominal=35.0 ± 1.0; WARN_HI=50.0; CRIT_HI=60.0
- 조치/요구: Activate desiccant system; inspect storage containers for leaks
- 센서: CHM01_CHEMICALSTORAGE_HUM
- 설비/제품 문맥: CHM01_CHEMICALSTORAGE
- KG actionTarget: 없음

> HUM

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 3, 열 1 · bbox [65.2, 304.87, 107.72, 332.87]  
인용 SHA-256: `c985ea35c7c867fdded4528ec701eb53de48ef7558a9d91218148a41e88a2e9b`

> %RH

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 3, 열 2 · bbox [107.72, 304.87, 141.73, 332.87]  
인용 SHA-256: `f52ab883875e9391646d21772e85a046e48eecd3331f981780605a9fc87f5912`

> 15.0

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 3, 열 3 · bbox [141.73, 304.87, 181.42, 332.87]  
인용 SHA-256: `c72ae9676454d7cc0014583a9d0a2e28553d5c62f087c7562b5307ebd1cc84c8`

> 20.0

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 3, 열 4 · bbox [181.42, 304.87, 221.1, 332.87]  
인용 SHA-256: `585348dbd28810f9a34f57be46f000c5f9effab894d074713d93fe7ccfeb3b76`

> 35.0 ± 1.0

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 3, 열 5 · bbox [221.1, 304.87, 289.13, 332.87]  
인용 SHA-256: `0d5fb563d2445fd3f4488aaad83e459f7cb753e334bdeedb12d08ec2ec6ca6a6`

> 50.0

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 3, 열 6 · bbox [289.13, 304.87, 328.82, 332.87]  
인용 SHA-256: `f97a13577367c1d604d37c4d2b6242d7193c7ba04aa4d1a64c322b23b2f9bd2a`

> 60.0

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 3, 열 7 · bbox [328.82, 304.87, 368.5, 332.87]  
인용 SHA-256: `db58b6c40698d7371bbcff35d085e1bac5fa439d0de31eb8e0da7c47d27cb2a7`

> Activate desiccant system; inspect storage containers for leaks

위치: SOP-002 p2 · SOP-002:p2:table3 · 행 3, 열 8 · bbox [368.5, 304.87, 530.08, 332.87]  
인용 SHA-256: `a454f896ac76fe7f65920bbe14da80be26c907806430e8dfd431ea0da7fbe5ad`

## THR-RND01_RDLAB_TMP

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=15.0; WARN_LO=18.0; Nominal=22.0 ± 0.2; WARN_HI=26.0; CRIT_HI=30.0
- 조치/요구: Inspect and notify maintenance
- 센서: RND01_RDLAB_TMP
- 설비/제품 문맥: RND01_RDLAB
- KG actionTarget: 없음

> TMP

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 2, 열 1 · bbox [65.2, 405.87, 107.72, 423.87]  
인용 SHA-256: `e789e660565bca113731795aaedba3f8dd95cdef51c3e0e83a014529b4e4334d`

> °C

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 2, 열 2 · bbox [107.72, 405.87, 141.73, 423.87]  
인용 SHA-256: `11c4350690a30002a4e786d72aa960ec0ad75b34dfa4cfe144c78c449d5e918a`

> 15.0

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 2, 열 3 · bbox [141.73, 405.87, 181.42, 423.87]  
인용 SHA-256: `c72ae9676454d7cc0014583a9d0a2e28553d5c62f087c7562b5307ebd1cc84c8`

> 18.0

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 2, 열 4 · bbox [181.42, 405.87, 221.1, 423.87]  
인용 SHA-256: `566afbb607a8f17b7cdf2d7f1632a2a810c06b128e8b81b6c6a8780eb9955dd1`

> 22.0 ± 0.2

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 2, 열 5 · bbox [221.1, 405.87, 289.13, 423.87]  
인용 SHA-256: `0f09c9d8f31a7e401ff4abbf8bc8110eb71ffe3fc98cea7e573316a48b99c5cd`

> 26.0

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 2, 열 6 · bbox [289.13, 405.87, 328.82, 423.87]  
인용 SHA-256: `80a753d4a473696b282e7cb81174a543a0973254e831f8c93e83a218f6045543`

> 30.0

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 2, 열 7 · bbox [328.82, 405.87, 368.5, 423.87]  
인용 SHA-256: `26c9a96ce053a14dd88a71a4830c9cbed7e1fed7e3f3f8a0b0b6a58f3f0f02e6`

> Inspect and notify maintenance

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 2, 열 8 · bbox [368.5, 405.87, 530.08, 423.87]  
인용 SHA-256: `491fc2ec197ce42f4e2a47587ab17b63d73d614e4cd418eafb5424aa721687d3`

## THR-RND01_RDLAB_HUM

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=25.0; WARN_LO=35.0; Nominal=50.0 ± 1.0; WARN_HI=65.0; CRIT_HI=75.0
- 조치/요구: Suspend experiments; inspect HVAC system
- 센서: RND01_RDLAB_HUM
- 설비/제품 문맥: RND01_RDLAB
- KG actionTarget: 없음

> HUM

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 3, 열 1 · bbox [65.2, 423.87, 107.72, 451.87]  
인용 SHA-256: `c985ea35c7c867fdded4528ec701eb53de48ef7558a9d91218148a41e88a2e9b`

> %RH

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 3, 열 2 · bbox [107.72, 423.87, 141.73, 451.87]  
인용 SHA-256: `f52ab883875e9391646d21772e85a046e48eecd3331f981780605a9fc87f5912`

> 25.0

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 3, 열 3 · bbox [141.73, 423.87, 181.42, 451.87]  
인용 SHA-256: `00c10b58d5c431fee46080cd1ce96bf2fd15a683255e9fc30ee0f672dad91424`

> 35.0

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 3, 열 4 · bbox [181.42, 423.87, 221.1, 451.87]  
인용 SHA-256: `72e72b41e40336eeef6045c40e3ac2988411fbadc42958caf30e7dbf1b729e00`

> 50.0 ± 1.0

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 3, 열 5 · bbox [221.1, 423.87, 289.13, 451.87]  
인용 SHA-256: `76b031d7f8ee235198884c5ff50f2eff0b78951a13f3cc4e25ccae6c7741397d`

> 65.0

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 3, 열 6 · bbox [289.13, 423.87, 328.82, 451.87]  
인용 SHA-256: `257a85d35ed6a007b8d472e3fcb23f955e0387751bf71c468065ab7a3ee129cd`

> 75.0

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 3, 열 7 · bbox [328.82, 423.87, 368.5, 451.87]  
인용 SHA-256: `dc371291bd7ac8a21624e3efa75d0a882d2d8d5a8a66befac962c2d1721076af`

> Suspend experiments; inspect HVAC system

위치: SOP-002 p2 · SOP-002:p2:table4 · 행 3, 열 8 · bbox [368.5, 423.87, 530.08, 451.87]  
인용 SHA-256: `ea8acfb0359eb97accaba24436760ab823ddcf7d291d92bb50d4f4478b45c7ea`

## THR-CAF01_CAFETERIA_TMP

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=14.0; WARN_LO=17.0; Nominal=21.0 ± 0.4; WARN_HI=26.0; CRIT_HI=30.0
- 조치/요구: Inspect and notify maintenance
- 센서: CAF01_CAFETERIA_TMP
- 설비/제품 문맥: CAF01_CAFETERIA
- KG actionTarget: 없음

> TMP

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 2, 열 1 · bbox [65.2, 524.87, 107.72, 542.87]  
인용 SHA-256: `e789e660565bca113731795aaedba3f8dd95cdef51c3e0e83a014529b4e4334d`

> °C

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 2, 열 2 · bbox [107.72, 524.87, 141.73, 542.87]  
인용 SHA-256: `11c4350690a30002a4e786d72aa960ec0ad75b34dfa4cfe144c78c449d5e918a`

> 14.0

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 2, 열 3 · bbox [141.73, 524.87, 181.42, 542.87]  
인용 SHA-256: `65cebb6f370f68502d4af051143fcd0def5afa569cf0176964bdf95bdf1ce5f1`

> 17.0

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 2, 열 4 · bbox [181.42, 524.87, 221.1, 542.87]  
인용 SHA-256: `2b7120854845b6c57c51713a6f7a1efa9f7577a9dc84c00e2224b505a8eddae7`

> 21.0 ± 0.4

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 2, 열 5 · bbox [221.1, 524.87, 289.13, 542.87]  
인용 SHA-256: `baaaf6dca8f691662a27cbc443b4d9d5511d0825401241d046743faa93c434e5`

> 26.0

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 2, 열 6 · bbox [289.13, 524.87, 328.82, 542.87]  
인용 SHA-256: `80a753d4a473696b282e7cb81174a543a0973254e831f8c93e83a218f6045543`

> 30.0

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 2, 열 7 · bbox [328.82, 524.87, 368.5, 542.87]  
인용 SHA-256: `26c9a96ce053a14dd88a71a4830c9cbed7e1fed7e3f3f8a0b0b6a58f3f0f02e6`

> Inspect and notify maintenance

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 2, 열 8 · bbox [368.5, 524.87, 530.08, 542.87]  
인용 SHA-256: `491fc2ec197ce42f4e2a47587ab17b63d73d614e4cd418eafb5424aa721687d3`

## THR-CAF01_CAFETERIA_HUM

- 문서/분류: SOP-002 / ThresholdRule
- 조건: CRIT_LO=25.0; WARN_LO=35.0; Nominal=55.0 ± 1.5; WARN_HI=70.0; CRIT_HI=80.0
- 조치/요구: Inspect and notify maintenance
- 센서: CAF01_CAFETERIA_HUM
- 설비/제품 문맥: CAF01_CAFETERIA
- KG actionTarget: 없음

> HUM

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 3, 열 1 · bbox [65.2, 542.87, 107.72, 560.87]  
인용 SHA-256: `c985ea35c7c867fdded4528ec701eb53de48ef7558a9d91218148a41e88a2e9b`

> %RH

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 3, 열 2 · bbox [107.72, 542.87, 141.73, 560.87]  
인용 SHA-256: `f52ab883875e9391646d21772e85a046e48eecd3331f981780605a9fc87f5912`

> 25.0

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 3, 열 3 · bbox [141.73, 542.87, 181.42, 560.87]  
인용 SHA-256: `00c10b58d5c431fee46080cd1ce96bf2fd15a683255e9fc30ee0f672dad91424`

> 35.0

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 3, 열 4 · bbox [181.42, 542.87, 221.1, 560.87]  
인용 SHA-256: `72e72b41e40336eeef6045c40e3ac2988411fbadc42958caf30e7dbf1b729e00`

> 55.0 ± 1.5

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 3, 열 5 · bbox [221.1, 542.87, 289.13, 560.87]  
인용 SHA-256: `89fb57944c73d155beedd5525381995208bf806fd5367749b69e5003f40db98b`

> 70.0

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 3, 열 6 · bbox [289.13, 542.87, 328.82, 560.87]  
인용 SHA-256: `2e12c864ec5ae8d3f0e2921625d48a7ef0adf5b5ba4eeb561cf409fc11c888f6`

> 80.0

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 3, 열 7 · bbox [328.82, 542.87, 368.5, 560.87]  
인용 SHA-256: `5afc581cc9ea399a2b1fa46aef3df4bea99fdbcf96285152389d9b581f8969fa`

> Inspect and notify maintenance

위치: SOP-002 p2 · SOP-002:p2:table5 · 행 3, 열 8 · bbox [368.5, 542.87, 530.08, 560.87]  
인용 SHA-256: `491fc2ec197ce42f4e2a47587ab17b63d73d614e4cd418eafb5424aa721687d3`

## ANOMALY-SPIKE

- 문서/분류: SOP-002 / ThresholdRule
- 조건: Transient deviation >3σ, <5 min; Single reading >CRIT
- 조치/요구: 명시 없음
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> SPIKE

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 2, 열 1 · bbox [77.95, 623.87, 148.82, 651.87]  
인용 SHA-256: `43df17d50abbf94a75bd7c1dbe728d96697cf5234c47229a7ab1f76bb1c8aadb`

> Transient deviation >3σ, <5 min

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 2, 열 2 · bbox [148.82, 623.87, 262.2, 651.87]  
인용 SHA-256: `57a18742bab7ffd0359954941e6e40c94b243c466aab83c10f841c54466fe617`

> Single reading >CRIT

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 2, 열 3 · bbox [262.2, 623.87, 375.59, 651.87]  
인용 SHA-256: `eb8fba6751f150fd56ddb57b9731c3e3b41436274e9cee6aac2f7083de8f3ec0`

> AnomalyEvent::Spike

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 2, 열 4 · bbox [375.59, 623.87, 517.32, 651.87]  
인용 SHA-256: `4088c1e1b3ef3b63e2ce53e93e71883a39f82d79809ce4b437a3fd36bbc701de`

## ANOMALY-DRIFT

- 문서/분류: SOP-002 / ThresholdRule
- 조건: Monotonic deviation >15 min; Slope >0.1σ/min for 5+ readings
- 조치/요구: 명시 없음
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> DRIFT

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 3, 열 1 · bbox [77.95, 651.87, 148.82, 679.87]  
인용 SHA-256: `3470efc4572c7bdb43604ac2c8833bc4df2736c720497834db3e9bceb1bcabb7`

> Monotonic deviation >15 min

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 3, 열 2 · bbox [148.82, 651.87, 262.2, 679.87]  
인용 SHA-256: `2fdb00269268bb5b99074ddd516a4cb6abb2ec1a226431bed7cca7ec94507578`

> Slope >0.1σ/min for 5+ readings

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 3, 열 3 · bbox [262.2, 651.87, 375.59, 679.87]  
인용 SHA-256: `b32ea2d096c37792152edce7da0be114420e94513f142998438144120d9285e0`

> AnomalyEvent::Drift

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 3, 열 4 · bbox [375.59, 651.87, 517.32, 679.87]  
인용 SHA-256: `e63027c19c090723d08bf0fa184421e22a28c31c5a41884dfedd0801ca0a883e`

## ANOMALY-STUCK

- 문서/분류: SOP-002 / ThresholdRule
- 조건: Unchanged >10 consecutive readings; std(last 10)<0.001×nominal
- 조치/요구: 명시 없음
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> STUCK

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 4, 열 1 · bbox [77.95, 679.87, 148.82, 707.87]  
인용 SHA-256: `15c04b2f5d12985f52800ffd450e9a9f5cfbb76b34b5549ff6a66f1a75119605`

> Unchanged >10 consecutive readings

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 4, 열 2 · bbox [148.82, 679.87, 262.2, 707.87]  
인용 SHA-256: `dd96111f7d2467fe7a8dee0571e50b0e330472b26560b33c88c6d609feb46785`

> std(last 10)<0.001×nominal

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 4, 열 3 · bbox [262.2, 679.87, 375.59, 707.87]  
인용 SHA-256: `131cab16149c672062394476aa909effcdd9d05362eeae911c21ce77b6025baa`

> AnomalyEvent::StuckSensor

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 4, 열 4 · bbox [375.59, 679.87, 517.32, 707.87]  
인용 SHA-256: `8725e5cf75ed9103c67f4e6d033f34bcc523bf5d1367b730c3aa120aa5ee0970`

## ANOMALY-OUT_OF_RANGE

- 문서/분류: SOP-002 / ThresholdRule
- 조건: Sustained WARN violation >10 min; >WARN for 20+ readings
- 조치/요구: 명시 없음
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> OUT_OF_RANGE

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 5, 열 1 · bbox [77.95, 707.87, 148.82, 735.87]  
인용 SHA-256: `2803a01f14ed3257754758efddbbd544f03aea9b4fb78dd40f6ecfb281e8557d`

> Sustained WARN violation >10 min

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 5, 열 2 · bbox [148.82, 707.87, 262.2, 735.87]  
인용 SHA-256: `08e5127cc5306a9874d933adeb6221264c24d3d281451013d6d16ab80ff2e7bf`

> >WARN for 20+ readings

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 5, 열 3 · bbox [262.2, 707.87, 375.59, 735.87]  
인용 SHA-256: `0182562ee67503231c915c677cbf6e49b039211a6c61d97009b43a5dad12f018`

> AnomalyEvent::OutOfRange

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 5, 열 4 · bbox [375.59, 707.87, 517.32, 735.87]  
인용 SHA-256: `95b9d63957fb7be1db87feb7021377aa774a95caee1b62c14f620df913dc1ac3`

## ANOMALY-CORRELATED

- 문서/분류: SOP-002 / ThresholdRule
- 조건: Causally linked to another station; Onset within 90 min of cause
- 조치/요구: 명시 없음
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> CORRELATED

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 6, 열 1 · bbox [77.95, 735.87, 148.82, 763.87]  
인용 SHA-256: `137234439948edd00c99a3a3f77d7a49735deb1142cbd1f04c7cb0d65c2a7592`

> Causally linked to another station

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 6, 열 2 · bbox [148.82, 735.87, 262.2, 763.87]  
인용 SHA-256: `76e85c063d3097e01d1add2c407dfbb911287df64b6094ce64d10e13c9a493c7`

> Onset within 90 min of cause

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 6, 열 3 · bbox [262.2, 735.87, 375.59, 763.87]  
인용 SHA-256: `28cd5a5d63d6f7e46072db334c70a59c4f5fe887fa6c0da3b2f6cc80db3abe16`

> AnomalyEvent::Correlated

위치: SOP-002 p2 · SOP-002:p2:table6 · 행 6, 열 4 · bbox [375.59, 735.87, 517.32, 763.87]  
인용 SHA-256: `d055be0c286dd10af344c380d22b0a58a3c554304298a9238faefc40947e5c4b`

## MAINT-01

- 문서/분류: SOP-003 / MaintenanceRule
- 조건: VIB DRIFT >0.05 mm/s over 60 min
- 조치/요구: Inspect and lubricate bearing
- 센서: ST04_PACKAGING_VIB
- 설비/제품 문맥: ST04_PACKAGING
- KG actionTarget: ST04_PACKAGING

> MAINT-01

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 2, 열 1 · bbox [77.95, 208.87, 134.65, 236.87]  
인용 SHA-256: `d7bb51de68be4e525d399ecbab7053286d646e6b512bd273c2d499502948aea4`

> VIB

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 2, 열 2 · bbox [134.65, 208.87, 168.66, 236.87]  
인용 SHA-256: `ff1264aaa35d2e0c29c7e25e1d06e6d64f64dd98ef1f6894105bc6cd0cf3f0c4`

> ST04_PACKAGING

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 2, 열 3 · bbox [168.66, 208.87, 259.37, 236.87]  
인용 SHA-256: `9af77621a2b8c5b7fa1078e2a31f3cbd5551f6eb8ebeda2bd338f178bf40f534`

> VIB DRIFT >0.05 mm/s over 60 min

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 2, 열 4 · bbox [259.37, 208.87, 367.09, 236.87]  
인용 SHA-256: `10d96388af6d34c71cda7eb1e4c86e103374243f466fa38ec656b96be27d2031`

> Inspect and lubricate bearing

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 2, 열 5 · bbox [367.09, 208.87, 466.3, 236.87]  
인용 SHA-256: `69224e26711ee3dd14e3ecc431a1e98073bb2b1224313d32a3178bf5b4b3cb33`

> HIGH

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 2, 열 6 · bbox [466.3, 208.87, 517.32, 236.87]  
인용 SHA-256: `b43e72eed0488d784f1e3092b48320e2355e9d6313f7ac401542018eec20d8a3`

## MAINT-02

- 문서/분류: SOP-003 / MaintenanceRule
- 조건: CUR DRIFT >1.0 A for 30+ min
- 조치/요구: Inspect sealing jaw
- 센서: ST02_SEALING_CUR
- 설비/제품 문맥: ST02_SEALING
- KG actionTarget: ST02_SEALING

> MAINT-02

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 3, 열 1 · bbox [77.95, 236.87, 134.65, 264.87]  
인용 SHA-256: `31d04fdf1027d962170501147bf87b540e1c9c0c8c08823b6809d370152e9a0f`

> CUR

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 3, 열 2 · bbox [134.65, 236.87, 168.66, 264.87]  
인용 SHA-256: `66d2af90645aa5197e4541bb208343e3ddcce962b02697e59014e3d93ea721f8`

> ST02_SEALING

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 3, 열 3 · bbox [168.66, 236.87, 259.37, 264.87]  
인용 SHA-256: `4a3fc980a6331199de6d5019036281c5f0cc773901ea7b76d7a75ec8377357af`

> CUR DRIFT >1.0 A for 30+ min

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 3, 열 4 · bbox [259.37, 236.87, 367.09, 264.87]  
인용 SHA-256: `da5f32c5279fb01fadb4155f57714bdae2ed63bf03a2a84f440f034dbb6358e4`

> Inspect sealing jaw

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 3, 열 5 · bbox [367.09, 236.87, 466.3, 264.87]  
인용 SHA-256: `ce5f18acaae9024f2124ebe2126b559a488dfddd5f199dd844459eb005976106`

> HIGH

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 3, 열 6 · bbox [466.3, 236.87, 517.32, 264.87]  
인용 SHA-256: `b43e72eed0488d784f1e3092b48320e2355e9d6313f7ac401542018eec20d8a3`

## MAINT-03

- 문서/분류: SOP-003 / MaintenanceRule
- 조건: TEN STUCK >10 samples
- 조치/요구: Replace sensor
- 센서: ST03_LABELLING_TEN
- 설비/제품 문맥: ST03_LABELLING
- KG actionTarget: ST03_LABELLING

> MAINT-03

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 4, 열 1 · bbox [77.95, 264.87, 134.65, 282.87]  
인용 SHA-256: `a5c3d0cbf6dc3131d841b1f82f98b12bb461f3ea09c33b7e7ef5b98f90527d4d`

> TEN

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 4, 열 2 · bbox [134.65, 264.87, 168.66, 282.87]  
인용 SHA-256: `5a15b6c4e2f863171b809f269c66c5fa8abf9ffcac6f6ff79a83a26f1c59ee55`

> ST03_LABELLING

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 4, 열 3 · bbox [168.66, 264.87, 259.37, 282.87]  
인용 SHA-256: `c54424b214bcd7cfefa3e02d87393f4af03491ebe06dccfdf4303bb6bed7c9c2`

> TEN STUCK >10 samples

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 4, 열 4 · bbox [259.37, 264.87, 367.09, 282.87]  
인용 SHA-256: `980dbea3b836d8ffd1a9ba6b20453b380f0ba7534b92ca30d4d8d70c3b7820ec`

> Replace sensor

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 4, 열 5 · bbox [367.09, 264.87, 466.3, 282.87]  
인용 SHA-256: `9e54dd416ccb922206cad1aa237a48e0cfc4ae6fb3b48b955de04150c942b471`

> MEDIUM

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 4, 열 6 · bbox [466.3, 264.87, 517.32, 282.87]  
인용 SHA-256: `7c48dd672a68098c3a9dac57805004a146db39c8d60c81d091537ee9c4a76054`

## MAINT-04

- 문서/분류: SOP-003 / MaintenanceRule
- 조건: PRS <3.3 bar for >15 min
- 조치/요구: Inspect filter and pump
- 센서: ST01_FILLING_PRS
- 설비/제품 문맥: ST01_FILLING
- KG actionTarget: ST01_FILLING

> MAINT-04

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 5, 열 1 · bbox [77.95, 282.87, 134.65, 300.87]  
인용 SHA-256: `f84572a974666157feb4c687b9c336348da645d466eb508146056303dd6f1cbd`

> PRS

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 5, 열 2 · bbox [134.65, 282.87, 168.66, 300.87]  
인용 SHA-256: `b5c84667baa4d9be1c7b42d7d7579fb93702f9b47a5d556dcd5de48d83da26e0`

> ST01_FILLING

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 5, 열 3 · bbox [168.66, 282.87, 259.37, 300.87]  
인용 SHA-256: `c75f7d0bbffa5bb05eb1a9b3746389def654a758c16b2f2f25c97799daf0e671`

> PRS <3.3 bar for >15 min

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 5, 열 4 · bbox [259.37, 282.87, 367.09, 300.87]  
인용 SHA-256: `9b13e55a81114a5d7e884553d5f2fff328f878bfade6412c1cca7268e679bfa3`

> Inspect filter and pump

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 5, 열 5 · bbox [367.09, 282.87, 466.3, 300.87]  
인용 SHA-256: `8802df289af5e11d18d65a17587bb03206c056e154353150540e21d6d94943fa`

> MEDIUM

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 5, 열 6 · bbox [466.3, 282.87, 517.32, 300.87]  
인용 SHA-256: `7c48dd672a68098c3a9dac57805004a146db39c8d60c81d091537ee9c4a76054`

## MAINT-05

- 문서/분류: SOP-003 / MaintenanceRule
- 조건: TMP >25°C for >5 min
- 조치/요구: Activate secondary cooling
- 센서: SRV01_SERVERROOM_TMP
- 설비/제품 문맥: SRV01_SERVERROOM
- KG actionTarget: SRV01_SERVERROOM

> MAINT-05

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 6, 열 1 · bbox [77.95, 300.87, 134.65, 328.87]  
인용 SHA-256: `b0cbba0fa38d380f88df5e9eb38936910b63fd0c008fbe154c5884ce707b12ad`

> TMP

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 6, 열 2 · bbox [134.65, 300.87, 168.66, 328.87]  
인용 SHA-256: `e789e660565bca113731795aaedba3f8dd95cdef51c3e0e83a014529b4e4334d`

> SRV01_SERVERROOM

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 6, 열 3 · bbox [168.66, 300.87, 259.37, 328.87]  
인용 SHA-256: `963235c3b2778e0b96c130f1bc83166d1b72c5e889a99c804e3143ae0e920347`

> TMP >25°C for >5 min

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 6, 열 4 · bbox [259.37, 300.87, 367.09, 328.87]  
인용 SHA-256: `e36ad72bb548ee8488334c925c2f9a25874070fb1aea3d3be696e5718bd6ba80`

> Activate secondary cooling

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 6, 열 5 · bbox [367.09, 300.87, 466.3, 328.87]  
인용 SHA-256: `a63b97a9dea051e7ed122e801835c151d1293b0d1523247dca20dc520db35c6a`

> CRITICAL

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 6, 열 6 · bbox [466.3, 300.87, 517.32, 328.87]  
인용 SHA-256: `4457f2d1aa4f8d6e5abe4ec13ea047b2adefbc67e4d6505262697d30ec601b51`

## MAINT-06

- 문서/분류: SOP-003 / MaintenanceRule
- 조건: TMP DRIFT >2°C over 2 h
- 조치/요구: Inspect compressor; notify QC
- 센서: WRH01_WAREHOUSE_TMP
- 설비/제품 문맥: WRH01_WAREHOUSE
- KG actionTarget: WRH01_WAREHOUSE

> MAINT-06

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 7, 열 1 · bbox [77.95, 328.87, 134.65, 356.87]  
인용 SHA-256: `8d900af0c00d33af0e8a7c3604b13ee4a142f132fd97eff6be66920568eeecc6`

> TMP

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 7, 열 2 · bbox [134.65, 328.87, 168.66, 356.87]  
인용 SHA-256: `e789e660565bca113731795aaedba3f8dd95cdef51c3e0e83a014529b4e4334d`

> WRH01_WAREHOUSE

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 7, 열 3 · bbox [168.66, 328.87, 259.37, 356.87]  
인용 SHA-256: `5d8c975cf5631fbcaf626492daca8c909d2f5dc9618795ee121adfe88104c5e6`

> TMP DRIFT >2°C over 2 h

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 7, 열 4 · bbox [259.37, 328.87, 367.09, 356.87]  
인용 SHA-256: `2fe6348b38010e2cb07ee1bc3f4f54f17cc44195160f052992d1b165b9923b20`

> Inspect compressor; notify QC

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 7, 열 5 · bbox [367.09, 328.87, 466.3, 356.87]  
인용 SHA-256: `f3331a187582133f7c09f000f87f6e417e9213957b9902b0541754c540a81a28`

> CRITICAL

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 7, 열 6 · bbox [466.3, 328.87, 517.32, 356.87]  
인용 SHA-256: `4457f2d1aa4f8d6e5abe4ec13ea047b2adefbc67e4d6505262697d30ec601b51`

## MAINT-07

- 문서/분류: SOP-003 / MaintenanceRule
- 조건: TMP >20°C for >10 min
- 조치/요구: Emergency ventilation; notify safety officer
- 센서: CHM01_CHEMICALSTORAGE_TMP
- 설비/제품 문맥: CHM01_CHEMICALSTORAGE
- KG actionTarget: CHM01_CHEMICALSTORAGE

> MAINT-07

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 8, 열 1 · bbox [77.95, 356.87, 134.65, 384.87]  
인용 SHA-256: `bfe4e2359612a1204b19058c0258937f230cbd442e7696107316b5e9c321ebf6`

> TMP

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 8, 열 2 · bbox [134.65, 356.87, 168.66, 384.87]  
인용 SHA-256: `e789e660565bca113731795aaedba3f8dd95cdef51c3e0e83a014529b4e4334d`

> CHM01_CHEMICALSTORAGE

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 8, 열 3 · bbox [168.66, 356.87, 259.37, 384.87]  
인용 SHA-256: `2d457abf68aed2ed47e1b007241e7072794499ef91c5756cd5301367998f5314`

> TMP >20°C for >10 min

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 8, 열 4 · bbox [259.37, 356.87, 367.09, 384.87]  
인용 SHA-256: `c6b63ec0052d65e59b28e0252f38535eb2971337930df69acaeda711930b0013`

> Emergency ventilation; notify safety officer

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 8, 열 5 · bbox [367.09, 356.87, 466.3, 384.87]  
인용 SHA-256: `c3cff82b6290316dbf3a5b7fde9ae697a740910b208b6dffb3f6487420556de8`

> CRITICAL

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 8, 열 6 · bbox [466.3, 356.87, 517.32, 384.87]  
인용 SHA-256: `4457f2d1aa4f8d6e5abe4ec13ea047b2adefbc67e4d6505262697d30ec601b51`

## MAINT-08

- 문서/분류: SOP-003 / MaintenanceRule
- 조건: HUM DRIFT >10%RH over 60 min
- 조치/요구: Activate dehumidifier; check HVAC drain
- 센서: RND01_RDLAB_HUM
- 설비/제품 문맥: RND01_RDLAB
- KG actionTarget: RND01_RDLAB

> MAINT-08

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 9, 열 1 · bbox [77.95, 384.87, 134.65, 412.87]  
인용 SHA-256: `cfa884a78f252daafd6868704f621803c42972a77e87d4304959b03d0cb51850`

> HUM

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 9, 열 2 · bbox [134.65, 384.87, 168.66, 412.87]  
인용 SHA-256: `c985ea35c7c867fdded4528ec701eb53de48ef7558a9d91218148a41e88a2e9b`

> RND01_RDLAB

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 9, 열 3 · bbox [168.66, 384.87, 259.37, 412.87]  
인용 SHA-256: `b9115957c4b42ee2b78fbcc4d306a29fcfcbede90ad9f16d44e33ddb4f37c901`

> HUM DRIFT >10%RH over 60 min

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 9, 열 4 · bbox [259.37, 384.87, 367.09, 412.87]  
인용 SHA-256: `1e9ec4e53072d49330791ea1b565ce617152dfb9b5a5750816003ceb7b8d5094`

> Activate dehumidifier; check HVAC drain

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 9, 열 5 · bbox [367.09, 384.87, 466.3, 412.87]  
인용 SHA-256: `87da3ca9375765bca25ef784ca29c3b5ef23388ee07872bf579b48691ef92dc8`

> HIGH

위치: SOP-003 p1 · SOP-003:p1:table1 · 행 9, 열 6 · bbox [466.3, 384.87, 517.32, 412.87]  
인용 SHA-256: `b43e72eed0488d784f1e3092b48320e2355e9d6313f7ac401542018eec20d8a3`

## SOP-003-p1-RESOLUTION-1

- 문서/분류: SOP-003 / MaintenanceRule
- 조건: ST02_SEALING-CUR↑ → ST04_PACKAGING-SPD↓
- 조치/요구: 1.Verify ST02-CUR trend. 2.Inspect sealing jaw. 3.Reset ST04 speed setpoint.
- 센서: ST02_SEALING_CUR, ST04_PACKAGING_SPD
- 설비/제품 문맥: ST02_SEALING, ST04_PACKAGING
- KG actionTarget: ST02_SEALING, ST04_PACKAGING

> ST02_SEALING-CUR↑ → ST04_PACKAGING-SPD↓

위치: SOP-003 p1 · SOP-003:p1:table2 · 행 2, 열 1 · bbox [63.78, 479.87, 162.99, 517.87]  
인용 SHA-256: `4747d05e763ab3ed0c018526607f4c9279c89040cea6e6888843596613c48dec`

> Sealing motor overload

위치: SOP-003 p1 · SOP-003:p1:table2 · 행 2, 열 2 · bbox [162.99, 479.87, 248.03, 517.87]  
인용 SHA-256: `1c2ef0acd82f7dce258efdf759a247044876465d11ad78b644ddcb3f54d6ad4f`

> Conveyor speed drop via electrical coupling

위치: SOP-003 p1 · SOP-003:p1:table2 · 행 2, 열 3 · bbox [248.03, 479.87, 347.24, 517.87]  
인용 SHA-256: `0cf4f732e492fd0276b6a0895d66ba809204d9d0efe57bf9205e7355ce6f4cff`

> 1.Verify ST02-CUR trend. 2.Inspect sealing jaw. 3.Reset ST04 speed setpoint.

위치: SOP-003 p1 · SOP-003:p1:table2 · 행 2, 열 4 · bbox [347.24, 479.87, 531.5, 517.87]  
인용 SHA-256: `99c2db16a50e6d3541d5b7399922394ee2da784b5fa386073ca399d6c8243fd4`

## SOP-003-p1-RESOLUTION-2

- 문서/분류: SOP-003 / MaintenanceRule
- 조건: SRV01-TMP↑ → SCADA latency↑
- 조치/요구: 1.Reduce SRV01-TMP <25°C. 2.Verify PLC heartbeats. 3.Clear STUCK alarms.
- 센서: SRV01_SERVERROOM_TMP
- 설비/제품 문맥: SRV01_SERVERROOM
- KG actionTarget: SRV01_SERVERROOM

> SRV01-TMP↑ → SCADA latency↑

위치: SOP-003 p1 · SOP-003:p1:table2 · 행 3, 열 1 · bbox [63.78, 517.87, 162.99, 555.87]  
인용 SHA-256: `de6698073670d91660ac066cd2169410a2d7d756bd35d443b724d444b76fe3eb`

> Server Room overheating

위치: SOP-003 p1 · SOP-003:p1:table2 · 행 3, 열 2 · bbox [162.99, 517.87, 248.03, 555.87]  
인용 SHA-256: `fbe7aaab1eba564e4ef4e62c3e161f76230b975364ce68f75577c19622719191`

> Increased scan time → apparent STUCK readings

위치: SOP-003 p1 · SOP-003:p1:table2 · 행 3, 열 3 · bbox [248.03, 517.87, 347.24, 555.87]  
인용 SHA-256: `443d4d42456d4d2ee041136a1afc2585a82d76958b437d8a00d1b915376b7a1e`

> 1.Reduce SRV01-TMP <25°C. 2.Verify PLC heartbeats. 3.Clear STUCK alarms.

위치: SOP-003 p1 · SOP-003:p1:table2 · 행 3, 열 4 · bbox [347.24, 517.87, 531.5, 555.87]  
인용 SHA-256: `a59664ef8dbfeea4a4678edaad1ffe83e860a287c156b3787abcadf6ec6104d3`

## SOP-003-p1-RESOLUTION-3

- 문서/분류: SOP-003 / MaintenanceRule
- 조건: WRH01-TMP↑ → QC HOLD
- 조치/요구: 1.Restore WRH01-TMP <8°C. 2.Notify QC. 3.Place batch on HOLD in ERP.
- 센서: WRH01_WAREHOUSE_TMP
- 설비/제품 문맥: WRH01_WAREHOUSE
- KG actionTarget: WRH01_WAREHOUSE

> WRH01-TMP↑ → QC HOLD

위치: SOP-003 p1 · SOP-003:p1:table2 · 행 4, 열 1 · bbox [63.78, 555.87, 162.99, 583.87]  
인용 SHA-256: `aa577f9410f0252a40bffaf99ab9d7a230620a89b07343cd70081bdeaf95cbbd`

> Cold warehouse drift

위치: SOP-003 p1 · SOP-003:p1:table2 · 행 4, 열 2 · bbox [162.99, 555.87, 248.03, 583.87]  
인용 SHA-256: `ad1335d1170f3feeecf6988686bd54d546795eb7d30bdc7a47afff5b90813cd5`

> Product quality risk

위치: SOP-003 p1 · SOP-003:p1:table2 · 행 4, 열 3 · bbox [248.03, 555.87, 347.24, 583.87]  
인용 SHA-256: `2fcccfa5677f7a34042208efba53c89d5bb68b694036efab623ec37b044f3cc4`

> 1.Restore WRH01-TMP <8°C. 2.Notify QC. 3.Place batch on HOLD in ERP.

위치: SOP-003 p1 · SOP-003:p1:table2 · 행 4, 열 4 · bbox [347.24, 555.87, 531.5, 583.87]  
인용 SHA-256: `84af16e2edb9dba07431ae502937cf6357ad1e332726e0ce595d1794daff60e7`

## RULE-ACCESS-01

- 문서/분류: SOP-004 / AccessRule
- 조건: Any entry by an unauthorised role
- 조치/요구: MUST be logged as OccupancyEvent::UnauthorisedAccess with person_id, zone, and timestamp.
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> RULE-ACCESS-01: Any entry by an unauthorised role MUST be logged as OccupancyEvent::UnauthorisedAccess with person_id, zone, and timestamp.

위치: SOP-004 p1 · SOP-004:p1:RULE-ACCESS-01 · 문자 [1131, 1270)  
인용 SHA-256: `6fcd41e82c2a9182f6a07865f00b33cb6725b2ec6ed3695852b0021cf38c4698`

## RULE-ACCESS-02

- 문서/분류: SOP-004 / AccessRule
- 조건: detection
- 조치/요구: Security personnel MUST be notified within 2 minutes of detection.
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> RULE-ACCESS-02: Security personnel MUST be notified within 2 minutes of detection.

위치: SOP-004 p1 · SOP-004:p1:RULE-ACCESS-02 · 문자 [1271, 1353)  
인용 SHA-256: `db3401720ea688664d8387097e036cfb20f80fb49f2ff8aa3ab6c5f97abf353e`

## RULE-ACCESS-03

- 문서/분류: SOP-004 / AccessRule
- 조건: 명시 없음
- 조치/요구: The KG node MUST include authorized=NO and a reference to this rule.
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> RULE-ACCESS-03: The KG node MUST include authorized=NO and a reference to this rule.

위치: SOP-004 p1 · SOP-004:p1:RULE-ACCESS-03 · 문자 [1354, 1438)  
인용 SHA-256: `e1fa14bb61deb77464cf76a817acfd49106438996c92d365dfc5246cbaf9f861`

## RULE-ACCESS-04

- 문서/분류: SOP-004 / AccessRule
- 조건: Any UNAUTHORIZED_ACCESS
- 조치/요구: immediate escalation to the Safety Officer regardless of role.
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> RULE-ACCESS-04: Chemical Storage has zero-tolerance policy. Any UNAUTHORIZED_ACCESS triggers immediate escalation to the Safety Officer regardless of role.

위치: SOP-004 p2 · SOP-004:p2:RULE-ACCESS-04 · 문자 [0, 155)  
인용 SHA-256: `6c31c3dd2b099fbc27b40886fa082f2f6dedf78f9f48440c013f10cd262d617e`

## SOP-004-p1-AUTH-operator

- 문서/분류: SOP-004 / AccessRule
- 조건: Role=operator
- 조치/요구: Prod. Area=YES; Server Room=NO; Gen. Warehouse=YES; Main Entrance=YES; Chem. Storage=NO; R&D Lab=NO; Cafeteria=YES
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> operator

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 2, 열 1 · bbox [48.19, 186.87, 121.89, 204.87]  
인용 SHA-256: `06e55b633481f7bb072957eabcf110c972e86691c3cfedabe088024bffe42f23`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 2, 열 2 · bbox [121.89, 186.87, 178.58, 204.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> NO

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 2, 열 3 · bbox [178.58, 186.87, 240.94, 204.87]  
인용 SHA-256: `23794d91c53ae875c8e247d72561e35d9d06ee07c70c9e0dbcc977a6d161504a`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 2, 열 4 · bbox [240.94, 186.87, 311.81, 204.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 2, 열 5 · bbox [311.81, 186.87, 374.17, 204.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> NO

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 2, 열 6 · bbox [374.17, 186.87, 436.54, 204.87]  
인용 SHA-256: `23794d91c53ae875c8e247d72561e35d9d06ee07c70c9e0dbcc977a6d161504a`

> NO

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 2, 열 7 · bbox [436.54, 186.87, 490.39, 204.87]  
인용 SHA-256: `23794d91c53ae875c8e247d72561e35d9d06ee07c70c9e0dbcc977a6d161504a`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 2, 열 8 · bbox [490.39, 186.87, 547.09, 204.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

## SOP-004-p1-AUTH-technician

- 문서/분류: SOP-004 / AccessRule
- 조건: Role=technician
- 조치/요구: Prod. Area=YES; Server Room=YES; Gen. Warehouse=YES; Main Entrance=YES; Chem. Storage=YES; R&D Lab=YES; Cafeteria=YES
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> technician

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 3, 열 1 · bbox [48.19, 204.87, 121.89, 222.87]  
인용 SHA-256: `29ba9d9cef5a66461116a24938bb9307e005c35aa1bb909f16aa5e85bd767480`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 3, 열 2 · bbox [121.89, 204.87, 178.58, 222.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 3, 열 3 · bbox [178.58, 204.87, 240.94, 222.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 3, 열 4 · bbox [240.94, 204.87, 311.81, 222.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 3, 열 5 · bbox [311.81, 204.87, 374.17, 222.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 3, 열 6 · bbox [374.17, 204.87, 436.54, 222.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 3, 열 7 · bbox [436.54, 204.87, 490.39, 222.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 3, 열 8 · bbox [490.39, 204.87, 547.09, 222.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

## SOP-004-p1-AUTH-supervisor

- 문서/분류: SOP-004 / AccessRule
- 조건: Role=supervisor
- 조치/요구: Prod. Area=YES; Server Room=YES; Gen. Warehouse=YES; Main Entrance=YES; Chem. Storage=YES; R&D Lab=YES; Cafeteria=YES
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> supervisor

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 4, 열 1 · bbox [48.19, 222.87, 121.89, 240.87]  
인용 SHA-256: `0834c2d60725ac5902257b3b78dd161ad26d1c0290dbf1e47cc14add5b8c8142`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 4, 열 2 · bbox [121.89, 222.87, 178.58, 240.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 4, 열 3 · bbox [178.58, 222.87, 240.94, 240.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 4, 열 4 · bbox [240.94, 222.87, 311.81, 240.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 4, 열 5 · bbox [311.81, 222.87, 374.17, 240.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 4, 열 6 · bbox [374.17, 222.87, 436.54, 240.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 4, 열 7 · bbox [436.54, 222.87, 490.39, 240.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 4, 열 8 · bbox [490.39, 222.87, 547.09, 240.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

## SOP-004-p1-AUTH-manager

- 문서/분류: SOP-004 / AccessRule
- 조건: Role=manager
- 조치/요구: Prod. Area=YES; Server Room=YES; Gen. Warehouse=YES; Main Entrance=YES; Chem. Storage=YES; R&D Lab=YES; Cafeteria=YES
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> manager

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 5, 열 1 · bbox [48.19, 240.87, 121.89, 258.87]  
인용 SHA-256: `6ee4a469cd4e91053847f5d3fcb61dbcc91e8f0ef10be7748da4c4a1ba382d17`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 5, 열 2 · bbox [121.89, 240.87, 178.58, 258.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 5, 열 3 · bbox [178.58, 240.87, 240.94, 258.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 5, 열 4 · bbox [240.94, 240.87, 311.81, 258.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 5, 열 5 · bbox [311.81, 240.87, 374.17, 258.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 5, 열 6 · bbox [374.17, 240.87, 436.54, 258.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 5, 열 7 · bbox [436.54, 240.87, 490.39, 258.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 5, 열 8 · bbox [490.39, 240.87, 547.09, 258.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

## SOP-004-p1-AUTH-security

- 문서/분류: SOP-004 / AccessRule
- 조건: Role=security
- 조치/요구: Prod. Area=YES; Server Room=YES; Gen. Warehouse=YES; Main Entrance=YES; Chem. Storage=YES; R&D Lab=YES; Cafeteria=YES
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> security

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 6, 열 1 · bbox [48.19, 258.87, 121.89, 276.87]  
인용 SHA-256: `5d2d3ceb7abe552344276d47d36a8175b7aeb250a9bf0bf00e850cd23ecf2e43`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 6, 열 2 · bbox [121.89, 258.87, 178.58, 276.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 6, 열 3 · bbox [178.58, 258.87, 240.94, 276.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 6, 열 4 · bbox [240.94, 258.87, 311.81, 276.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 6, 열 5 · bbox [311.81, 258.87, 374.17, 276.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 6, 열 6 · bbox [374.17, 258.87, 436.54, 276.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 6, 열 7 · bbox [436.54, 258.87, 490.39, 276.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 6, 열 8 · bbox [490.39, 258.87, 547.09, 276.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

## SOP-004-p1-AUTH-visitor

- 문서/분류: SOP-004 / AccessRule
- 조건: Role=visitor
- 조치/요구: Prod. Area=YES; Server Room=NO; Gen. Warehouse=NO; Main Entrance=YES; Chem. Storage=NO; R&D Lab=NO; Cafeteria=YES
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> visitor

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 7, 열 1 · bbox [48.19, 276.87, 121.89, 294.87]  
인용 SHA-256: `5f14f9e6d80f802a65269804f2552ef9889f2c7ccec5067214e58a1e48e0b3ff`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 7, 열 2 · bbox [121.89, 276.87, 178.58, 294.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> NO

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 7, 열 3 · bbox [178.58, 276.87, 240.94, 294.87]  
인용 SHA-256: `23794d91c53ae875c8e247d72561e35d9d06ee07c70c9e0dbcc977a6d161504a`

> NO

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 7, 열 4 · bbox [240.94, 276.87, 311.81, 294.87]  
인용 SHA-256: `23794d91c53ae875c8e247d72561e35d9d06ee07c70c9e0dbcc977a6d161504a`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 7, 열 5 · bbox [311.81, 276.87, 374.17, 294.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

> NO

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 7, 열 6 · bbox [374.17, 276.87, 436.54, 294.87]  
인용 SHA-256: `23794d91c53ae875c8e247d72561e35d9d06ee07c70c9e0dbcc977a6d161504a`

> NO

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 7, 열 7 · bbox [436.54, 276.87, 490.39, 294.87]  
인용 SHA-256: `23794d91c53ae875c8e247d72561e35d9d06ee07c70c9e0dbcc977a6d161504a`

> YES

위치: SOP-004 p1 · SOP-004:p1:table1 · 행 7, 열 8 · bbox [490.39, 276.87, 547.09, 294.87]  
인용 SHA-256: `f9171164593756e56fb197327b529a4955590566560dbe62d586bff41be9d297`

## SOP-004-p1-OCCUPANCY-1

- 문서/분류: SOP-004 / AccessRule
- 조건: Production Area
- 조치/요구: Max Persons=12; WARNING above 10; CRITICAL above 12
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> Production Area

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 2, 열 1 · bbox [63.78, 361.87, 191.34, 379.87]  
인용 SHA-256: `3fb26fc452ef64564fdf9aae6ac5674b4ef09b5666ed5298237eed46bf5ea7ce`

> 12

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 2, 열 2 · bbox [191.34, 361.87, 262.2, 379.87]  
인용 SHA-256: `6b51d431df5d7f141cbececcf79edf3dd861c3b4069f0b11661a3eefacbba918`

> WARNING above 10; CRITICAL above 12

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 2, 열 3 · bbox [262.2, 361.87, 531.5, 379.87]  
인용 SHA-256: `482c60d4b1f246aed0220dd66d16f1eeef5cf785ad664b87f245d4043392f0d6`

## SOP-004-p1-OCCUPANCY-2

- 문서/분류: SOP-004 / AccessRule
- 조건: Server Room
- 조치/요구: Max Persons=2; CRITICAL above 2; access badge required
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> Server Room

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 3, 열 1 · bbox [63.78, 379.87, 191.34, 397.87]  
인용 SHA-256: `96788a33f6ec4bab14c1ff754874db7539d9a4d7c2e500a75925a3081af3a191`

> 2

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 3, 열 2 · bbox [191.34, 379.87, 262.2, 397.87]  
인용 SHA-256: `d4735e3a265e16eee03f59718b9b5d03019c07d8b6c51f90da3a666eec13ab35`

> CRITICAL above 2; access badge required

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 3, 열 3 · bbox [262.2, 379.87, 531.5, 397.87]  
인용 SHA-256: `afcfb9b2efcbe93c6182dcf3c1fb57d1c76442a60a4c18e6423e38908ccd485f`

## SOP-004-p1-OCCUPANCY-3

- 문서/분류: SOP-004 / AccessRule
- 조건: General Warehouse
- 조치/요구: Max Persons=4; WARNING above 3
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> General Warehouse

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 4, 열 1 · bbox [63.78, 397.87, 191.34, 415.87]  
인용 SHA-256: `06b7cf6bf8b63f3d3ee6994d172bcfd75824c9db87fe1f445ea140abd39ac5e0`

> 4

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 4, 열 2 · bbox [191.34, 397.87, 262.2, 415.87]  
인용 SHA-256: `4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a`

> WARNING above 3

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 4, 열 3 · bbox [262.2, 397.87, 531.5, 415.87]  
인용 SHA-256: `bc32c0f574abe4d4d8aaad8676edd0ea15cca17db7312e5050667c4c138a02a4`

## SOP-004-p1-OCCUPANCY-4

- 문서/분류: SOP-004 / AccessRule
- 조건: Main Entrance
- 조치/요구: Max Persons=8; Monitoring only
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> Main Entrance

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 5, 열 1 · bbox [63.78, 415.87, 191.34, 433.87]  
인용 SHA-256: `203974207a540808e90e1a70d624fd7a04dd0c94b301fd76d28ac7a8fddff9a5`

> 8

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 5, 열 2 · bbox [191.34, 415.87, 262.2, 433.87]  
인용 SHA-256: `2c624232cdd221771294dfbb310aca000a0df6ac8b66b696d90ef06fdefb64a3`

> Monitoring only

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 5, 열 3 · bbox [262.2, 415.87, 531.5, 433.87]  
인용 SHA-256: `904df09a97970bbf293118f1fc1c04c51a90247e44fabaa7c7df209639c8dd2a`

## SOP-004-p1-OCCUPANCY-5

- 문서/분류: SOP-004 / AccessRule
- 조건: Chemical Storage
- 조치/요구: Max Persons=4; CRITICAL above 4; hazmat training required — see RULE-CHM01-03
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> Chemical Storage

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 6, 열 1 · bbox [63.78, 433.87, 191.34, 451.87]  
인용 SHA-256: `0b476e5403eae6efd016cc212959202a8041958603e2b549c7eccd7b4750a725`

> 4

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 6, 열 2 · bbox [191.34, 433.87, 262.2, 451.87]  
인용 SHA-256: `4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a`

> CRITICAL above 4; hazmat training required — see RULE-CHM01-03

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 6, 열 3 · bbox [262.2, 433.87, 531.5, 451.87]  
인용 SHA-256: `2a348aa441e21f986bfb104f643d598533a0ea3dbadf674891bb9ba1a19f1c43`

## SOP-004-p1-OCCUPANCY-6

- 문서/분류: SOP-004 / AccessRule
- 조건: R&D Lab
- 조치/요구: Max Persons=6; WARNING above 5; precision experiments may be disturbed
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> R&D Lab

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 7, 열 1 · bbox [63.78, 451.87, 191.34, 469.87]  
인용 SHA-256: `c0cf8327ab2d0304cbf14d0675d3ca0a2df9de63cac58532bbad6d81b1e74d01`

> 6

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 7, 열 2 · bbox [191.34, 451.87, 262.2, 469.87]  
인용 SHA-256: `e7f6c011776e8db7cd330b54174fd76f7d0216b612387a5ffcfb81e6f0919683`

> WARNING above 5; precision experiments may be disturbed

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 7, 열 3 · bbox [262.2, 451.87, 531.5, 469.87]  
인용 SHA-256: `09a8502d39056344908d5942efa5aadb58d1ef373594badf719ffd285b1bda42`

## SOP-004-p1-OCCUPANCY-7

- 문서/분류: SOP-004 / AccessRule
- 조건: Cafeteria
- 조치/요구: Max Persons=20; Monitoring only — occupant comfort
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> Cafeteria

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 8, 열 1 · bbox [63.78, 469.87, 191.34, 487.87]  
인용 SHA-256: `d5fe60af2faabfe51607c62676ab4f4c8ebbc6530ff489618185be14fd1db892`

> 20

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 8, 열 2 · bbox [191.34, 469.87, 262.2, 487.87]  
인용 SHA-256: `f5ca38f748a1d6eaf726b8a42fb575c3c71f1864a8143301782de13da2d9202b`

> Monitoring only — occupant comfort

위치: SOP-004 p1 · SOP-004:p1:table2 · 행 8, 열 3 · bbox [262.2, 469.87, 531.5, 487.87]  
인용 SHA-256: `ec1175d7fb31f772e38df85ef2f3753a61a15f03a92180d5eeb71bfb1e28c306`

## SOP-004-p1-ACK-operator

- 문서/분류: SOP-004 / AccessRule
- 조건: Role=operator
- 조치/요구: Max Ack — WARNING (min)=15; Max Ack — CRITICAL (min)=3
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> operator

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 2, 열 1 · bbox [99.21, 554.87, 212.6, 572.87]  
인용 SHA-256: `06e55b633481f7bb072957eabcf110c972e86691c3cfedabe088024bffe42f23`

> 15

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 2, 열 2 · bbox [212.6, 554.87, 354.33, 572.87]  
인용 SHA-256: `e629fa6598d732768f7c726b4b621285f9c3b85303900aa912017db7617d8bdb`

> 3

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 2, 열 3 · bbox [354.33, 554.87, 496.06, 572.87]  
인용 SHA-256: `4e07408562bedb8b60ce05c1decfe3ad16b72230967de01f640b7e4729b49fce`

## SOP-004-p1-ACK-technician

- 문서/분류: SOP-004 / AccessRule
- 조건: Role=technician
- 조치/요구: Max Ack — WARNING (min)=10; Max Ack — CRITICAL (min)=2
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> technician

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 3, 열 1 · bbox [99.21, 572.87, 212.6, 590.87]  
인용 SHA-256: `29ba9d9cef5a66461116a24938bb9307e005c35aa1bb909f16aa5e85bd767480`

> 10

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 3, 열 2 · bbox [212.6, 572.87, 354.33, 590.87]  
인용 SHA-256: `4a44dc15364204a80fe80e9039455cc1608281820fe2b24f1e5233ade6af1dd5`

> 2

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 3, 열 3 · bbox [354.33, 572.87, 496.06, 590.87]  
인용 SHA-256: `d4735e3a265e16eee03f59718b9b5d03019c07d8b6c51f90da3a666eec13ab35`

## SOP-004-p1-ACK-supervisor

- 문서/분류: SOP-004 / AccessRule
- 조건: Role=supervisor
- 조치/요구: Max Ack — WARNING (min)=5; Max Ack — CRITICAL (min)=1
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> supervisor

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 4, 열 1 · bbox [99.21, 590.87, 212.6, 608.87]  
인용 SHA-256: `0834c2d60725ac5902257b3b78dd161ad26d1c0290dbf1e47cc14add5b8c8142`

> 5

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 4, 열 2 · bbox [212.6, 590.87, 354.33, 608.87]  
인용 SHA-256: `ef2d127de37b942baad06145e54b0c619a1f22327b2ebbcfbec78f5564afe39d`

> 1

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 4, 열 3 · bbox [354.33, 590.87, 496.06, 608.87]  
인용 SHA-256: `6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b`

## SOP-004-p1-ACK-manager

- 문서/분류: SOP-004 / AccessRule
- 조건: Role=manager
- 조치/요구: Max Ack — WARNING (min)=15; Max Ack — CRITICAL (min)=5
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> manager

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 5, 열 1 · bbox [99.21, 608.87, 212.6, 626.87]  
인용 SHA-256: `6ee4a469cd4e91053847f5d3fcb61dbcc91e8f0ef10be7748da4c4a1ba382d17`

> 15

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 5, 열 2 · bbox [212.6, 608.87, 354.33, 626.87]  
인용 SHA-256: `e629fa6598d732768f7c726b4b621285f9c3b85303900aa912017db7617d8bdb`

> 5

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 5, 열 3 · bbox [354.33, 608.87, 496.06, 626.87]  
인용 SHA-256: `ef2d127de37b942baad06145e54b0c619a1f22327b2ebbcfbec78f5564afe39d`

## SOP-004-p1-ACK-security

- 문서/분류: SOP-004 / AccessRule
- 조건: Role=security
- 조치/요구: Max Ack — WARNING (min)=20; Max Ack — CRITICAL (min)=5
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: 없음
- KG actionTarget: 없음

> security

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 6, 열 1 · bbox [99.21, 626.87, 212.6, 644.87]  
인용 SHA-256: `5d2d3ceb7abe552344276d47d36a8175b7aeb250a9bf0bf00e850cd23ecf2e43`

> 20

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 6, 열 2 · bbox [212.6, 626.87, 354.33, 644.87]  
인용 SHA-256: `f5ca38f748a1d6eaf726b8a42fb575c3c71f1864a8143301782de13da2d9202b`

> 5

위치: SOP-004 p1 · SOP-004:p1:table3 · 행 6, 열 3 · bbox [354.33, 626.87, 496.06, 644.87]  
인용 SHA-256: `ef2d127de37b942baad06145e54b0c619a1f22327b2ebbcfbec78f5564afe39d`

## DS-ELEC-3300-p1-OVERLOAD

- 문서/분류: DS-ELEC-3300 / OperationalRule
- 조건: Operation between 14 A and 20 A
- 조치/요구: permissible for short durations (< 60 seconds).
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: Series 3300
- KG actionTarget: 없음

> Note 2 — Continuous Overload Rating: The sensor is rated for continuous operation up to 14 A. Operation between 14 A and 20 A is permissible for short durations (< 60 seconds). Sustained operation above 14 A will cause progressive accuracy drift. ElectroMeasure recommends that process alarm thresholds triggering corrective action be set no higher than the continuous overload rating.

위치: DS-ELEC-3300 p1 · DS-ELEC-3300:p1:text2 · 문자 [433, 818)  
인용 SHA-256: `915f07185029b7769f8b9493e1b91e9013bf8ae900d48f0f78e46d6f8d367350`

## DS-ELEC-3300-p1-ALARM

- 문서/분류: DS-ELEC-3300 / ThresholdRule
- 조건: 명시 없음
- 조치/요구: ElectroMeasure recommends that process alarm thresholds triggering corrective action be set no higher than the continuous overload rating.
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: Series 3300
- KG actionTarget: 없음

> Note 2 — Continuous Overload Rating: The sensor is rated for continuous operation up to 14 A. Operation between 14 A and 20 A is permissible for short durations (< 60 seconds). Sustained operation above 14 A will cause progressive accuracy drift. ElectroMeasure recommends that process alarm thresholds triggering corrective action be set no higher than the continuous overload rating.

위치: DS-ELEC-3300 p1 · DS-ELEC-3300:p1:text2 · 문자 [433, 818)  
인용 SHA-256: `915f07185029b7769f8b9493e1b91e9013bf8ae900d48f0f78e46d6f8d367350`

## DS-MECH-4400-p1-ALARM

- 문서/분류: DS-MECH-4400 / ThresholdRule
- 조건: 명시 없음
- 조치/요구: Application Note — Alarm Threshold Setting: With a total accuracy of ±0.10 bar, alarm thresholds should be set at least 5× the accuracy (0.50 bar) from the nominal operating point to avoid nuisance alarms. Thresholds closer than 3× accuracy (0.30 bar) are not recommended for process control.
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: PRS-4410
- KG actionTarget: 없음

> Application Note — Alarm Threshold Setting: With a total accuracy of ±0.10 bar, alarm thresholds should be set at least 5× the accuracy (0.50 bar) from the nominal operating point to avoid nuisance alarms. Thresholds closer than 3× accuracy (0.30 bar) are not recommended for process control. 2. Electromagnetic Flowmeter FLW-4450

위치: DS-MECH-4400 p1 · DS-MECH-4400:p1:text2 · 문자 [382, 712)  
인용 SHA-256: `23bb969952d3286f9c15dde46231228754b5abd1eb5859877a93cf394fec8969`

## DS-THERM-2200-p1-SUSTAINED

- 문서/분류: DS-THERM-2200 / OperationalRule
- 조건: applications requiring sustained operation above 200°C
- 조치/요구: ThermoSense recommends the Series 2400 (Pt100 RTD, rated to 250°C continuous).
- 센서: 명시적 설치 연결 없음
- 설비/제품 문맥: TMP-2210, Series 2400
- KG actionTarget: 없음

> Note 1 — Maximum Operating Temperature: The rated maximum for continuous operation is 200°C. Exposure above this value accelerates thermocouple ageing and may cause drift of up to ±5°C within 500 hours. For applications requiring sustained operation above 200°C, ThermoSense recommends the Series 2400 (Pt100 RTD, rated to 250°C continuous). 2. Humidity Sensor HUM-2250 — Specifications

위치: DS-THERM-2200 p1 · DS-THERM-2200:p1:text2 · 문자 [471, 857)  
인용 SHA-256: `638568c3df566c234058af4fa2e217a889d7112847c417391bce631652c98193`

