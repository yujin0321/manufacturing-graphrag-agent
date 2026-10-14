# ④ 검증기 수정 2건 검증 보고서
- 판정: PASS
- 방법: 코드와 산출물을 직접 읽고, 실제 청크(preprocessed/documents)와 가짜 응답으로 검증기를 직접 실행했다. 임시 스크립트와 출력은 scratchpad에만 있다. 정답 파일은 열지 않았고 API는 호출하지 않았다. `kg_build/extraction/`에 시험 run을 만들지 않았다.

## 항목별 결과
| 항목 | 결과 | 근거 |
| --- | --- | --- |
| 1a 줄바꿈→공백 인용 일치 | PASS | 산문 8개(SOP-001 2, SOP-002, SOP-003, SOP-004, DS-ELEC, DS-MECH, DS-THERM). 줄바꿈이 든 구간을 공백으로 바꾼 인용 8/8이 일치하고 `quote_whitespace_adjusted` 1개만 붙었다. |
| 1b 한 글자·단어·숫자·대소문자·구두점 차이 | PASS | 같은 8개에 단어 하나 변경, 숫자 하나 변경, 대소문자 변경, 끝 구두점 변경을 넣었다. 모두 `evidence_not_found`였다. |
| 1c 표 셀 | PASS | SOP-001 table1 셀 4개. 원문 그대로 인용하면 플래그가 없다. 공백을 겹쳐 넣으면 일치하고 ws 플래그가 붙고 sourceQuote가 셀 원문과 같다. 단어 변경·swapcase는 not_found. bbox가 채워진다. 표 셀 원문(`rows_normalized`)에는 줄바꿈이 0개라 줄바꿈 표 셀은 시험할 수 없었다. |
| 1d 위치·해시·model_quote | PASS | 산문 8개에서 `pages.jsonl[charStart:charEnd]`가 `sourceQuote`와 같았고, 줄바꿈이 들어 있다. `textSha256`은 그 구간의 SHA-256을 직접 계산한 값과 같다. `model_quote`는 모델이 준 공백 인용으로 남고 `source_quote`는 원문 구간이다(v2 run 규칙 `Note 2-2`, `Note 2-3`도 같다). |
| 1e 여러 곳 일치·매핑 불가 | PASS | 청크 안에서 2번 이상 나오는 부분 문자열은 `position_unresolved`이고 `charStart`가 없다(`resolved` False). 쪽 텍스트를 일부러 어긋나게 한 가짜 store도 `position_unresolved`이고 위치가 없다. |
| 2 `quote_match_rate`·ws 집계 | PASS | v2: evidence 8개, not_found 0개, ws 5개, 비율 1.0이 `run_summary.json`과 같다. 가짜 run: evidence 6개, not_found 2개, ws 3개, 비율 0.666667이 손계산 (6-2)/6과 같다. |
| 3a 접미사 | PASS | 같은 문서에서 같은 ID가 3번이면 `NOTE-2`, `NOTE-2-2`, `NOTE-2-3`이 된다. `split_from_printed_id`는 두 번째부터 붙고 `printed_rule_id`는 원문 그대로다. |
| 3b 충돌 시 번호 올림 | PASS | `["N","N","N-2","N"]`은 `N`, `N-3`, `N-2`, `N-4`가 된다. reserved에 `MAINT-01-2`를 넣으면 `MAINT-01-3`이 된다. 실제 ③ 산출물 identifier 46개를 읽는다(MAINT-01~08 포함). 자동 부여 ID와 같은 인쇄 ID도 `-2`로 갈라진다. |
| 3c 결정성·재적용 | PASS | 같은 입력을 두 번 처리하면 결과가 같고, 이미 접미사가 붙은 규칙에 다시 적용해도 변하지 않는다. |
| 3d 다른 문서의 같은 인쇄 ID | PASS(관찰 있음) | `duplicate_identifier`가 유지된다(보고서 서술대로). 설계서 §5-6 마지막 문장(별개로 취급)과의 관계는 판정 외 관찰 1번. |
| 4 비차단 플래그 | PASS | 가짜 run: ws·split만 있는 `P`, `P-2`는 `rules_valid`에 남고, `evidence_not_found`를 가진 두 규칙은 `rules_valid`에서만 빠졌다. `predictions.jsonl`에는 4개가 모두 남는다(`rules_all` 4, `predictions` 4, `valid` 2). v2 run은 8개 모두 `rules_valid`에 있고 ws 플래그를 가진다. |
| 5a 기존 smoke 불변 | PASS | `smoke-g31fl-ds-elec`의 파일 수정 시각이 전부 20:28(v2는 20:44). 이후 수정 흔적이 없다. 값은 not_found 2, duplicate 3, 적재 5. 수정 전 해시는 없어 시각과 내용 일관성으로만 판단했다. |
| 5b v2 값 | PASS | `smoke-g31fl-ds-elec-v2/run_summary.json`: not_found 0, duplicate 0, split 2, ws 5, match_rate 1.0, rules_valid 8. `identifier_conflicts` 0. `rules_all.jsonl`을 직접 읽어 같은 값을 재계산했다. 보고서의 "KG 적재 8개"는 v2의 `rules_valid` 8개와 `rules_in_ttl` 8개를 뜻한다. |
| 5c `validate`에 LLM 호출 없음 | PASS | `run.py` `revalidate()`는 `run_manifest.json`과 저장된 응답 파일만 읽고 응답 해시를 대조한 뒤 `validate_response`를 부른다. 클라이언트·캐시 호출이 없다. |
| 6 to-rdf | PASS | `run_shacl.py --data kg_with_rules.ttl --ont ontology_v1/ontology.ttl --shapes ontology_v1/shapes.ttl` 결과 `Conforms: True`. TTL을 rdflib로 읽으면 sourceQuote 8개 중 2개에 줄바꿈이 있고 `\n`으로 이스케이프돼 있다. TTL 인용 집합이 `rules_all`의 provenance 인용과 같고 `textSha256` 8개가 TTL 인용의 SHA-256과 일치한다. 출처 장부 `triple_sources.jsonl` 122행이 `rules_only.ttl`의 122 트리플을 모두 덮고 sources가 비지 않았다. |
| 7 `reserved_ids.py` 분리 | PASS | 분리는 타당하다. `test_seed_maintenance_text_not_read`(tests/test_extract_b_request.py:119)는 `request_builder.py`·`docdata.py` 소스에 `maintenance_rules`, `nodes.csv`, `kg_seed`가 없는지 보는 문자열 검사이고 약화되지 않았다. `reserved_ids.py`는 `identifier` 열만 읽고 요청 빌더는 이 모듈을 쓰지 않는다. `run.py`가 응답 검증 이후에만 부른다. |
| 8 공통 | PASS | check_raw_unchanged PASS(1121개). check_leakage 기본 폴더 PASS, 경고 0건. check_secrets 기본 PASS(198개), `src tests config` PASS(76개). 절대 경로 grep 0건. `ground_truth`·`severity`(ruleSeverity 제외) grep 0건. 단위 테스트 `Ran 301 tests ... OK`. |
| 8 미수정 확인 | PASS(제한적) | `ontology_v1/`·`.claude/`의 수정 표시는 이번 작업(20:36~20:48)보다 이른 시각이다(ontology.ttl, schema_tables.md는 14:45, `.claude`는 13:57). `shapes.ttl`은 10/12 그대로다. `harness/`는 `checklist.md`뿐이고 제외 대상이다. 이번 수정 2건의 영향은 확인되지 않았다. |

## 불합격 사유
없음.

## 미확인
- 표 셀 안에 줄바꿈이 든 인용은 전처리 표 데이터에 줄바꿈 셀이 0개라 실제 데이터로 시험할 수 없었다(표는 공백 겹침·앞뒤 공백으로만 확인). 코드상 `raw_rows`는 줄바꿈을 그대로 두고 비교한다.
- 기존 `smoke-g31fl-ds-elec`의 수정 전 해시가 없어 불변은 수정 시각으로만 확인했다.
- `ontology_v1/`·`.claude/`의 이전 수정 내용은 이 검증 범위가 아니라 열어 보지 않았다.

## 판정 외 관찰
1. **서로 다른 문서의 같은 인쇄 ID**: 현재는 `duplicate_identifier`가 붙어 두 규칙 모두 `rules_valid`에서 빠진다(가짜 run에서 확인). 설계서 §5-6은 "별개로 취급한다"고 적어, 서로 접미사 없이 두는 것이 의도인지 불분명하다. 그 규칙들이 KG 적재에서 빠진다는 점은 알고 있어야 한다. 실제 문서에서 얼마나 일어나는지는 확인하지 않았다.
2. **표 행 인용의 `quote_whitespace_adjusted`**: v2의 ws 5건 중 3건(table1 행 2, 6, 7)은 모델 인용이 ' | '로 끝나고 앞뒤 공백 제거로 끝의 공백 하나가 잘린 경우다(sourceQuote는 'ms |', 'mA |' 등 `|`로 끝남). 설계서 §5-2가 "앞뒤 공백 제거"를 정규화로 정의하므로 규칙과는 일치한다. 그러나 이 플래그는 내용이 아니라 구분자 공백 하나를 보고하는 것이라 정보 가치가 낮다. `|` 구분자는 원문 셀의 글자가 아니라 이음용 글자인데 sourceQuote에 남는다. 끝 구분자를 아예 떼거나 앞뒤 공백만 다른 경우는 플래그를 생략하는 편이 적절하다는 의견이다. 비차단이라 결과에는 영향이 없다.
3. 쪽 텍스트와 청크 텍스트가 글자 단위로 대응하지 않을 때도 `set_segment`가 호출돼 `position_unresolved`와 함께 ws 플래그가 붙을 수 있다(가짜 store 시험에서 확인). 정보 플래그일 뿐이다.
4. `quote_match_rate`는 공백 조정 일치를 일치로 센다. 이는 설계서 §5-2와 같다.
