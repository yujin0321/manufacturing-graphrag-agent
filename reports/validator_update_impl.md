# ④ 추출 검증기 수정 2건 구현 보고 (2026-10-14)

합격 판정은 하지 않는다. verifier 검증이 필요하다.

## 1. 바꾼 점

수정한 코드
- `src/imaks_kg/extract/validator.py`: 인용 대조를 공백 정규화로 바꿈(`collapse_ws`, `resolve_evidence` 재작성), 비차단 플래그 2개(`quote_whitespace_adjusted`, `split_from_printed_id`)와 `INFO_FLAGS`, `apply_identifier_suffixes` 추가. 예전 `_count_overlapping`은 `_find_all`로 대체. `pageSliceExact` 필드는 없앰(sourceQuote 자체가 쪽 텍스트 구간이라 의미가 없어짐).
- `src/imaks_kg/extract/docdata.py`: `TableInfo.raw_rows` 추가(셀 줄바꿈을 지킨 문자열; 앞뒤 공백만 제거). 기존 `rows`(줄바꿈을 공백으로 바꾼 표시용)는 요청 렌더링용으로 그대로.
- `src/imaks_kg/extract/reserved_ids.py`(새 파일): ③ 산출물의 identifier 열(stations, sensors, maintenance_rules, documents)만 읽는다. docdata에 두지 않은 이유: 기존 시험 `test_seed_maintenance_text_not_read`가 요청 쪽 소스에 `maintenance_rules` 문자열이 없어야 한다고 검사하므로(시험을 약화하지 않으려고 분리).
- `src/imaks_kg/extract/artifacts.py`: `collect_rules`가 접미사를 먼저, 중복 플래그를 나중에 적용. `quote_stats` 추가, `run_summary.json`에 `quote_stats`, `quote_match_rate`, `quote_whitespace_adjusted` 기록. `by_flag`에 새 플래그 2개 포함.
- `src/imaks_kg/extract/run.py`: 새 identifier 목록을 `write_outputs`에 전달(run/validate 둘 다).
- `to_rdf.py`는 수정하지 않았다(Provenance의 `sourceQuote`/`textSha256`을 그대로 쓰므로 새 값이 자동 반영).

시험
- 새 파일 `tests/test_extract_b_quote_ws.py` (26개). 기존 `tests/test_extract_b_validator.py`의 `test_prose_position_matches_page_text`에 sourceQuote = 쪽 텍스트 구간, 해시 = 그 구간, model_quote 존재 단언 추가. 다른 기존 시험은 고칠 필요 없이 통과(의미 약화 없음).

## 2. 인용 매칭 정의와 위치·해시 처리

- 정규화: `str.isspace()`가 참인 글자(스페이스, 탭, 줄바꿈, 비분리 공백 등)의 연속을 공백 하나로, 앞뒤 공백 제거. 인용과 대상(산문은 청크 텍스트, 표는 셀 텍스트 또는 한 행의 셀 이음 `' | '`)에 같은 규칙을 적용. 그 밖(대소문자, 구두점, 숫자, 단어)은 엄격. 공백 유무 자체(`(< 60` vs `(<60`)는 정규화 대상이 아니라 불일치로 남는다.
- 위치: 정규화 문자열에서의 일치 위치를 `collapse_ws`가 만든 위치 표(정규화 글자 -> 원문 글자)로 원문 구간으로 되돌린다. 산문은 청크 안 구간을 얻은 뒤 기존 로직대로 청크와 쪽 텍스트가 글자 단위로 대응(공백류만 다를 수 있음)하는지 확인하고 `charStart/charEnd`(쪽 텍스트 기준)를 계산한다. 대응이 안 되면 `position_unresolved`(추측 없음). 정규화 후에도 여러 곳에 맞으면 `position_unresolved`.
- 저장 값: `Provenance.sourceQuote`와 `textSha256`은 쪽 텍스트에서 잘라 낸 실제 구간(줄바꿈 포함 가능)으로 계산(`page[charStart:charEnd]`와 항상 같음). 표는 셀의 `raw_rows` 구간(셀 안 줄바꿈 유지). 위치를 확정하지 못했지만 청크 안 구간이 유일하면 청크 구간을 쓴다.
- rules_all.jsonl의 evidence 항목: `model_quote` = 모델이 준 인용(감사용), `source_quote` = 실제 구간(찾지 못한 경우는 모델 인용 그대로). 이 때문에 `flags.csv`와 검토 파일(review.py)이 보여 주는 `source_quote`는 이제 원문 구간이다.
- `quote_whitespace_adjusted`: 최종 실제 구간이 모델 인용과 문자열로 다를 때(= 공백만 다른 일치) 붙는 비차단 정보 플래그. KG 적재 제외 사유 아님(`EXCLUDING_FLAGS` 불변), 예측 파일의 identifier/condition/action에는 영향 없음(`flags` 목록에 이름이 추가될 뿐).
- `quote_match_rate` = (evidence 수 - evidence_not_found가 붙은 evidence 수) / 전체 evidence 수. 공백 조정 일치는 일치로 센다. position_unresolved, table_position_out_of_range는 일치율에 영향을 주지 않는다(별도 플래그). run_summary에는 `quote_stats`(evidence_total, evidence_matched, evidence_not_found, quote_whitespace_adjusted, quote_match_rate)도 함께 둔다. 이 집계는 검증을 통과한(accepted) 응답의 evidence만 센다.

## 3. 접미사 정책

- 대상: 같은 문서(`document_id`) 안에서 `printed_rule_id`(공백 제거 후)가 두 번째 이후로 나온 규칙. 첫 규칙은 원래 ID. 두 번째부터 `<ID>-2`, `<ID>-3`.
- 후보가 겹치면 번호를 올림: 모든 규칙의 현재 identifier(인쇄 ID, 자동 부여 `문서:청크:번호` 포함), ③ seed identifier(Station, Sensor, 정비 규칙 MAINT-01~08, 문서)를 피한다. 이후에 나오는 인쇄 ID(예: 원문의 `R-2`)도 미리 피한다.
- 적용 위치: `collect_rules`(실행 전체 규칙 목록)에서 한다. 한 문서가 여러 part로 나뉘어 호출돼도 문서 단위로 일관되게 적용된다. `validate_response` 단독 호출 결과에는 접미사가 아직 없다(시험은 `apply_identifier_suffixes`를 직접 부르거나 run 경로를 쓴다).
- `printed_rule_id`는 원문 그대로. 접미사가 붙은 규칙에 `split_from_printed_id`. 다시 불러도 결과 동일(멱등).
- 다른 문서의 같은 인쇄 ID는 접미사를 붙이지 않는다. 현재 동작 유지 요청에 따라 `duplicate_identifier`가 그대로 나온다(시험으로 확인). 이 경우는 "문서 ID가 달라 별도 취급"이 identifier 문자열의 유일성까지 뜻하는지가 모호하다(미결정 참조).

## 4. 스모크 응답 재검증 (LLM 재호출 없음)

명령: `validate --run-id smoke-g31fl-ds-elec --out-run-id smoke-g31fl-ds-elec-v2 --config config/extract.gemini-3-1-flash-lite.toml` (저장된 응답 해시 검사 통과). 기존 run 폴더는 건드리지 않았다(기존 flags.csv, run_summary.json 그대로 확인).

| 항목 | 기존 run | v2 run |
|---|---|---|
| 규칙 수 | 8 | 8 |
| evidence_not_found | 2 | 0 |
| duplicate_identifier | 3 | 0 |
| split_from_printed_id | - | 2 (Note 2-2, Note 2-3) |
| quote_whitespace_adjusted | - | 5 |
| position_unresolved 등 그 밖 차단 플래그 | 0 | 0 |
| 예측 수 / KG 적재 대상(rules_valid) | 8 / 5 | 8 / 8 |
| quote_match_rate | (미기록) | 1.0 (8/8) |

- 기존 불일치 2건(규칙 6, 7: `Operation between\n14 A ...`와 `... be\nset no higher ...`)이 일치로 바뀜: 규칙 6 charStart/End 527~609, 규칙 7 680~818, 쪽 텍스트 구간을 sourceQuote로 저장.
- `quote_whitespace_adjusted` 5건 = 위 2건 + 표 행 인용 3건. 표 행 3건은 모델이 인용 끝에 `" | "`(빈 셀 경계)를 붙였고, 규칙상 앞뒤 공백이 제거돼 저장 구간은 `... |`로 끝나서 문자열이 달라진 경우다. 규칙대로 동작한 결과이나 "줄바꿈 때문" 건과 성격이 다르다(제안 참조).
- 같은 v2 폴더에서 `to-rdf`를 돌려 규칙 8/8개 TTL 반영, SHACL(S7·S8 포함, 추론 없음) 적합 확인(이 단계는 요청 범위 밖이지만 새 값으로 확인용으로 실행; v2 폴더에만 파일이 생김, git 제외 폴더).

## 5. 검증 실행 결과

- 전체 단위 테스트(`PYTHONPATH=src .venv/Scripts/python.exe -m unittest discover -s tests`) 마지막 요약: `Ran 301 tests in 168.935s` / `OK` (기존 275 + 새 26).
- `check_leakage.py` 기본 폴더: `검사한 파일 125개 ... PASS: 금지 컬럼 없음`, 경고 줄 없음(0건).
- `check_secrets.py` 기본: 검사 197개, 발견 0건 PASS. `check_secrets.py src tests config`: 검사 76개, 발견 0건 PASS.
- `check_raw_unchanged.py`: `PASS: imaks_data/ 원본 불변 (1121개 파일)`.
- 절대 경로 grep(`[A-Za-z]:[\\/]`, `/Users/`, `/home/`)을 `src/imaks_kg/extract`와 새 시험 파일에 실행: 걸린 것은 기존 API 주소(https://...)뿐이고 로컬 절대 경로는 없음. `ground_truth`·`severity` 단어(`ruleSeverity` 제외)는 새/수정 파일에 없음.
- 실제 API 호출 없음. 정답 파일은 열지 않았다.

## 6. 설계서 수정안 제안 (docs/는 수정하지 않았다)

§5 (코드 검증)
- 인용 대조 문장을 "인용과 청크/셀을 각각 연속 공백류를 공백 하나로 바꾸고 앞뒤 공백 제거 후 비교(나머지는 엄격)"로 바꾸고, 위치는 원문으로 되돌려 매핑, `sourceQuote`/`textSha256`은 원문 구간, 모델 인용은 `model_quote`(감사용)로 보존한다고 명시.
- 플래그 목록에 비차단 정보 플래그 2개(`quote_whitespace_adjusted`, `split_from_printed_id`)를 추가하고 "KG 적재 제외 사유 아님, 평가 예측 불변"을 적음.
- identifier 항목: "같은 문서 안에서 인쇄 ID 반복 시 두 번째부터 `-2`, `-3`, 후보 충돌 시 번호 상승(자동 부여 ID, 다른 인쇄 ID, ③ seed ID 회피)". `duplicate_identifier`는 해결할 수 없는 충돌(예: 서로 다른 문서의 같은 ID)에만 남는다.
§13 (구현 반영 사항)
- 위 두 수정, `run_summary`의 `quote_match_rate`/`quote_stats` 정의(분모 = 전체 evidence, 분자 = evidence_not_found가 아닌 evidence), 새 모듈 `reserved_ids.py`, 전체 시험 301개를 기록.
- 예선 1차 관문 "인용 일치율"은 `quote_match_rate`로 계산한다고 못박기.

## 7. 가정

- "공백류"는 파이썬 `str.isspace()` 기준(유니코드 공백 포함). 너비 0 글자(U+200B 등)는 공백이 아니다.
- 인용 앞뒤 공백만 다른 경우(표 행 끝의 `" | "` 포함)도 "공백만 달라 일치"로 보아 `quote_whitespace_adjusted`를 붙였다.
- 접미사는 run 단위 목록(`collect_rules`)에서 정하며, 순서는 응답 안의 규칙 순서(part 순서)다.
- ③ seed identifier 목록은 `kg_build/instances/`의 CSV 4개의 `identifier` 열.
- 표 인용의 "원문"은 전처리 `rows_normalized`(셀 줄바꿈 유지) 기준이다. 모델에게 보이는 표 렌더링은 기존대로 줄바꿈을 공백으로 바꾼 표시용이다.

## 8. 미결정, 미확인

- 미결정: 서로 다른 문서에서 같은 인쇄 ID가 나올 때 `duplicate_identifier`를 그대로 두는 것이 의도인지(현재 유지). to-rdf는 입력 안의 identifier 중복이면 중단하므로 이 경우 사람 검토(`edited_identifier`) 단계가 필요하다. 문서 ID를 접두로 붙이는 방안은 구현하지 않았다.
- 미결정: 표 행 인용 끝의 `" | "` 때문에 생기는 `quote_whitespace_adjusted`를 정보 플래그로 계속 셀지(현재 셈), 앞뒤 구분자만 다른 경우는 제외할지. 일치율에는 영향 없고 비차단이다.
- 미확인: 다른 6개 문서(SOP-001~004, 다른 데이터시트)의 실제 응답에서 일치율이 어떻게 나오는지(스모크 응답 한 개로만 재검증). 이름 `quote_stats` 하위 키를 소비하는 평가/보고 스크립트가 있는지.
- 미확인: 쪽 텍스트와 청크가 글자 단위로 대응하지 않는 청크(실제로는 발견 안 됨)에서의 동작은 합성 시험 없이 코드 경로만 있다.
- 미확인: `review.py` 검토 흐름에서 `source_quote`가 원문 구간(줄바꿈 포함)으로 바뀐 것이 검토 CSV에서 보이는 방식(줄바꿈이 셀 안에 들어감) - 시험은 기존 것이 통과했으나 사람 눈으로 확인하지 않았다.

verifier 검증이 필요하다.
