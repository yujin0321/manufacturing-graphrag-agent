# 센서 임계값 대조표: seed nodes.csv Sensor 행 vs SOP-002 표(ThresholdRule) vs 전처리 임계값 파일

생성: `imaks_kg.kg.promote_rules` (직접 고치지 말 것). KG의 ThresholdRule 값은 SOP-002 표에서 왔다. seed와 임계값 파일은 대조만 하고 KG에 넣지 않는다. 다른 값은 셋 다 적고 통일하지 않는다.

- 비교는 수치(Decimal) 기준이다. 수치는 같고 표기만 다르면(예: 120 vs 120.0) '같음(표기 다름)'으로 적는다.
- 칸 표기: 셋이 같으면 값 하나, 다르면 `seed=… / SOP-002=… / csv=…`.
- Nominal 옆 '±' 허용오차는 온톨로지에 속성이 없어 KG 속성으로 만들지 않았다(원문은 Provenance sourceQuote와 해시로 남음). 참고로 아래 표에 적는다.

| 센서 | ThresholdRule identifier | SOP-002 위치 | 단위 | nominalValue | warnLo | warnHi | critLo | critHi | ± 허용오차(원문, KG 미반영) | 판정 |
|---|---|---|---|---|---|---|---|---|---|---|
| CAF01_CAFETERIA_HUM | SOP-002:THR:CAF01_CAFETERIA_HUM | SOP-002:p2:table5 행 3 | %RH | 55.0 | 35.0 | 70.0 | 25.0 | 80.0 | 1.5 | 같음 |
| CAF01_CAFETERIA_TMP | SOP-002:THR:CAF01_CAFETERIA_TMP | SOP-002:p2:table5 행 2 | °C | 21.0 | 17.0 | 26.0 | 14.0 | 30.0 | 0.4 | 같음 |
| CHM01_CHEMICALSTORAGE_HUM | SOP-002:THR:CHM01_CHEMICALSTORAGE_HUM | SOP-002:p2:table3 행 3 | %RH | 35.0 | 20.0 | 50.0 | 15.0 | 60.0 | 1.0 | 같음 |
| CHM01_CHEMICALSTORAGE_TMP | SOP-002:THR:CHM01_CHEMICALSTORAGE_TMP | SOP-002:p2:table3 행 2 | °C | 15.0 | 10.0 | 20.0 | 5.0 | 25.0 | 0.3 | 같음 |
| RND01_RDLAB_HUM | SOP-002:THR:RND01_RDLAB_HUM | SOP-002:p2:table4 행 3 | %RH | 50.0 | 35.0 | 65.0 | 25.0 | 75.0 | 1.0 | 같음 |
| RND01_RDLAB_TMP | SOP-002:THR:RND01_RDLAB_TMP | SOP-002:p2:table4 행 2 | °C | 22.0 | 18.0 | 26.0 | 15.0 | 30.0 | 0.2 | 같음 |
| SRV01_SERVERROOM_HUM | SOP-002:THR:SRV01_SERVERROOM_HUM | SOP-002:p2:table1 행 1 | %RH | 45.0 | 30.0 | 60.0 | 25.0 | 70.0 | 1.0 | 같음 |
| SRV01_SERVERROOM_TMP | SOP-002:THR:SRV01_SERVERROOM_TMP | SOP-002:p1:table5 행 2 | °C | 21.0 | 18.0 | 25.0 | 16.0 | 28.0 | 0.3 | 같음 |
| ST01_FILLING_FLW | SOP-002:THR:ST01_FILLING_FLW | SOP-002:p1:table1 행 4 | L/min | 120.0 | 112.0 | 128.0 | 105.0 | 135.0 | 1.5 | 같음 |
| ST01_FILLING_PRS | SOP-002:THR:ST01_FILLING_PRS | SOP-002:p1:table1 행 3 | bar | 3.8 | 3.3 | 4.2 | 3.0 | 4.8 | 0.05 | 같음 |
| ST01_FILLING_TMP | SOP-002:THR:ST01_FILLING_TMP | SOP-002:p1:table1 행 2 | °C | 22.0 | 18.0 | 26.0 | 15.0 | 30.0 | 0.4 | 같음 |
| ST02_SEALING_CUR | SOP-002:THR:ST02_SEALING_CUR | SOP-002:p1:table2 행 4 | A | 12.4 | 11.0 | 13.5 | 9.5 | 15.0 | 0.3 | 같음 |
| ST02_SEALING_PRS | SOP-002:THR:ST02_SEALING_PRS | SOP-002:p1:table2 행 3 | bar | 5.2 | 4.6 | 5.7 | 4.2 | 6.2 | 0.08 | 같음 |
| ST02_SEALING_TMP | SOP-002:THR:ST02_SEALING_TMP | SOP-002:p1:table2 행 2 | °C | 185.0 | 175.0 | 195.0 | 165.0 | 210.0 | 1.2 | 같음 |
| ST03_LABELLING_CNT | SOP-002:THR:ST03_LABELLING_CNT | SOP-002:p1:table3 행 4 | pcs/min | 120 | 110 | 130 | 100 | 140 | 2.0 | 같음 |
| ST03_LABELLING_SPD | SOP-002:THR:ST03_LABELLING_SPD | SOP-002:p1:table3 행 2 | m/s | 0.85 | 0.75 | 0.95 | 0.65 | 1.05 | 0.01 | 같음 |
| ST03_LABELLING_TEN | SOP-002:THR:ST03_LABELLING_TEN | SOP-002:p1:table3 행 3 | N | 2.2 | 1.8 | 2.6 | 1.5 | 3.0 | 0.05 | 같음 |
| ST04_PACKAGING_CUR | SOP-002:THR:ST04_PACKAGING_CUR | SOP-002:p1:table4 행 3 | A | 8.7 | 7.5 | 9.8 | 6.5 | 11.0 | 0.2 | 같음 |
| ST04_PACKAGING_SPD | SOP-002:THR:ST04_PACKAGING_SPD | SOP-002:p1:table4 행 4 | m/s | 1.2 | 1.0 | 1.4 | 0.85 | 1.6 | 0.02 | 같음 |
| ST04_PACKAGING_VIB | SOP-002:THR:ST04_PACKAGING_VIB | SOP-002:p1:table4 행 2 | mm/s | 0.12 | 0.02 | 0.2 | 0.01 | 0.35 | 0.005 | 같음 |
| WRH01_WAREHOUSE_HUM | SOP-002:THR:WRH01_WAREHOUSE_HUM | SOP-002:p2:table2 행 3 | %RH | 75.0 | 60.0 | 85.0 | 55.0 | 90.0 | 1.5 | 같음 |
| WRH01_WAREHOUSE_TMP | SOP-002:THR:WRH01_WAREHOUSE_TMP | SOP-002:p2:table2 행 2 | °C | 4.0 | 0.5 | 8.0 | -1.0 | 12.0 | 0.5 | 같음 |

## 요약

- 센서 22개 중 수치·단위 불일치 0개, 수치는 같고 표기만 다름 0개
- 임계값 파일에만 있는 센서: 없음
