# ③ 기존 KG 변환 v3 구현 보고서 (2026-10-14)

이전 보고서(v1, v2)는 고치지 않았다. 사용자 결정 "A"(매핑표를 1부터로 통일)를 반영했다.

## 1. 바뀐 점
수정한 파일은 `src/imaks_kg/kg/convert_seed.py`, `tests/test_kg_convert.py` 두 개다. CLAUDE.md, work_log.md, ontology_v1/, harness/, .claude/, imaks_data/는 건드리지 않았다.

- **번호 규약.** 매핑표 `kg_build/mapping/maint_seed_vs_sop003.csv`의 `sop003RowIndex`를 1부터(표 헤더 행 = 1)로 바꿨다. MAINT-01은 2, MAINT-08은 9다. 열 이름은 그대로다.
- **열 번호.** 이 매핑표에는 열 번호 열이 없어서 바꿀 것이 없었다. 문서 Provenance의 colIndex는 이미 1부터다.
- **규약 기록 위치.** 이 보고서에만 적었다. summary.json은 고치지 않았다(아래 2장 참고). 필요하면 verifier 또는 사용자가 summary.json 필드 추가 여부를 정해 달라.
- **내부 검사.** `check_row_index_consistent(ruleId, 매핑표 값, Provenance rowIndex)`를 추가했다. 두 값이 다르면 `ValueError`를 낸다. 매핑표 행을 만들 때 호출한다.
- **테스트.** `test_mapping_rowindex_matches_provenance`를 추가했다. 매핑표와 `provenance_document.csv`를 읽어 8행 모두 `sop003RowIndex == rowIndex`인지 보고, MAINT-01=2, MAINT-08=9를 확인한다. 검사 함수가 어긋난 값에 예외를 내는지도 확인한다.

## 2. 변경 전후 비교
변경 전에 `kg_build`를 임시 폴더에 복사한 뒤 변환을 다시 실행해 `cmp`로 비교했다.

- 바뀐 파일은 `kg_build/mapping/maint_seed_vs_sop003.csv` 하나뿐이다. 8개 데이터 행 모두 바뀐 열은 5번째 열(`sop003RowIndex`)뿐이고, 값은 1~8에서 2~9로 올랐다. 헤더와 나머지 열은 csv 파싱 기준으로 같다(원문 줄바꿈 포함 셀 비교).
- `kg_build/instances/*` 11개 파일(CSV 9개, `instances.ttl`, `triple_sources.jsonl`)은 바이트가 같았다.
- `summary.json`도 바이트가 같았다. 해시 정보에 매핑표는 들어 있지 않아서 바뀔 이유가 없었다. 지시문은 summary.json의 해시 정보가 바뀔 수 있다고 봤으나 실제로는 바뀌지 않았다.
- **재현성.** 변환을 한 번 더 실행해 `kg_build` 전체 13개 파일이 첫 실행 결과와 바이트까지 같았다.

## 3. 실행한 검증과 결과
- 변환 출력: 개수 일치(Station 9, Sensor 22, hasSensor 22, feedsInto 3, MaintenanceRule 8, Document 7, appliesToSensor 8, Provenance 47).
- `run_shacl.py`(`--data kg_build/instances/instances.ttl --ont ontology_v1/ontology.ttl --shapes ontology_v1/shapes.ttl`): Conforms: True, PASS.
- `check_leakage.py`: PASS. `check_raw_unchanged.py`: PASS(1121개 파일 불변). `check_secrets.py`: PASS(발견 0건).
- 전체 단위 테스트 `python -m unittest discover -s tests`의 마지막 요약: `Ran 78 tests in 42.537s` / `OK`(v2의 77개에 새 테스트 1개).

## 4. 가정
- 통일 방향은 매핑표를 Provenance에 맞추는 것(1부터)이다. Provenance와 TTL은 손대지 않았다.
- 매핑표 번호는 변환 코드에서 `rows_normalized` 인덱스 + 1로 만든다.

## 5. 미확인
- `sop003RowIndex` 열을 읽는 다른 소비자(코드, 문서)가 있는지는 전수 조사하지 않았다. 테스트와 보고서에서만 확인했다. 이전 보고서(v1, v2, verify)에는 "0부터"라는 서술이 남아 있고, 고치지 않았다.
- 규약 설명(1부터)이 파일 안에 없다. 열 이름만 봐서는 기준을 알 수 없다.

## 6. 변경하지 못한 문서에 필요한 수정안 (제안)
- `work_log.md`: 매핑표를 1부터로 통일한 결정 기록.
- `ontology_v1/schema_tables.md`의 매핑표 설명이 있다면 "1부터" 명시.

커밋하지 않았다. verifier 검증이 필요하다.
