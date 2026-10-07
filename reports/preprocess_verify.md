# 전처리(센서·문서) 검증 보고서
- 판정: PASS (공통 + 전처리 절 전 항목 통과. 추가 관찰 4건은 판정 제외)
- 범위: harness/checklist.md의 "공통"과 "전처리 (센서·문서)" 절만. 구현자 보고서(reports/preprocess_impl.md)는 근거로 쓰지 않았다.

## 항목별 결과
| 항목 | 결과 | 근거 |
| --- | --- | --- |
| 공통: check_raw_unchanged PASS | PASS | "PASS: imaks_data/ 원본 불변 (1121개 파일)", 종료코드 0 |
| 공통: check_leakage PASS | PASS | 기본 폴더 실행 "검사한 파일 31개 ... PASS: 금지 컬럼 없음". `evaluation`을 추가해 돌리면 row_labels.csv에서 4건 발견되지만 의도된 격리 위치라 오탐이다(아래 추가 관찰) |
| 공통: 코드에 절대경로 없음 | PASS | `grep -rnE "C:\\|/Users/|/home/" src tests` 결과 없음 |
| 공통: 큰 산출물·원본이 git 추적 아님 | PASS | `git ls-files` = .gitignore, LICENSE, README.md뿐. `.gitignore`에 `imaks_data/`, `/preprocessed/`, `/evaluation/`, `.venv/` |
| 공통: 이상값 삭제·보간·평활화 코드 없음 | PASS | src에서 interpolat/rolling/smooth/dropna/fillna/ffill/bfill/clip/savgol/ewm/resample 검색 결과 없음. value 문자열 일치 확인(아래) |
| ts_input 헤더 7개 | PASS | `timestamp,zone,station_id,sensor_id,sensor_type,value,unit` |
| 211,200행, 센서 22, 타임스탬프 9,600, 중복 0 | PASS | 직접 계산: 행 211200, 센서 22, 타임스탬프 9600, (sensor_id,timestamp) 중복 0 |
| 7개 값이 timeseries_raw.csv와 문자열 동일 | PASS | 211,200행 전부 (sensor_id,timestamp) 키로 대조, 불일치 0 (원본 키 211200개) |
| (sensor_id, timestamp) 정렬 | PASS | `keys == sorted(keys)` True |
| 정답·품질 컬럼은 evaluation/row_labels.csv에만 | PASS | row_labels 헤더 `sensor_id,timestamp,anomaly_label,severity,alarm_flag,quality`, 211,200행, 키 집합이 ts_input과 동일, 값은 timeseries_annotated.csv와 불일치 0. preprocessed 내 CSV 헤더·JSON 키에 없음(스크립트 PASS) |
| 임계값은 rules/에만 | PASS | ts_input 헤더에 임계 컬럼 없음. 임계값은 `preprocessed/sensors/rules/sensor_thresholds.csv`(nominalValue,warnLo,warnHi,critLo,critHi) |
| original_day/shift/batch_id 보존·원본과 동일 | PASS | `metadata/original_time_labels.csv` 헤더 `original_day,original_shift,original_batch_id`, 211,200행 원본 raw 값과 불일치 0 |
| 임계값 22행 = SOP-002 tables.jsonl 센서별 일치 | PASS | thresholds 22행. tables.jsonl의 SOP-002 임계 표 행 22개(캡션의 station + 센서 종류로 sensor_id 구성)를 단위·CRIT_LO·WARN_LO·Nominal(± 앞)·WARN_HI·CRIT_HI로 수치 대조: 불일치 0, 22센서 전부 대응. 원본 raw의 센서별 임계(상수)와도 일치 |
| doc_manifest 7행, PDF SHA-256 일치, 쪽 10, 표 24 | PASS | 7개 PDF를 직접 해시해 file_sha256과 모두 일치. 쪽 합계 10(pages.jsonl 10행), tables.jsonl 24행 |
| 청크 필드 완비, text_sha256 = SHA-256(text) | PASS | 86청크(text 34, rule 28, table 24). doc_id/page/text_sha256/source_file_sha256 누락 0, 위치(char_start/char_end 또는 bbox) 누락 0, text 해시 불일치 0, source_file_sha256이 manifest와 불일치 0 |
| RULE-ST02-04가 1쪽의 한 청크에 온전히 | PASS | chunk `SOP-001:p1:RULE-ST02-04`(kind=rule, page 1)에 "RULE-ST02-04: ... Monitor ST04_PACKAGING-SPD whenever ST02_SEALING-CUR triggers a WARNING." 전문이 들어 있다 |
| 글리프 치환은 Symbol/ZapfDingbats에만, glyph_fixes 기록, 원문 보존 | PASS | glyph_fixes.csv 86행(profile의 glyph_fix_records와 일치). Symbol 글리프 치환(fi→→, s→σ, ›→↑, fl→↓, ‡→≥)은 이유란에 Symbol 폰트 코드가 적혀 있다. 일반 글꼴의 "fi"(specific, verify, humidifier 등)는 정규화 후에도 유지(SOP-001 p2·SOP-002 p2·SOP-004 등 raw와 normalized의 fi 개수 동일). 원문은 pages.jsonl `text_raw`, tables.jsonl `rows_raw`에 보존. 소스는 폰트명으로 Symbol 계열만 코드 매핑 |
| src가 ground_truth를 읽지 않음 | PASS | `grep -rn ground_truth src tests` 결과 없음 |
| /preprocessed/, /evaluation/ 무시, src 비무시 | PASS | `git check-ignore -v`: `.gitignore:221:/preprocessed/`, `:222:/evaluation/` 매치. src/imaks_kg/settings.py는 매치 없음(rc=1) |
| check_leakage 기본 폴더 PASS, 예외 상수는 TEXT_EXEMPT_PREFIXES 1개 | PASS | 기본 폴더 PASS. 스크립트의 예외성 상수는 `TEXT_EXEMPT_PREFIXES = ("preprocessed/documents/",)` 하나. (EVAL_DIRS, SKIP_DIRS는 각각 평가 폴더 구분·검색 제외용으로 금지어 면제가 아니다) |
| 단위 테스트 전부 통과 | PASS | `PYTHONPATH=src python -m unittest discover -s tests` → Ran 50 tests, OK |

## 불합격 사유와 수정이 필요한 위치
없음.

## 미확인 항목과 이유
없음. 아래 두 가지는 해석상 판단이다.
- 글리프 항목: glyph_fixes.csv에는 Symbol 글리프 치환 외에 "R&D;→R&D"(source typo)와 줄바꿈 분리 단어 병합(split-word cell merge)도 기록돼 있다. 이는 폰트 글리프 치환이 아니라 별도 텍스트 정규화이고, 모두 기록되며 원문이 보존돼 있어 항목 취지에 어긋나지 않는다고 판단했다.
- 항목 문구 "SOP-002 표"는 tables.jsonl의 `rows_normalized`를 기준으로 비교했다(rows_raw의 줄바꿈 깨짐은 정규화됨).

## 추가 관찰 (판정에 미포함)
1. 금지 목록의 이름 불일치: header_only 목록의 `nominal, warn_hi, warn_lo, crit_hi, crit_lo`는 원본 컬럼명이다. 그런데 산출물 `sensor_thresholds.csv`는 `nominalValue, warnLo, warnHi, critLo, critHi`(camelCase)를 쓴다. 전체 일치 검사라서 이 이름이 `preprocessed/sensors/input/` 같은 곳에 섞여도 스크립트가 못 잡는다. 현재 ts_input은 깨끗하지만 도구에 구멍이 있다. 변형 이름을 목록에 추가하는 것이 좋다.
2. check_leakage의 예외 범위: `preprocessed/documents/`의 .json/.jsonl은 키만 검사하고 본문 텍스트·`ground_truth` 경고 검사를 모두 건너뛴다. 문서 청크 text에 금지어나 ground_truth 언급이 들어와도 잡히지 않는다. 단 CSV(glyph_fixes.csv, doc_manifest.csv)는 헤더만 보므로 CSV 본문은 원래 검사하지 않는다. 의도한 범위(문서 폴더 JSON)에는 맞지만, 키 검사로 문서 JSON 구조에 정답 컬럼이 숨는 것은 막는다는 점만 확인했다. `grep -rli ground_truth preprocessed`는 결과 없음.
3. 기본 검사 폴더(preprocessed, ontology_v1, kg_build, src)에 `evaluation`이 없어서 `evaluation/row_labels.csv`는 기본 실행으로 검사되지 않는다. 그 폴더를 직접 지정하면 정답 컬럼 4건이 나온다(의도된 위치). 따라서 "정답이 evaluation에만 있다"는 점은 스크립트가 아니라 이번 수동 대조로 확인했다. 평가 폴더 파일이 preprocessed로 복사되는 회귀는 헤더 검사로만 잡힌다.
4. 정답 정보 위치: `preprocessed/sensors/metadata/original_time_labels.csv`에 original_day/shift/batch_id가 있다. 이는 체크리스트가 허용한 보존본이지만, ⑥ 입력으로 읽을 때 shift·batch가 이상 구간과 상관이 있을 수 있으니 ⑥ 입력 목록에서는 제외하는 것이 안전하다. `profile.json`의 `source_sha256`에 annotated 파일 해시가 있는 것은 누수가 아니다. `evaluation/row_labels.csv`는 12MB 단일 파일로 git 무시 대상이다. 재현성: 모든 산출물이 git 무시이므로 src 재실행으로만 복원된다(profile.json에 출력 해시가 있어 대조 가능).
