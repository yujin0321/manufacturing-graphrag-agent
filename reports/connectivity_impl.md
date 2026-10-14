# LLM API 연결 확인 도구 구현 보고 (2026-10-14)

## 만든 파일
- `src/imaks_kg/extract/__init__.py` (빈 파일)
- `src/imaks_kg/extract/connectivity.py` (urllib만 사용, 새 패키지 없음)
- `tests/test_connectivity.py` (13개, 네트워크 미사용, urlopen mock)
- `.env.example` (키 이름 3개, 값 비움, "git에 올리지 마세요" 주석)
- `.gitignore`에 `/llm_logs/`, `/llm_cache/` 두 줄 추가(CRLF 유지)
- 수정 금지 대상(CLAUDE.md, work_log.md, ontology_v1/, harness/, .claude/, imaks_data/)은 건드리지 않았다. 커밋 없음.

## 사용법 (저장소 루트, 입력/출력은 저장소 상대 경로)
```
PYTHONPATH=src .venv\Scripts\python.exe -m imaks_kg.extract.connectivity status
... list-models --provider {gemini,openai,hf} [--contains 문자열 ...]
... ping --provider {gemini,openai,hf} --model 이름 [--json-mode] [--temperature 0]
```
- 시작 때 저장소 루트 `.env`를 읽는다(없으면 건너뜀, 이미 설정된 환경변수는 덮어쓰지 않음, 따옴표·#주석·빈 줄·`export` 처리, 지원 키 3개만 반영).
- 모델명 기본값 없음(`--model` 필수). 키가 없으면 어떤 키가 없는지만 알리고 종료(코드 1).
- 기록: `llm_logs/connectivity_YYYYMMDD_HHMMSS.json`(명령, 공급자, 모델, 상태, 지연, 토큰, 마스킹된 오류, 시각, JSON 모드·온도·max_tokens 재시도 여부). 키 미설정으로 종료한 경우에는 기록하지 않는다.
- 요청 본문은 고정 문장뿐. 단 `--json-mode`에서는 OpenAI 계열 json_object가 메시지에 "JSON" 단어를 요구하므로 `Reply with a JSON object: {"reply": "OK"}.`를 쓴다(지시한 한 문장에서 벗어난 부분, 내용은 SOP·정답과 무관).
- 출력 토큰 상한은 128(Gemini의 추론형 모델이 토큰을 생각에 쓰면 응답이 비거나 잘릴 수 있음, 그때는 JSON 파싱 "불가"로 표시됨).

## 동작 요약
- Gemini 키는 `x-goog-api-key` 헤더, OpenAI·HF는 `Authorization: Bearer`. 목록은 `pageSize=1000`과 `pageToken` 순회(최대 100페이지).
- 마스킹 `mask()`: 환경의 키 값 3개, 키 형식 정규식(AIza…, sk-…, hf_…, Bearer …, `?key=`)을 `***`로 치환. 오류 메시지·로그 JSON·출력에 모두 적용.
- 실패 출력: HTTP 상태, 마스킹된 오류 300자 이내, 힌트(키/권한, 모델명, 할당량, temperature 거부, JSON 모드 거부, 토큰 매개변수명).
- OpenAI·HF 재시도는 400 응답 본문에 `max_completion_tokens`가 있을 때만 1회, `max_tokens`로 바꿔 보냄.

## 실행한 검증과 결과
- `tests.test_connectivity`: 13개 OK. 검증 항목: (a) 오류·네트워크 오류·로그에 가짜 키 누출 없음, Gemini 키가 URL이 아니라 헤더에 있음, (b) `.env`가 기존 환경변수를 덮어쓰지 않음, (c) Gemini 페이지 순회, (d) max_completion_tokens 400 후 max_tokens 재시도(다른 400은 재시도 안 함), (e) 80줄 상한과 "외 20건", (f) status가 값·앞글자를 출력하지 않음. 가짜 키는 테스트 안에서 조합.
- 전체 단위 테스트 마지막 요약: `Ran 91 tests in 56.342s` / `OK` (`python -m unittest discover -s tests`).
- `check_secrets.py`(기본 대상) PASS, `check_leakage.py` PASS, `check_raw_unchanged.py` PASS(1121개 파일).
- `git check-ignore -v`: `.env`는 `.gitignore:151`로 무시, `llm_logs/`, `llm_cache/`는 새 줄로 무시, `.env.example`은 무시되지 않음(추적 가능).
- `status` 명령을 실제 실행해 봄. 작업 중 사용자의 `.env`가 생겼고 status는 이름별 설정됨/없음만 출력했다. **실제 API 호출은 하지 않았다**(list-models는 .env 생기기 전 키 없음으로 종료된 한 번만 실행).

## 가정
- OpenAI/HF 목록 응답은 `{"data":[{"id":...}]}`, Gemini는 `{"models":[{"name","supportedGenerationMethods"}], "nextPageToken"}`, 채팅 응답은 `choices[0].message.content`와 `usage.prompt_tokens/completion_tokens`, Gemini는 `usageMetadata.promptTokenCount/candidatesTokenCount`라고 가정했다.
- 타임아웃 60초, 재시도는 위의 1회뿐(fallback 계층은 이 도구의 범위가 아님).

## 미확인
- 지시문의 엔드포인트·매개변수 이름(Gemini v1beta, HF router `/v1/models`, `max_completion_tokens`, `responseMimeType`)은 공식 문서로 확인하지 못했고 실제 키로 한 번 돌려 봐야 맞는지 알 수 있다.
- 모델별 temperature 0 지원, JSON 모드 지원, HF 라우터가 `json_object`를 받는지는 ping 실제 호출 전까지 미확인.
- 응답 필드 이름 가정이 틀리면 "응답 형식을 해석하지 못했습니다"로 표시된다.

verifier 검증이 필요하다.
