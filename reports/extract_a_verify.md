# ④ 추출 1단계(호출 계층) 검증 보고서
- 판정: PASS (FAIL 항목 없음. 확인 한계와 판정 외 관찰은 아래)
- 방법: 코드 직접 읽기 + scratchpad의 독립 시나리오 3개(설정·요청 본문 캡처, 재시도·fallback, 기록·캐시·키 누수)를 mock과 가짜 transport로 실행. 실제 API 호출 없음. 정답 파일은 열지 않음.

## 항목별 결과
| 항목 | 결과 | 근거 |
|---|---|---|
| 1-a 모델 id 비면 거부(한국어) | PASS | 예시 설정 로드 시 `providers.gemini.models[0].id가 비어 있습니다. 모델 id를 설정 파일에 채우세요(코드에 기본값 없음).` 공백 id, 모델 목록 비어 있음도 거부 |
| 1-b temperature/top_p/top_k 설정 거부 | PASS | 최상위·모델·공급자·`fields` 경로·중첩 5곳 모두 ConfigError (config.py:92-96, 111-114) |
| 1-c timeout 기본 120초 이상 | PASS | 기본 120, 119 입력은 거부 |
| 1-d 모델명 기본값 없음 | PASS | `grep -iE "gemini-[0-9]\|gpt-[0-9]\|flash\|sol"` extract/·config/ 결과 0건. 예시 id는 ""; 키 환경변수 기본값 GEMINI_API_KEY/OPENAI_API_KEY, 키 값을 key_env에 넣으면 거부 |
| 2 샘플링 매개변수 미전송 | PASS | 두 어댑터 16개 조합(system 유무, 스키마 유무, expect_json 유무) 요청 본문·URL·헤더에서 temperature/top_p/top_k 0건. 마지막 방어 `assert_no_sampling`도 주입 시험으로 동작 확인 |
| 2 키 전달 위치 | PASS | Gemini `x-goog-api-key` 헤더, OpenAI `Authorization: Bearer`. URL에 `key=` 없고 URL·본문에 키 없음 |
| 3 재시도 시퀀스 | PASS | 지터 0일 때 1,2,4,8,16,32,60(상한), 난수 1일 때 1.25,2.5,5. 429 연속 시 호출 4회·대기 [1,2,4] |
| 3 재시도 대상 구분 | PASS | 408/429/500/503/504와 타임아웃은 재시도. 실제 어댑터에 400/402/403 응답을 주면 호출 1회·대기 0. 401·404도 재시도 없음. `insufficient_quota`가 든 429는 즉시 중단 종류로 분류 |
| 3 크레딧·인증 즉시 중단 | PASS | 402/auth는 그 공급자의 남은 모델을 건너뛰고(g1만 호출) 다음 공급자가 응답. `try_next_provider_on_auth_error=false`면 전체 중단. 키 환경변수 없으면 호출 없이 인증 오류 |
| 3 타임아웃 후 중복 청구 표시 | PASS | 타임아웃 뒤 재시도: model_call·extract_call 기록과 결과 객체 모두 `possible_duplicate_billing=true`. 429 재시도는 false |
| 4 fallback 순서 | PASS | g1 4회 → g2 4회 → o1 응답. 모델별 기록 3건 `(gemini,g1,failed) (gemini,g2,failed) (openai,o1,success)` |
| 4 전부 실패 | PASS | 예외 없이 `status=failed, skipped_document=true`, 기록에 `models_tried` 3건. 응답 텍스트는 빈 문자열 |
| 4 실제 응답 모델 구분 | PASS | extract_call 기록 `requested_model=g1`, `actual_model=o1`. model_call마다 actual_provider/actual_model/reported_model |
| 4 잘림·거부·빈 출력·JSON 아님 | PASS | mock과 Gemini 실제 어댑터(MAX_TOKENS, SAFETY, 공백 STOP, 비JSON STOP) 모두 status truncated/refused/failed, 시도 1회, 원문 raw 파일 보존, 해시 있음, `complete=False`. 다음 모델로 이동 |
| 5 기록 필드 | PASS | model_call 줄에 run_id, parent_id(=extract_call의 call_id), step_name, request_meta, 실제 공급자·모델, time, attempts, status, usage(입력·출력·생각·합계 토큰), latency_ms, response_sha256, raw_file |
| 5 요청 메타 | PASS | answer_key_supplied=false, seed_maintenance_text_supplied=false, prompt/schema/example/input 해시(모두 비어 있지 않음), doc_id, 요청 모델. 플래그가 true인 요청은 ValueError로 거부 |
| 5 원문 독점 생성 | PASS | 같은 call_id로 `write_raw` 재호출 시 FileExistsError, 기존 파일 바이트 불변. 해시는 저장된 바이트의 SHA-256과 일치 |
| 5 키 누수 없음(기록) | PASS | 가짜 키를 환경변수에 넣고 서버 오류 본문·예외 메시지에 키를 심어 실행: logs/ 아래 jsonl·raw 어디에도 키 없음, 오류 메시지는 `***`로 마스킹. imaks_data 아래 기록 폴더는 PermissionError |
| 6 캐시 키 구성 | PASS | 문서·프롬프트·Example·스키마·입력이 바뀌면 적중 실패, 모델 id·생각 수준·최대 토큰·fields가 바뀌면 키 변경 |
| 6 검증 통과 응답만 재사용 | PASS | 저장만 한 항목은 재사용 안 함(호출 재발생), `mark_validated` 뒤에만 적중. 항목 변조 시 해시 불일치로 재사용 안 함. 실패 결과는 캐시되지 않음 |
| 6 캐시 적중 기록 | PASS | `cache_hit=true, attempts=0, cache_key, actual_model` 줄이 남음 |
| 7 테스트가 네트워크 미사용 | PASS | `urlopen`은 base.py·connectivity.py 외 없음. 테스트의 `build_providers`/`extract_call`은 모두 transport 또는 providers 주입, `urlopen` 직접 사용 2곳은 `mock.patch`로 가림 |
| 7 테스트가 동작을 실제 검증 | PASS | 4개 파일 53개 테스트가 본문 캡처, 대기 시퀀스, 중복 청구, 캐시 변조, 키 누수 등을 단언. 자명한 통과(`assertTrue(True)`, skip) 없음. 위 독립 시나리오 결과와도 일치 |
| 8 check_leakage 기본 폴더 | PASS | `검사한 파일 69개 ... PASS: 금지 컬럼 없음`, 경고 0건. extract/·신규 테스트·config의 `ground_truth` grep 0건 |
| 8 check_secrets | PASS | 기본 `검사한 파일 124개, 건너뜀 0, 발견 0 / PASS`. `src tests config` 지정 `검사한 파일 48개, 건너뜀 0, 발견 0 / PASS` |
| 8 check_raw_unchanged | PASS | `PASS: imaks_data/ 원본 불변 (1121개 파일)` |
| 8 절대 경로 grep | PASS | src·tests·config에서 `C:\`, `C:/`, `/Users/`, `/home/` 0건 |
| 8 .gitignore | PASS | `/llm_logs/`(229줄), `/llm_cache/`(230줄) |
| 8 단위 테스트 | PASS | extract_a 4개 + connectivity 모듈 `Ran 67 tests ... OK`. 전체 discover는 `Ran 117 tests ... FAILED (errors=3)`인데 3건 모두 `ModuleNotFoundError`(numpy, rdflib, pyshacl)로 test_eval_f1, test_kg_convert, test_shacl 가져오기 실패. 이번 작업 범위 밖의 환경 문제이고 나머지 114개는 통과 |
| 8 connectivity.py 의도치 않은 변경 | 미확인 | extract/ 폴더 전체가 untracked라 git 기준선이 없음. 파일 수정 시각 15:48은 호출 계층 파일들(16:39 이후)보다 앞서고 test_connectivity 67개 묶음이 통과함 |
| 10 금지 경로 | PASS(단서) | harness/는 checklist.md만 수정(승인된 대상). ontology_v1/는 ontology.ttl·schema_tables.md가 수정 상태이나 수정 시각 14:45로, 호출 계층 파일(최초 15:27)보다 앞섬. 이번 작업 산출로 보이지 않으나 diff 원인은 확인하지 않음 |

## 불합격 사유와 위치
없음.

## 미확인 항목과 이유
- connectivity.py가 이번 작업으로 바뀌었는지: untracked라 비교 기준 없음(위 표).
- ontology_v1/ 수정이 이번 작업 때문이 아닌지: 시각 근거만 있음.
- 공급자 실제 필드 이름(`thinkingLevel`, `reasoning_effort` 등)과 구조화 출력 스키마 형식: 실제 API 호출 금지라 확인 불가(설계서도 미확인으로 명시).
- 전체 테스트 117개 중 numpy/rdflib/pyshacl 의존 3개 모듈은 이 환경에서 실행되지 않아 확인하지 못함.

## 판정 외 관찰
1. 정책 우려 재현됨: 1순위(g1)가 500으로 실패하고 2순위(o1) 응답이 검증 표시를 받은 뒤, 1순위가 정상이어도 같은 요청은 캐시 적중으로 o1 응답이 재사용됨(g1 호출 0회). 캐시를 체인 순서로 훑되 모델별 키라서 생김. 설계서 §6 "문서·프롬프트·Example·모델·설정 해시가 같고 검증 통과"와는 어긋나지 않으나, "1순위 모델 결과" 가정과는 다르므로 실행 결과 해석 때 기록의 `actual_model`을 봐야 함.
2. 캐시 항목의 응답 텍스트는 마스킹되지 않음(raw 파일과 jsonl은 마스킹). 모델이 응답 본문에 키를 되풀이하는 인위적 시험에서 캐시 파일에만 키가 남았음. 실제 모델이 키를 알 수 없어 위험은 낮고, llm_cache/는 git 제외.
3. `assert_no_sampling`이 JSON 스키마 속성 이름까지 검사함. 스키마에 `top_k`, `temperature` 같은 이름의 속성이 있으면 요청 전체가 PermanentError로 막힘(실제 센서 규칙 스키마에 있을 가능성은 낮음).
4. 구현자 동작 가정 대 설계서 §6:
   - 잘림·거부·빈 출력·JSON 아님은 같은 모델 재시도 없이 다음 모델: §6은 재시도 대상을 429·408·5xx로 한정하므로 부합. §5.1의 "JSON 실패하면 재시도"는 다음 모델 호출로 해석하면 충족, 같은 모델 재호출로 읽으면 어긋남(해석 필요).
   - 400도 같은 공급자의 다음 모델로: §6은 400 재시도 금지만 쓰고 "스키마 오류는 반복하지 않고 중단"도 씀. 요청 자체가 잘못된 400이면 모델 전부를 한 번씩 소모함. 모순은 아니나 "중단" 문구와는 약간 거리 있음.
   - 크레딧·인증은 해당 공급자만 중단하고 다음 공급자 시도(기본값): §6 fallback 순서와 부합하나 "중단" 문구를 전체 중단으로 읽으면 어긋남. `try_next_provider_on_auth_error=false`로 바꿀 수 있음.
   - 최대 시도 4회=같은 모델 총 시도 수: 설계서 "1초, 2초, 4초, 8초 …, 최대 4회"는 재시도 4회(총 5회)로도 읽힘. 현재 기본값은 대기 1,2,4초만 사용하고 8초는 나오지 않음. 해석 확정 필요.
   - 공급자별 필드 이름을 `[providers.X.fields]`로 바꾸고 빈 문자열이면 미전송: 설계서가 필드 이름을 구현 때 확인할 미확인 항목으로 두었으므로 부합. 시험으로 확인함.
5. `config/extract.toml`(모델 id가 채워질 실제 설정)은 .gitignore 대상이 아님. 키는 없으므로 문제는 아니나 추적 여부는 팀 합의 사항.
6. 내 시나리오의 mock이 "502" 종류를 지원하지 않아 한 줄이 BAD로 찍혔으나(시험 도구 한계), 실제 분류기에서 504·503·500은 일시 오류로 확인되어 결함이 아님.
