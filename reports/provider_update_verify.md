# provider_update 검증 보고서 (공급자 어댑터 + MAINT 충돌 처리)
- 판정: PASS
- 방법: 코드 직접 읽기 + 가짜 transport로 실제 요청 본문 캡처(임시 스크립트는 scratchpad, 저장소 미수정). 실제 API 호출 없음. 정답 파일 열지 않음. 구현 보고서는 근거로 쓰지 않음.
- 실행 환경: `.venv/Scripts/python.exe`(시스템 python에는 rdflib·pytest가 없음). 단위 테스트는 `PYTHONPATH=src python -m unittest discover -s tests`.

## 항목별 결과
| 항목 | 결과 | 근거 |
| --- | --- | --- |
| A1 Gemini 기본 Interactions, `api="generate_content"` 선택 | PASS | 기본 URL `.../v1beta/interactions`, 레거시는 `.../models/gm:generateContent`. 본문 키 `model,input,response_format,generation_config,store`. |
| A1 키는 헤더에만 | PASS | 세 경로 모두 헤더 `x-goog-api-key`만, 가짜 키가 URL·본문에 없음. OpenAI는 `Authorization`만. `extract_call` 실행 뒤 로그·캐시 6개 파일에 키 없음. |
| A1 store:false 항상 | PASS | Interactions 본문 `store: False`(기본·명시 모두). 레거시에는 해당 필드 없음. |
| A1 temperature/top_p/top_k 없음 | PASS | Gemini 2경로·OpenAI 본문 모두 0건. `base.assert_no_sampling`이 전송 직전 재검사(base.py:125, 206). |
| A1 thinking_level / response_format 형태 | PASS | `generation_config{thinking_level:"medium",max_output_tokens:500}`, `response_format{type:"text",mime_type:"application/json",schema}`. system은 input 앞에 이어 붙임(주석에 명시). |
| A2 Gemini 응답 파싱 | PASS | completed 정상. 사고 단계+텍스트 2조각 -> `'{"a":1}'`만 이어짐, 사고 문구는 `raw_body`에만 존재. incomplete=`truncated`, failed·cancelled=`failed`, queued·빈 status=`empty`. usage -> input 7/output 3/thinking 2/cached 1/total 13 정확. |
| A2 failed 재시도 안 함 | PASS | `run_with_retry`로 failed 응답 시 attempts=1, transport 호출 1회. fallback.py:56은 `failed`를 "failed" 상태로 분류. |
| A2 OpenAI 응답 | PASS | 정상, refusal=`refused`, finish_reason length=`truncated`. 본문에 `reasoning_effort:high`, `max_completion_tokens:600`(max_tokens 없음), `response_format{json_schema,strict:true}`. 추론 토큰 키 없으면 `thinking_tokens` 미생성(확인), 있으면 5로 매핑. |
| A3 오류 분류 = 설계 §6 | PASS | HTTP 400/404=Permanent, 401/402/403=QuotaOrAuth(중단), 408/429/500/503=Transient. 타임아웃은 Transient(중복 청구 표시). 잘림·거부·빈·failed는 재시도 없음. |
| A4 설정 검증 | PASS | Gemini low/medium/high만(none·minimal·xhigh 거부), OpenAI low~max 허용·none·minimal 거부, api 값 오류 거부, 모델 id 공백 거부, `temperature` 설정·샘플링 가리키는 fields 거부. 견본의 id는 `""`, 키 값 없음. `config/`에는 `extract.example.toml`만 있음(`extract.toml` 없음). `model_fingerprint`에 api 포함(api만 바꿔도 값 달라짐 확인). |
| A5 원본 스키마 불변 | PASS | `response_schema_v1.json` sha256 `963c5c5b…18e8`. 변환 후 원본 deepcopy와 동일. 저장소 추적 전(untracked)이라 이전 해시와는 비교 불가: 변경 여부는 "이번 실행 중 불변"까지만 확인. |
| A5 OpenAI 린트 4건 정확 | PASS | 스키마를 직접 읽어 독립 목록 작성: `evidence.minItems`, `table_row.minimum`, `table_col.minimum`, `coverage[].rules.items.minimum` = 4건. 린트 출력 경로 4건과 일치(과소·과다 없음). |
| A5 변환 결과가 strict 충족 | PASS | 변환본 재귀 점검: 모든 object에 additionalProperties false, properties==required, minItems/minimum 잔존 0건. |
| A5 제거 제약 명시 + 로컬 검사 유지 | PASS | schema_compat.py 머리말 4~5, 12~13줄에 "공급자용 복사본에서 뺀 제약은 로컬에서 그대로 적용", "공급자 쪽 제약만 완화" 명시. 직접 실행: `table_row=0` -> `table_row: 1 이상이어야 합니다`, `evidence=[]` -> `1개 이상`, `rules:[-1]` -> `0 이상`을 `schema_errors`가 잡음. `run.py:125,199`와 request_builder가 원본 스키마를 검증기에 전달. |
| A5 선택 속성 변환 거부 | PASS | `coverage.required`에서 reason을 뺀 스키마로 `to_provider_schema("openai")` -> `SchemaIncompatible`(자동 필수화 안 함). |
| A5 Gemini 린트 0건 근거 | PASS(주의) | 스키마가 쓰는 키워드는 type, properties, required, items, enum, additionalProperties, minItems, minimum뿐이고 모두 `GEMINI_ALLOWED`에 있음. 목록이 "보수적·미확인"이라고 주석에 밝힘. 단 `type` 배열(`["string","null"]`)은 린트가 검사하지 않으며 수용 여부도 스모크 확인 대상. |
| A6 스키마 해시 = 원본 기준 | PASS | `LLMRequest.schema_sha256`가 원본 dict의 `sha256(json.dumps(sort_keys))`와 일치. 변환본은 해시에 쓰이지 않음. |
| B1 충돌 규칙만 TTL에서 제외, 중단 없음 | PASS | SOP-003형 가짜 응답에 MAINT-01·MAINT-05 규칙 추가: 입력 4개 -> TTL 2개(RULE-*), 중단 없음, MaintenanceRule 노드 8개(seed)만 유지. |
| B2 identifier_conflicts.json / report 개수 | PASS | count 2, conflicts[]에 identifier·kind(`iri_exists_in_instances`)·seed_node_iris(`.../id/MAINT-01`)·document_id `SOP-003`·chunk_id 기록. `to_rdf_report.json` `identifier_conflicts`=2, `input_rules`=4. 0건 시험은 단위 테스트가 count 0 확인. |
| B3 Provenance·장부 고아 없음 | PASS | rules_only.ttl에서 Provenance 집합==hasProvenance 대상 집합(차집합 공집합), 장부 28줄==트리플 28개, 장부에 MAINT-01·05 언급 없음. |
| B4 입력 파일 해시 불변 | PASS | predictions/rules_all/rules_valid sha256 변환 전후 동일. |
| B5 SHACL(S7·S8) | PASS | 보고서 `shacl.conforms` True, 별도로 `run_shacl.py --data kg_with_rules.ttl` -> `Conforms: True`. |
| B6 입력 내 중복 중단 | PASS | to_rdf.py:174~179에서 `IdCollisionError`, 단위 테스트(`test_duplicates_inside_input_still_stop`) 통과. |
| B7 `test_extract_b_request.py` 수정 | PASS | 예전 "레지스트리 0개" 가정을 "entries가 list이고 각 sha256이 64자리"로 바꿈. 코드에 `example_v1`이 박히지 않았는지는 그대로 검사. 등록 해시 `edbf73a7…`가 `example_v1.txt` 실제 sha256과 일치함을 직접 확인. 의미 약화는 아님(0개 가정은 사용자 등록 후 어차피 성립 불가). 다만 "코드가 레지스트리를 쓰지 않는다"는 직접 증명은 아니고 문자열 검사에 의존. |
| C check_leakage 기본 | PASS | `PASS: 금지 컬럼 없음`(95개 검사, 경고 없음). |
| C check_secrets 기본 / `src tests config` | PASS | 152개 0건 / 71개 0건. 환경변수에 키 설정 0개(환경변수 값 검색은 실질 수행 안 됨). |
| C check_raw_unchanged | PASS | `PASS: imaks_data/ 원본 불변 (1121개 파일)`. |
| C 절대경로·`ground_truth`·`severity` grep | PASS | extract/, config/, extract 시험에서 0건(ruleSeverity 제외). |
| C connectivity.py 미수정 | PASS(제한) | 수정 시각 15:48:03로 다른 파일(16:40 이후)보다 앞섬. 저장소에 추적 전이라 내용 diff는 불가: 시각 근거만. |
| C requirements.txt 미변경 | PASS(제한) | 수정 시각 16:46:31, 이번 변경 시간대(19~20시) 이전. 추적 전이라 내용 비교는 불가. |
| C 전체 단위 테스트 | PASS | `Ran 275 tests in 217.060s` / `OK`. |
| C mock 밖 네트워크 경로 | PASS | `urlopen`은 connectivity.py와 base.urllib_transport뿐. 시험은 transport를 주입하거나 `urllib.request.urlopen`을 mock. 테스트의 `build_providers`는 모두 `transport=` 지정. |

## 불합격 사유
없음.

## 미확인 항목과 이유
- 원본 스키마·connectivity.py·requirements.txt가 "이전 대비" 변경되지 않았는지: 모두 untracked라 비교 기준이 없다(수정 시각·이번 실행 중 불변만 확인).
- 환경변수 기반 키 검색은 환경에 키가 없어 실질 수행 안 됨(패턴 검색만 유효).
- Gemini Interactions의 실제 수용 여부(필드명 `generation_config.max_output_tokens`, system 위치, 스키마 키워드, `store`, 사고 단계 type 이름, incomplete 형태)는 실제 호출 없이 확인 불가.

## 판정 외 관찰
1. 스모크에서 필요한 관찰(응답 원문 `raw_body`와 요청 본문을 비교):
   - max_output_tokens 필드명: 작은 값(예 200)으로 호출해 `status:incomplete`가 나오는지, 400 "unknown field" 여부를 본다. 400이면 `fields.max_tokens_path`를 바꿔 재시도.
   - system 위치: system_path를 비운 채(input 앞 이어붙임) 지시가 지켜지는지 + 문서의 system 전용 필드명을 확인.
   - 스키마 수용 범위: 원본 그대로(minItems/minimum/`type` 배열 포함)가 Interactions·generateContent에서 400 없이 통과하는지, OpenAI strict에서 변환본이 통과하는지. 거부 시 오류 메시지의 키워드를 `GEMINI_ALLOWED`/`OPENAI_UNSUPPORTED`에 반영.
   - store 동작: `store:false` 요청이 400 없이 받아들여지고 응답 `id`로 재조회가 안 되는지 확인.
   - 사고 단계 type 이름: 응답 `steps[].type` 값 목록을 기록(현재 코드는 `model_output`만 취하므로 이름이 다르면 빈 출력으로 실패함. 정상 응답이 `empty`로 오분류되는 것이 가장 큰 위험).
   - incomplete 응답 형태: 일부 텍스트가 steps에 들어오는지, `usage.total_thought_tokens`가 한도를 소진했는지 확인.
2. 공급자 스키마에서 `minItems/minimum`이 빠지므로, 공급자가 `table_row=0`·빈 evidence를 줄 수 있다. 이 경우 로컬 검증에서 `schema_failed`가 되고 재시도 없이 다음 모델로 간다(설계 §6). 스모크에서 이런 응답 빈도를 기록할 것.
3. 설계서·work_log 제안: 설계서 §4 또는 §6에 "공급자 전송 스키마는 원본에서 minItems/minimum을 뺀 변환본(약화), 로컬 검증기는 원본으로 검증" 한 줄 추가(현재 설계서에는 이 설명이 없고 코드 주석에만 있음). §6의 "구현 때 확인한다(미확인)" 문구를 Interactions 기본/`store:false`/OpenAI `reasoning_effort` 값 범위 반영으로 갱신하고, 위 미확인 6개를 §12에 열린 항목으로 옮길 것. work_log에는 Gemini 기본 경로 전환 날짜(2026-10-14)와 근거, MAINT 충돌 정책(제외+기록, 병합은 ⑤ 대조 후)을 기록.
4. `identifier_conflicts.json`의 `chunk_id`는 규칙의 첫 evidence 기준이다. 근거가 여러 개일 때 나머지 chunk는 기록되지 않는다(경미).
