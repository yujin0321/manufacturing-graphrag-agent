# 전처리 구현 보고 (preprocess_impl)

상태: 구현·자체 실행까지 함. **합격 여부는 verifier가 정한다. verifier 검증이 필요하다.** 커밋하지 않았다.

## 1. 만든 파일
| 경로 | 내용 |
|---|---|
| `src/imaks_kg/__init__.py`, `common/__init__.py`, `preprocess/__init__.py` | 패키지 |
| `src/imaks_kg/settings.py` | 저장소 루트를 `Path(__file__)`로 계산, 경로 상수(절대 경로 하드코딩 없음) |
| `src/imaks_kg/common/io_utils.py` | UTF-8 LF 쓰기(csv/json/jsonl), `imaks_data/` 아래 쓰기는 `PermissionError`로 거부 |
| `src/imaks_kg/common/provenance.py` | sha256(파일, 텍스트) |
| `src/imaks_kg/preprocess/sensors.py` | 센서 전처리 |
| `src/imaks_kg/preprocess/documents.py` | 문서(PDF) 전처리 |
| `harness/forbidden_columns_header_only.txt` | 컬럼 전용 금지어 11개(신규). `harness/forbidden_columns.txt`는 그대로 |
| `.claude/skills/stage-check/scripts/check_leakage.py` | 최소 수정(아래 4장) |
| `tests/test_check_leakage.py`(11), `tests/test_preprocess_sensors.py`(10), `tests/test_preprocess_documents.py`(10) | 신규 테스트 |
| `.gitignore` | `/preprocessed/`, `/evaluation/` 두 줄 추가(앞 슬래시, Edit 도구, 기존 CRLF 줄바꿈에 맞춤). `git check-ignore -v`로 두 폴더 무시, `src/` 는 무시되지 않음 확인 |

## 2. 실행 방법 (저장소 루트)
```
PYTHONPATH=src PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m imaks_kg.preprocess.sensors
PYTHONPATH=src PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m imaks_kg.preprocess.documents
PYTHONPATH=src .venv/Scripts/python.exe -m unittest discover -s tests
```
문서 쪽은 `preprocessed/sensors/rules/sensor_thresholds.csv`가 있으면 SOP-002 표와 대조한다(없으면 대조만 생략). 센서를 먼저 돌리는 편이 좋다.

## 3. 입력/출력
입력(읽기 전용): `imaks_data/sensors/timeseries_raw.csv`, `timeseries_annotated.csv`, `imaks_data/rules/*.pdf`(4), `imaks_data/datasheets/*.pdf`(3). 정답 규칙 파일(86규칙)은 코드가 읽지도 쓰지도 않는다(코드에 그 이름도 없음).

출력:
- `preprocessed/sensors/input/ts_input.csv` (허용목록 7컬럼, 211,200행, `sensor_id,timestamp` 정렬, value는 원본 문자열)
- `preprocessed/sensors/metadata/original_time_labels.csv` (`original_day/_shift/_batch_id`)
- `preprocessed/sensors/rules/sensor_thresholds.csv` (22행, 헤더 `sensor_id, unit, nominalValue, warnLo, warnHi, critLo, critHi`: 온톨로지 속성 이름에 맞춤. raw를 읽는 쪽은 원본 컬럼명 유지)
- `evaluation/row_labels.csv` (키 + annotated 추가 컬럼 3개 + raw 품질 컬럼; 평가 전용)
- `preprocessed/sensors/profile.json`
- `preprocessed/documents/{doc_manifest.csv, pages.jsonl, tables.jsonl, chunks.jsonl, glyph_fixes.csv}`, 추가로 `doc_profile.json`(개수·해시·경고만)

센서 입력 설계: 허용목록 7컬럼만 읽어 `ts_input`에 쓴다. 정답 라벨 컬럼은 `annotated 컬럼 − raw 컬럼`의 집합 차로 구한다(코드에 이름 없음). raw의 나머지 컬럼은 (시간 라벨 3개, 임계값 5개, 품질 1개)로 정확히 일치하는지 assert하고 각각 별도 파일로 분리했다.

## 4. check_leakage.py 수정 (최소)
- 컬럼 전용 목록(`forbidden_columns_header_only.txt`)을 읽어 **CSV 헤더와 `.json/.jsonl`의 키에만** 전체 일치(대소문자 무시)로 적용. 본문 텍스트에는 적용하지 않음. 목록 파일이 없으면 무시.
- 일반 목록은 기존대로 본문·CSV 헤더에 적용. `.jsonl`을 검사 대상 확장자에 추가.
- 출력 형식 유지(첫 줄에 `, 컬럼 전용 N개`만 추가).
- **예외 없음(사용자 확정 반영):** 앞서 넣었던 `preprocessed/sensors/rules/` 헤더 예외(`HEADER_ONLY_EXEMPT_PREFIXES`)는 제거했다. 임계값 CSV 컬럼명을 바꿔서 예외 없이 통과한다.
- **문서 폴더 예외(사용자 확정 반영):** 상수 `TEXT_EXEMPT_PREFIXES = ("preprocessed/documents/",)`. 이 폴더의 `.json/.jsonl`은 일반 목록의 본문(값) 검사를 하지 않고, JSON 키만 두 목록(일반+컬럼 전용) 모두에 대해 전체 일치로 검사한다. 이유: 문서 폴더는 ④ 추출용 원문이라 ⑥ 입력이 아니며 원문에 금지어 단어가 자연스럽게 나온다(SOP-004 "Severity" 제목). 시험은 ROOT를 임시 폴더로 바꿔 상대 경로 규칙을 확인한다.

## 5. 검증 결과 (실행한 것)
- 센서: `-m imaks_kg.preprocess.sensors` -> `ts_input 행 211200, 센서 22, timestamp 9600, 임계값 행 22`. 코드 안 assert 통과(행 수, 센서 수, 타임스탬프 수, 키 중복 0, value 문자열 동일, 정렬, 헤더 7개, raw/annotated 공통 컬럼 값 동일, 센서별 임계값 일정, 헤더가 두 금지 목록과 겹치지 않음). 결측 0(허용목록 컬럼). 출력은 LF만, BOM 없음.
- 문서: 문서 7, 쪽 10, 표 24(SOP-001 1, SOP-002 11, SOP-003 2, SOP-004 3, DS-ELEC 1, DS-MECH 4, DS-THERM 2). 연속 표 1건(`SOP-002:p2:table1` <- `SOP-002:p1:table5`). 청크: rule 28(SOP-001 24 + SOP-004 4), table 24, text 34.
- `RULE-ST02-04` 청크: 쪽 1, 섹션 "2.2 ST02_SEALING", 줄바꿈으로 이어진 3줄 전체("... triggers a WARNING.")가 한 청크.
- SOP-002 센서 행 22개 추출, `sensor_thresholds.csv`(raw 유래)와 nominalValue/warn/crit/unit 22행 모두 일치. 허용오차(`± 0.4` 등)는 추출 시 분리해 비교에서만 썼고 출력엔 쓰지 않았다.
- 전체 테스트: `unittest discover -s tests` -> 50개 OK(기존 test_shacl 포함, 문서 폴더 예외 시험 3개 추가, 약 60초 이내).
- `check_leakage.py ontology_v1 tests` -> PASS (파일 17개, 금지어 8개, 컬럼 전용 11개).
- `check_raw_unchanged.py` -> PASS (1121개 파일, 원본 불변).
- 절대 경로 grep(`C:\`, `/Users/`, `/home/`) `src/` 0건.
- **`check_leakage.py` 기본 폴더 -> PASS** (파일 31개, 금지어 8개, 컬럼 전용 11개). 센서 전처리 재실행 후(임계값 헤더 변경) 및 문서 전처리 재실행 후 결과이며, SOP-002 대조 `sop002_matches_sensor_file: true`, 경고 0.

## 6. 글리프 치환 요약 (`glyph_fixes.csv` 86행)
pdfplumber는 Symbol 폰트 바이트를 StandardEncoding으로 풀어 유니코드를 낸다(예: 바이트 0xAE -> 합자 "fi"). 그래서 폰트 이름에 Symbol이 들어간 글자만 (유니코드 -> 원 바이트 -> Symbol 코드표)로 바꿨다. 일반 글꼴의 "fi"("Specifications" 등)는 건드리지 않음(테스트로 확인). pdfplumber의 `extract_text`는 합자를 2글자("fi")로 펼치므로 위치는 `text_raw` 기준 문자 인덱스이고 길이가 달라지는 구간은 difflib로 맞췄다.
| 원문(추출) | 코드 | 치환 | 쪽 본문 | 표 셀 | 문맥 확인 |
|---|---|---|---|---|---|
| fi | 0xAE | → | 9 | 6 | SOP-001 "ST01_FILLING → ST02_SEALING", SOP-003 "CUR↑ → SPD↓" |
| › | 0xAD | ↑ | 4 | 4 | SOP-003 "ST02_SEALING-CUR↑" |
| fl | 0xAF | ↓ | 1 | 1 | SOP-003 "ST04_PACKAGING-SPD↓" |
| s | 0x73 | σ | 2 | 2 | SOP-002 "deviation >3σ", "Slope >0.1σ/min" |
| ‡ | 0xB3 | ≥ | 1 | 1 | DS-MECH-4400 "Resonant frequency ≥ 18 kHz" |
- 코드표에는 ± (0xB1)도 있으나 이번 PDF에는 해당 글자가 없어 쓰이지 않았다. 미해결 기호 글자(코드표에 없는 것)는 0개(경고 없음).
- `R&D;` -> `R&D`: 쪽 본문 4, 표 셀 3(원문은 `text_raw`/`rows_raw`에 보존).
- 쪼개진 셀 병합(공백 없이): SRV01_SERVERROOM(SOP-001, SOP-003), CHM01_CHEMICALSTORAGE(SOP-001, SOP-003), WRH01_WAREHOUSE, OUT_OF_RANGE, CRIT_LO/CRIT_HI/WARN_LO/WARN_HI(각 9), `pcs/min`, `Sensor`, SOP-004 헤더 "Gen. Warehouse", "Main Entrance", "Chem. Storage", SOP-003 §2 "ST04_PACKAGING-SPD". 이 병합은 헤더 행, ID형 열(Station/Station ID/Type/Unit), 줄 끝이 `-`·`_`인 경우에만 공백 없이 붙이고, 다른 셀의 줄바꿈은 공백으로 이었다.

## 7. 알려진 한계
- 쪽 본문(`text_normalized`)의 표 영역에는 셀 병합이 적용되지 않는다(예: 본문엔 `SRV01_SERVERROO`와 `M`이 다른 줄에 남음). 셀 병합은 `rows_normalized`와 table 청크에만 반영된다.
- 연속 표 판정은 휴리스틱(앞 쪽 표 바닥이 쪽 높이의 90% 이하, 이번 표 상단이 15% 이내, 열 수 동일). 이 PDF 묶음에서는 1건만 걸리며 의도와 일치.
- 표 제목(`caption`)은 표 바로 위 30pt 이내의 줄이며 마침표로 끝나는 줄은 제목에서 제외(SOP-001 §1 표는 제목 없음).
- text 청크가 "ST01_FILLING Thresholds" 같은 제목 한 줄짜리 작은 청크(길이 30자 미만 15개)를 만든다. 지시한 규칙(규칙·표 이외 본문 전부)을 그대로 적용한 결과이며 검색 쪽에서 합치거나 걸러야 할 수 있다.
- 연속 표(SOP-002 p2 table1)의 table 청크는 앞 표의 헤더와 제목을 빌려 한 행을 풀어 쓴다(`continued_from`로 표시).
- `char_count`는 `text_normalized` 길이로 정의했다(원문 길이는 `char_count_raw`). rule 청크의 `text`는 줄바꿈을 공백으로 바꾼 것이며 길이는 같아 `char_start/end`와 일대일로 맞는다. table 청크의 `char_start/end`는 해당 표 줄들이 차지하는 쪽 본문 구간이고 `text`는 풀어 쓴 별도 텍스트다.
- 셀 bbox는 pdfplumber `find_tables` 결과. 병합 셀(None bbox)은 빈 문자열로 처리한다(현재 PDF엔 없음).
- 글리프 로그의 `before`가 합자 두 글자("fi")인 행이 있다(pdfplumber 합자 펼침 때문).
- `profile.json`·`doc_profile.json`은 금지어 이름 없이 개수·해시만 담았다.
- 센서 쪽 `day` 등 시간 라벨은 원본 값 그대로 `original_*`로 보존만 했다(파생 `calendar_date`/`clock_shift`는 이 단계 범위가 아니라 만들지 않음).

## 8. 미결정·가정
1. (해결) 임계값 헤더 충돌: 컬럼명을 `nominalValue` 등으로 바꾸고 검사 예외를 제거함.
2. (해결) 문서 본문 "Severity" 오탐: `preprocessed/documents/` json/jsonl은 값 검사 제외, 키만 검사(위 4장).
3. 가정: doc_id는 1쪽 "Document: <ID> |"에서 가져옴(7개 모두 성공). 표 행 0이 항상 헤더(연속 표 제외)라고 가정해 table 청크를 만들었다(24개 표 모두 해당).
4. 가정: `row_labels.csv`의 "품질 컬럼"은 raw의 `quality` 한 개. annotated에도 같은 컬럼이 있으며 raw와 값이 같음을 assert로 확인했다.
5. 가정: SOP-002 임계값 대조에 센서 전처리 산출물을 참조한다(원본 센서 파일 유래). `ontology_v1/schema_tables.md` 7장은 구조 대응표라 임계값 수치 대조 대상이 아니었고, 수치는 `reports/own_facts_for_design.md`의 "raw의 임계값은 SOP-002 표와 센서별로 일치"와 일치하는 결과가 나왔다.
6. 데이터시트 vs SOP-002 수치 충돌은 이 단계에서 다루지 않았다(원문은 모두 보존되어 있어 ④에서 출처와 함께 기록 가능).

verifier 검증이 필요하다.
