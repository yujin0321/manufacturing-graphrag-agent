# 4단계 LLM 추출 - 1단계(호출 계층) 구현 보고

날짜 2026-10-14. 범위: 호출 계층만(요청 빌더, 검증기, TTL 변환, 사람 검토 기록은 2단계). 실제 API는 한 번도 호출하지 않았다.

## 만든 파일
- `config/extract.example.toml`: 설정 견본(모델 id 빈 문자열, 키 없음)
- `src/imaks_kg/extract/config.py`, `retry.py`, `fallback.py`, `callog.py`, `cache.py`, `client.py`
- `src/imaks_kg/extract/providers/__init__.py`, `base.py`, `gemini.py`, `openai.py`, `mock.py`
- 테스트: `tests/extract_a_helpers.py`, `tests/test_extract_a_config.py`, `_providers.py`, `_retry_fallback.py`, `_log_cache.py`
- 기존 `connectivity.py`는 수정하지 않았다(마스킹 함수 `mask`만 재사용).

## 사용법
1. `config/extract.example.toml`을 `config/extract.toml`로 복사하고 각 공급자의 모델 id를 채운다(비어 있으면 `ConfigError`, 어떤 항목이 빈지 한국어로 알림). 키는 `.env`/환경변수(`GEMINI_API_KEY`, `OPENAI_API_KEY`).
2. 호출자(2단계)가 `LLMRequest(prompt, system, response_schema, doc_id, prompt_sha256, example_sha256, ...)`를 만들어 `extract_call(load_config(), request)`를 부른다. 결과 `ExtractResult`: `status`(success/failed), `text`, `provider`, `model_id`, `cache_hit`, `cache_key`, `skipped_document`, `failure_reason`, `possible_duplicate_billing`, `raw_files`, `calls`(모델별 기록).
3. 검증기는 통과시킨 뒤 `result.mark_validated("검증기이름")`을 부른다. 그 전에는 캐시를 재사용하지 않는다.
- 테스트: `PYTHONPATH=src python -m unittest discover -s tests`. 시험용으로 sleep, 난수, 전송 함수, 공급자 객체(`providers=`)를 주입할 수 있다.

## 입력/출력 경로
- 입력: 설정 TOML(저장소 루트 기준), 환경변수. 출력: `llm_logs/calls_<run_id>.jsonl`(호출마다 한 줄), `llm_logs/raw/<call_id>.txt`(응답 원문, 독점 생성), `llm_cache/<key>.entry.json`과 `<key>.validated.json`. 둘 다 `.gitignore`에 `/llm_logs/`, `/llm_cache/`로 이미 있음(확인함). imaks_data 아래로는 기록 거부.

## 설계서 대비
구현함:
- 6장 설정 항목 전부(공급자 순서, 모델 목록, 생각 수준 기본 low, max_output_tokens, timeout_s 기본 120이며 120 미만은 거부, 키 환경변수 이름, 재시도 4회/1초/60초/지터, 폴더). `temperature`, `top_p`, `top_k`가 설정 어디에 있어도 거부. 키 이름 칸에 키 값처럼 보이는 문자열을 넣어도 거부.
- 요청 본문에 샘플링 매개변수 없음: 본문 빌더가 만들지 않고, 전송 직전에 한 번 더 검사(`assert_no_sampling`). 두 공급자 모두 테스트로 확인.
- 재시도: 429/408/5xx/타임아웃만 지수 백오프+지터(대기 = min(60, 1*2^(n-1)*(1+0.25*난수))). 400/402/403 재시도 없음. 크레딧/인증 오류는 즉시 중단.
- fallback: 같은 모델 재시도 -> 같은 공급자 다음 모델 -> 다음 공급자 -> 전부 실패 시 `status=failed`, `skipped_document=true`(예외 없음). 크레딧/인증 오류는 그 공급자의 남은 모델을 건너뛰고, 다음 공급자는 `try_next_provider_on_auth_error`(기본 true)로 정함. 예기치 못한 예외도 영구 오류로 바꿔 기록.
- 호출 기록: run_id, parent_id(모델 호출 줄의 부모는 `extract_call` 줄), step_name, 요청 메타(`answer_key_supplied: false`, `seed_maintenance_text_supplied: false`, 프롬프트/스키마/Example/입력 해시, 문서 ID, 요청 모델), 실제 사용 모델과 서버가 알려준 모델, 시각, 시도 횟수, 재시도 사유, 대기 목록, 상태(success/failed/refused/truncated), 토큰(입력/출력/생각/합계), 지연, 응답 SHA-256, `possible_duplicate_billing`. 응답 원문은 'xb' 모드로 저장(같은 이름이면 `FileExistsError`). 모든 기록은 직렬화 후 마스킹.
- 캐시: 키 = 문서 ID, 프롬프트 해시, Example 해시, 스키마 해시, 입력 전체 해시, 모델 지문(공급자, 모델, 생각 수준, 출력 한도, 필드 설정)의 SHA-256. 검증 표시는 별도 파일이며 저장 응답 해시가 달라지면(변조) 재사용하지 않음. 캐시 적중도 호출 기록에 남음.
- 잘림/거부/빈 출력/JSON 아님: 완료로 취급하지 않고(`complete=False`) 재시도 없이 다음 모델로 넘어가며, 원문은 raw 파일에 보존.
- 요청에 `answer_key_supplied`나 `seed_maintenance_text_supplied`가 true이면 `extract_call`이 호출을 거부(ValueError).

못한 것/하지 않은 것:
- 요청 빌더, 스키마/프롬프트 파일, 2단계 검증, 사람 검토 기록은 하지 않음(범위 밖).
- 실제 API 호출 없음. 따라서 공급자 어댑터의 실제 서버 호환성은 미확인.
- 서버가 주는 Retry-After 헤더는 사용하지 않음(고정 백오프만).
- `config/extract.toml`은 만들지 않음(모델 id 미정).

## 공급자별 필드 이름: 미확인
공식 문서를 이 환경에서 확인하지 못했다. 아래는 가정이며 모두 `[providers.X.fields]`에서 바꿀 수 있고, 빈 문자열이면 해당 필드를 보내지 않는다.
- Gemini: REST `generateContent`, 키 헤더 `x-goog-api-key`(연결 확인에서 동작), `systemInstruction`, 생각 수준 `generationConfig.thinkingConfig.thinkingLevel`(미확인), 출력 한도 `generationConfig.maxOutputTokens`(연결 확인에서 동작), JSON `responseMimeType`(연결 확인에서 동작), 스키마 `generationConfig.responseJsonSchema`(미확인; `responseSchema`일 수도 있음). 응답 `finishReason`, `usageMetadata.thoughtsTokenCount`도 미확인.
- OpenAI: `/v1/chat/completions` 선택. 이유: 연결 확인에서 실제로 동작했고(`max_completion_tokens`, `response_format: json_object`) 요청/응답 모양이 단순함. Responses API는 입력/출력 항목 구조가 달라 파서가 복잡. 생각 수준 `reasoning_effort`(미확인), 스키마 `response_format.type=json_schema`(미확인; `schema_mode`로 `json_object`/`none` 전환 가능). 응답의 `completion_tokens_details.reasoning_tokens`, `message.refusal`도 미확인.
- 크레딧/할당량 판별은 문구 휴리스틱(`insufficient_quota` 등)과 401/402/403만 사용. 429는 속도 제한과 일일 할당량을 구분할 수 없어 일시 오류로 재시도한다. 이 문구들은 미확인.

## 가정
- 최대 시도 4회는 같은 모델에 대한 총 시도 수(대기 1, 2, 4초). 설계의 "최대 4회"가 재시도 횟수일 가능성도 있어 설정값으로 둠.
- `max_output_tokens` 코드 기본값 16384는 자리표시이고 스모크에서 실측해야 함.
- 400(영구 오류)은 같은 공급자의 다음 모델로 넘어간다(모델별 매개변수 거부일 수 있어서). 전 모델이 거부하면 최종 실패.
- 타임아웃만 `possible_duplicate_billing`을 켠다(연결 오류, 5xx는 켜지 않음).

## 한계
- 캐시 조회는 체인 순서대로 모델별 키를 훑는다. 1순위가 죽어 2순위 응답이 검증된 뒤에는 1순위가 살아나도 2순위 응답이 재사용될 수 있다(결과에 모델이 기록됨. 기준선 고정 정책과 맞는지 정책 확인 필요).
- 응답 원문의 마스킹이 키 모양 패턴(`sk-...`, `AIza...`)을 가리므로, SOP 원문에 비슷한 문자열이 있으면 원문이 바뀔 수 있다(`raw_masked`로 표시).
- 호출 기록 줄이 동시 쓰기에 안전한지는 확인하지 않음(단일 프로세스 가정).

## 2단계에 넘기는 인터페이스
- 입력: `LLMRequest`(문자열 그대로 전달). 해시 칸(`prompt_sha256`, `example_sha256`)은 빌더가 파일 해시로 채운다. 스키마는 `response_schema` dict.
- 출력: `ExtractResult.text`(모델 출력 문자열), `raw_files`(로그 폴더 기준 상대 경로), `calls`(모델별 상태/토큰/지연), `cache_key`.
- 검증기 의무: 통과하면 `mark_validated()`; 실패하면 호출하지 않음(재시도 정책은 2단계 몫. 설계 5장 1번).
- 모델별 구분: `result.provider/model_id`와 호출 기록의 `actual_model`로 채점 때 분리 가능.

## 설계서 수정 제안(docs/는 수정하지 않음)
- 10장 파일 위치: `config/extract.example.yaml` -> `config/extract.example.toml`(TOML 사용).
- 0장/6장: 요청 메타 플래그 이름을 `answer_key_supplied`로(조정자 진행 중), 호출 기록 구조(모델 호출 줄 + `extract_call` 부모 줄)와 상태 값 4종(success/failed/refused/truncated) 명시.
- 6장: 잘림/거부/JSON 아님은 같은 모델 재시도 없이 다음 모델로 넘어간다는 규칙, 400은 다음 모델로 넘어간다는 규칙을 명시할지 결정 필요.
- `.gitignore`에 `config/extract.toml`을 넣을지 결정(키는 없지만 로컬 설정).

## 직접 실행한 확인
- 전체 단위 테스트 마지막 줄: `Ran 173 tests in 51.401s` / `OK` (신규 extract_a 테스트 포함. 1회 실패는 테스트 도우미의 가변 기본값 공유 버그였고 수정 후 통과).
- `check_leakage.py` 기본 실행: `PASS: 금지 컬럼 없음`, 경고 0건(`answer_key_supplied`로 이름을 바꾼 뒤. 이전 경고 3건은 모두 이 플래그 이름 단어였고 `src/imaks_kg/extract/`와 신규 테스트에 해당 단어가 더 이상 없음을 grep으로 확인).
- `check_secrets.py` 기본 실행: `검사한 파일 123개, 건너뜀 0개, 발견 0건` PASS. 참고: 기본 실행은 git 추적 파일 중심이라 신규 미추적 파일은 폴더를 직접 지정해 별도로 실행했다(`src tests config`): 1건 발견, `tests/test_eval_f1.py:266`(내가 만든 파일이 아님, 평가기 테스트의 오탐 가능성, 미확인). 내가 만든 파일에서는 발견 없음.
- `check_raw_unchanged.py`: `PASS: imaks_data/ 원본 불변 (1121개 파일)`.
- 절대 경로 grep(`C:\`, `/Users/`, `/home/`) 신규 코드/테스트/설정: 0건.
- `.gitignore`에 `/llm_logs/`, `/llm_cache/` 이미 있음.
- 커밋하지 않았다. CLAUDE.md, work_log.md, ontology_v1/, harness/, .claude/, docs/, requirements.txt는 수정하지 않았다.

verifier 검증이 필요하다.
