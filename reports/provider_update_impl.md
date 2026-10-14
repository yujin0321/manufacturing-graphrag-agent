# 공급자 어댑터 갱신 구현 보고 (2026-10-14)

범위: ④ 호출 계층의 공급자 어댑터(Gemini Interactions API, OpenAI Chat Completions strict). 실제 API 호출 없음(모든 시험은 가짜 전송). 키 값은 어디에도 쓰지 않았다. `connectivity.py`, `config/extract.toml`, CLAUDE.md, work_log.md, docs/, ontology_v1/, harness/, .claude/, imaks_data/는 건드리지 않았다.

## 바꾼 파일
- `src/imaks_kg/extract/providers/gemini.py`: Interactions 어댑터가 기본, 기존 generateContent는 `api = "generate_content"`로 유지.
- `src/imaks_kg/extract/providers/openai.py`: 스키마 변환 적용, 추론 토큰 키가 없으면 건너뜀, 문서화.
- `src/imaks_kg/extract/providers/schema_compat.py` (신규): `schema_lint(provider, schema) -> [SchemaIssue]`, `to_provider_schema(provider, schema) -> (복사본, 변환 메모)`, `SchemaIncompatible`.
- `src/imaks_kg/extract/providers/base.py`: docstring만(RefusalOrIncomplete kind에 `failed` 추가 설명).
- `src/imaks_kg/extract/config.py`: `ProviderSpec.api` 추가, Gemini 필드 기본값을 api별로 분리(`GEMINI_FIELDS`), `api` 값 검증, 생각 수준 검증(Gemini low/medium/high, OpenAI low/medium/high/xhigh/max; none·minimal 거부), 캐시 지문(`model_fingerprint`)에 `api` 포함.
- `config/extract.example.toml`: 새 필드 반영(모델 id 빈 문자열, 키는 환경변수 이름만, 생각 수준 `low`).
- 시험: `tests/test_extract_a_providers.py` 재작성, `tests/extract_a_helpers.py`에 `gemini_interactions_body` 추가, `tests/test_extract_a_log_cache.py` 한 곳 수정.

## 사용법
- 설정(`config/extract.example.toml`을 `config/extract.toml`로 복사해 모델 id만 채움):
  - `[providers.gemini] api = "interactions"`(기본) 또는 `"generate_content"`.
  - `[providers.gemini.fields]`: `thinking_path`(`generation_config.thinking_level`), `max_tokens_path`(`generation_config.max_output_tokens`, 미확인 추정), `store_path`(`store`, 값은 항상 false), `system_path`(비면 system 문구를 input 앞에 이어 붙임).
  - OpenAI: `reasoning_effort`, `max_completion_tokens`, `schema_mode = json_schema | json_object | none`.
- 코드: `from imaks_kg.extract.providers.schema_compat import schema_lint, to_provider_schema`.
  `schema_lint("openai", schema)`는 SchemaIssue(path, code, message, auto_fix, changes_meaning) 목록을 돌려준다.
- 어댑터는 요청을 보낼 때 `request.response_schema`(원본)를 `to_provider_schema`로 변환한 복사본을 쓴다. `schema_sha256`(요청 메타, 캐시 키)은 계속 원본 기준이다. 로컬 검증기(validator.py)도 원본 스키마로 검사한다.

## 바꾼 점 상세
### Gemini Interactions
- `POST {base_url}/interactions`, 헤더는 `x-goog-api-key`만(Content-Type은 전송 함수가 붙임). 키는 URL·본문에 없음(시험으로 확인).
- 본문: `model`, `input`, `response_format{type:"text", mime_type:"application/json", schema}`(JSON 모드일 때), `generation_config{thinking_level, max_output_tokens}`, `store:false`(항상). temperature·top_p·top_k 없음(`assert_no_sampling` 유지, 시험 유지).
- 응답: `steps` 중 type이 `model_output`인 단계의 content에서 type이 `text`인 text를 순서대로 이음(사고 단계, 비텍스트 content 제외, 원문 `raw_body`에는 그대로 보존).
- status 분류: `completed` 정상, `incomplete` -> `truncated`(부분 텍스트 보존), `failed`/`cancelled` -> `RefusalOrIncomplete(kind="failed")`(재시도 안 함, 원문 보존, 호출 기록 상태 failed), 그 밖(`queued` 등) -> `empty`, 텍스트 없음 -> `empty`.
- 사용량 매핑: `total_input_tokens`->`input_tokens`, `total_output_tokens`->`output_tokens`, `total_thought_tokens`->`thinking_tokens`, `total_cached_tokens`->`cached_tokens`(신규 키), `total_tokens`. 응답에 없는 키는 넣지 않는다.
- HTTP 오류 분류는 기존 `classify_http_error` 그대로(429·408·5xx 일시, 400 영구, 401·402·403 인증/할당량, 타임아웃 일시+중복과금 표시).
### OpenAI
- 기존 구현이 이미 `reasoning_effort`, `max_completion_tokens`, `response_format` json_schema strict, 샘플링 없음, refusal·length 분류를 갖고 있어 유지. 추가: 스키마 변환 적용, `reasoning_tokens`가 없으면 `thinking_tokens` 키를 만들지 않음(이전에는 None).
- `max_completion_tokens -> max_tokens` 재시도는 이 어댑터에 원래 없었다(연결 확인 도구 `connectivity.py`에만 있음). 켜고 끄는 설정을 만들 대상이 없어 추가하지 않았다. `max_tokens_path` 설정으로 필드 이름만 바꿀 수 있다.
### 기존 시험이 새 형식에 의존해서 고친 곳
- `test_extract_a_log_cache.py::FakeHttpEndToEnd`: 기본 api가 interactions로 바뀌어 가짜 응답을 `gemini_interactions_body()`로 교체(이유: 이전 응답 형식은 레거시 경로 전용).
- `test_extract_a_providers.py`: 기존 Gemini 본문·응답 시험은 레거시 경로 시험(`api="generate_content"`)으로 옮기고 Interactions 시험을 새로 추가. 시험용 SCHEMA를 OpenAI strict 규칙을 지키는 형태로 바꿈(선택 속성이 있는 스키마는 이제 변환 단계에서 거부되므로).
- `connectivity.py`는 수정하지 않았다.

## 스키마 린트 결과 (현재 `prompts/response_schema_v1.json`)
OpenAI strict 규칙 위배(모두 `unsupported_keyword`, 자동 수정 가능하지만 제약을 완화하는 변환임):
1. `$.properties.rules.items.properties.evidence` : `minItems`(=1)
2. `...evidence.items.properties.table_row` : `minimum`(=1)
3. `...evidence.items.properties.table_col` : `minimum`(=1)
4. `$.properties.coverage.items.properties.rules.items` : `minimum`(=0)

위배 없음으로 확인된 규칙(OpenAI): 모든 object에 `additionalProperties:false` 있음, 모든 속성이 `required`에 있음(선택 속성 0건), `reason`의 `type`에 null이 있고 `enum`에도 null 포함, 최상위가 object, 중첩 깊이 한도 내.
Gemini 부분집합 규칙: 위배 0건(쓰인 키워드가 모두 내 허용 목록 안). 단 허용 목록 자체가 보수적 추정이라 수용 여부는 미확인.

변환 결과와 의미 영향(보고용):
- OpenAI 전송본에서 위 4개 키워드 4건을 제거한다(`to_provider_schema`가 메모로 반환). 원본 파일은 그대로. 제거로 달라지는 점: 공급자 쪽 구조화 출력이 "evidence 최소 1개", "table_row/col >= 1", "coverage.rules 항목 >= 0"을 강제하지 않는다. 이 제약은 로컬 검증기(`validator.py`, 원본 스키마 기준)가 여전히 검사하므로 위반 응답은 로컬에서 거부된다. 즉 "생성 단계 강제 약화, 검증 단계 강제 유지"다. 이 변환은 의미를 바꾸는 쪽(제약 완화)이므로 verifier 확인 대상으로 둔다.
- 자동 수정하지 않는 것: 선택 속성 -> 필수 전환(의미가 바뀜). 현재 스키마에는 해당 없음. 다른 스키마에 있으면 `SchemaIncompatible`을 내고 전송하지 않는다.
- 자동 수정하는 것: `additionalProperties:false` 추가(현재 스키마에는 이미 있어 적용 0건), null 허용 타입의 `enum`에 null 추가(현재 0건).
- Gemini로는 변환 없이 보낸다.

## 공식 문서 대비
확인한 것(지시문에 적힌 2026-10-14 문서 요약을 코드·시험에 반영): Interactions 엔드포인트·헤더·본문 필드(`model`, `input`, `response_format`, `generation_config.thinking_level`, `store`), 응답의 `steps`/`status`/`usage` 필드 이름, OpenAI Chat Completions 필드 이름과 refusal·length 규칙. 나는 문서를 직접 다시 열어보지 않았고 요약을 근거로 했다.
못한 것(미확인):
- `generation_config.max_output_tokens` 필드 이름(설정으로 변경 가능).
- Interactions에서 system 문구를 넣는 전용 필드(현재는 input 앞에 이어 붙임; `fields.system_path`로 바꿀 수 있음).
- `response_format.schema`가 어떤 JSON Schema 키워드를 수용하는지, 허용 목록의 정확성.
- OpenAI strict가 `minimum`/`minItems`를 실제로 거부하는지(거부한다고 가정하고 제거). 거부하지 않는다면 제거는 불필요한 완화다.
- `store:false`가 요청에서 수용되는지, `status` 값 이름 일치, `incomplete`가 실제로 최대 토큰 도달 때 오는지.
- Interactions 오류 응답 본문의 형태(기존 `error.message` 추출 규칙을 가정). 인증·할당량 판별 문구는 기존 휴리스틱 그대로(미확인).
- thinking_level이 Gemini 모델 id별로 모두 low/medium/high만 받는지.

## 가정
- 위 미확인 필드 이름 3개(max_output_tokens, system 위치, 린트 허용 목록)는 설정 또는 상수로 바꿀 수 있다.
- failed/cancelled는 같은 모델 재시도 없이 다음 모델로 넘어가는 것이 맞다고 가정(잘림·거부와 같은 취급).
- 캐시 지문에 `api`를 넣었으므로 api를 바꾸면 기존 캐시 응답은 재사용되지 않는다(의도).

## 스모크에서 확인해야 할 항목 (모두 미확인)
1. Gemini Interactions 요청이 400 없이 수용되는가(특히 `generation_config.max_output_tokens`, `store`, `response_format.schema`).
2. 사고 단계가 섞인 실제 `steps` 구조와 `type` 이름(`thought` 계열 외 다른 이름이 `model_output`으로 오는지).
3. 실제 `incomplete` 응답에서 부분 텍스트와 `usage.total_thought_tokens`가 오는지.
4. OpenAI strict가 변환본(키워드 4건 제거)을 수용하는지, 원본(제거 전)을 보냈을 때 거부하는지(제거 필요 여부 판정용).
5. 두 공급자의 `reasoning_effort`/`thinking_level` low가 수용되는지, 추론 토큰 기록 여부.
6. system 문구를 input에 붙여 보낸 결과가 system 전용 필드 사용과 품질이 비슷한지(필드 확인 후 전환 검토).

## 직접 실행한 결과
- 전체 단위 테스트: `Ran 275 tests in 215.201s` / `OK`
- `check_leakage.py` 기본 폴더: `PASS: 금지 컬럼 없음`, 경고 0건
- `check_secrets.py` 기본: `PASS` (검사 파일 151개, 추가 0건); `src tests config`: `PASS` (71개, 추가 0건)
- `check_raw_unchanged.py`: `PASS: imaks_data/ 변경 없음 (1121개 파일)`
- 절대 경로 grep(`providers/`, `config.py`, `config/`, 관련 테스트): 일치 0건
- 금지어(정답 파일 이름, 심각도 단독어) 검색: 변경한 코드·설정·시험에서 0건

## 알려진 한계 / 미결정
- Interactions의 스트리밍, 도구, 이전 상호작용 이어쓰기(`previous_interaction_id`)는 쓰지 않는다.
- 린트 허용/불허 키워드 목록은 공식 문서 요약에 근거한 상수라 문서 변경 시 갱신이 필요하다.
- `docs/extraction_design.md` §6의 "필드 이름은 구현 때 확인한다(미확인)" 문구와 §0 표는 이번 갱신을 반영하도록 사용자가 고칠 것을 제안한다(내가 수정하지 않음). work_log.md에도 이번 변경(api 선택, store false, 스키마 변환 정책)을 기록할 것을 제안한다.

verifier 검증이 필요하다.
