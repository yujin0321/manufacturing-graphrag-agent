# 점검 스크립트 2개 구현 보고서 (check_secrets, check_gt_overlap)

## 만든 파일
- `.claude/skills/stage-check/scripts/check_secrets.py`
- `.claude/skills/stage-check/scripts/check_gt_overlap.py`
- `tests/test_check_secrets.py` (6개 테스트), `tests/test_check_gt_overlap.py` (6개 테스트)
- 이 보고서. 기존 스크립트, SKILL.md, agents, harness, CLAUDE.md, ontology_v1/는 수정하지 않았다. 커밋하지 않았다.

## 사용법
```
python .claude/skills/stage-check/scripts/check_secrets.py [폴더 또는 파일 ...]
python .claude/skills/stage-check/scripts/check_gt_overlap.py [--gt P] [--gt-column 열1,열2] [--sop P] [-n 6] [--threshold 0.3] 대상...
```
종료 코드: 둘 다 0 문제 없음, 1 발견. 2는 check_gt_overlap에서 정답/SOP 파일 없음·열 없음·인자 오류(미확인), check_secrets에서는 사용하지 않는다.

## 탐지 규칙
check_secrets
- 기본 대상: `git ls-files` 추적 파일 + kg_build, reports, llm_logs(있으면). 폴더는 재귀, `.git .venv venv imaks_data __pycache__ node_modules` 제외.
- NUL 포함 이진 파일, UTF-8로 못 읽는 파일은 건너뛰고 개수를 요약에 표시. 한 줄씩 스트리밍으로 읽는다.
- (1) 환경변수 GEMINI_API_KEY, OPENAI_API_KEY 값(8자 이상) 정확 일치. (2) Google `AIza...{35}`, OpenAI `sk-...{20,}`(앞 글자가 영숫자면 제외해 task- 같은 단어 오탐 방지), `Bearer ...{20,}`, `api_key|secret|token` 대입(값 16자 이상 따옴표 문자열).
- 허용: os.environ, getenv, `${`, `<...>`, YOUR_, xxxx 포함 값, 환경변수 이름 형태(대문자_대문자, GEMINI_API_KEY 등)인 값.
- 출력은 상대 경로:줄:패턴 이름만, 최대 50건 후 "외 N건". 키 값과 환경변수 값은 출력하지 않는다. 마지막 `검사한 파일 N개, 건너뜀 M개, 발견 K건`과 PASS/FAIL.

check_gt_overlap
- 정답 파일은 `imaks_data` 안에서 파일명(ground_truth.csv)으로 찾는다. 헤더(이름만 확인): `ruleId,class,station,sensor,sensorType,condition,action,severity,critHi,warnHi,critLo,warnLo,unit,source`.
- 규칙 문장 열 판단 근거: 헤더 이름상 자연어 텍스트 열은 `condition`, `action` 두 개뿐(나머지는 ID, 분류, 수치, 단위, 출처). 단일 "문장" 열이 없어 `--gt-column` 기본값을 `condition,action`(쉼표로 여러 열)로 했다. 열마다 따로 n-gram을 만든 뒤 합친다(열 경계는 넘지 않음). 행 내용은 읽어서 출력하지 않았다.
- 정규화: 소문자, 영숫자 외 문자(밑줄 포함)는 공백, 연속 공백 하나. 단어 n-gram(기본 6). SOP 원문 n-gram은 pages.jsonl의 text_normalized를 페이지별로 만든다(페이지 경계는 넘지 않음). 대상 파일은 줄 단위 n-gram(줄 경계는 넘지 않음).
- 규칙별 고유 n-gram = 정답 n-gram - SOP n-gram. 대상 파일 n-gram 집합과의 교집합 비율이 임계(기본 0.3) 이상이면 의심. 파일은 한 번만 읽고 집합 연산으로 비교.
- 출력: 파일 경로, 정답 행 번호(1부터), 비율(소수 2자리), 겹침 개수. 최대 30건 후 "외 N건". 정답 파일 없음은 "정답 파일이 없어 검사하지 못함(미확인)" + 종료 2. 정답 파일과 SOP 파일 자체는 대상에서 제외한다.

## 실행한 검증과 결과
- 단위 테스트 전체(`PYTHONPATH=src .venv\Scripts\python.exe -m unittest discover -s tests`): `Ran 70 tests in 45.200s` / `OK`. 새 테스트 12개 포함.
- 테스트 범위: 가짜 키(테스트 안에서 조합) FAIL, 환경변수 이름만은 PASS, 출력에 키·환경변수 값 없음, 50건 상한, 이진·비UTF-8 건너뜀, 제외 폴더, 환경변수 값 검색(8자 미만 무시). overlap은 임시 가짜 정답·SOP로 고유 문구 복사 FAIL, SOP만 복사 PASS, 출력에 정답 문장 없음, 정답 없음 종료 2, 정규화, -n·임계 옵션, 30건 상한.
- 실제 저장소 실행 1 (`check_secrets.py` 기본 대상): `검사한 파일 75개, 건너뜀 0개, 발견 0건`, PASS, 종료 0. 이 셸에는 두 환경변수가 설정돼 있지 않아(0개) 환경변수 값 검색은 실제로는 수행되지 않았다.
- 실제 저장소 실행 2 (`check_gt_overlap.py src docs`): `정답 규칙 86개, 고유 n-gram이 있는 규칙 45개, 검사한 파일 12개, 기준 초과 0건`, PASS, 종료 0. 아직 프롬프트가 없어 동작 확인 용도다.

## 가정
- 정답 규칙 문장 = `condition`+`action` 열 (헤더 이름만으로 판단).
- 86개 중 41개 규칙은 6-gram 기준으로 고유 n-gram이 없어(문장이 짧거나 SOP와 겹침) 이 방식으로는 복사 여부를 잴 수 없다.
- 임계 0.3, n=6은 요청 기본값을 그대로 썼다. 적정성은 검증하지 않았다.

## 미확인
- 환경변수 값 검색을 실제 키로 돌려 보지 않았다(테스트에서 가짜 값으로만).
- 호출 기록(llm_logs) 같은 큰 파일에서의 속도.
- 정답 파일이 아닌 실제 프롬프트·Example이 생겼을 때의 오탐 수준.
- 고유 n-gram이 없는 41개 규칙의 구체 내용(보지 않음).

## 한계
- 키 탐지는 형식 기반이라 형식이 다른 키(Azure 등)와 여러 줄로 쪼개진 키는 못 잡는다. 허용 규칙 때문에 대문자_밑줄 형태의 실제 값도 통과할 수 있다. git 이력 속 과거 키는 보지 않는다(추적 파일 현재 상태만).
- `.env` 등 미추적 파일은 기본 대상이 아니다(.gitignore 대상이 맞는지는 별도 확인 필요, 인자로 직접 지정 가능).
- 겹침은 단어 n-gram 표면 일치만 본다. 말바꿈(paraphrase)한 복사는 못 잡는다. 줄/페이지 경계를 넘는 n-gram은 세지 않는다. 한 규칙의 짧은 고유 부분만 복사하면 비율이 낮아 놓칠 수 있다.
- 수치·ID 위주 문구는 정규화 후 짧아 n-gram이 안 생길 수 있다.

## 수정안 제안 (적용하지 않음, 승인 필요)
1. SKILL.md 등록 (스크립트 목록에 두 줄 추가)
   - 전: (check_leakage.py, check_raw_unchanged.py, run_shacl.py만 나열) 
   - 후: `check_secrets.py [경로...]` API 키·토큰 검색, 발견 건수와 파일:줄만 출력 / `check_gt_overlap.py [옵션] 대상...` ④ 프롬프트·Example·청킹과 정답 규칙의 고유 n-gram 겹침, 정답 파일 없으면 종료 2(미확인)
   (SKILL.md의 실제 문구를 이번에 대조하지 않아 위치는 미확인)
2. harness/checklist.md 공통 절 12행 끝
   - 전: `(키 패턴과 환경변수 값을 찾는 스크립트 한 번으로 확인하고 발견 건수와 파일명만 보고한다. 호출 기록 파일을 통째로 읽지 않는다)`
   - 후: `(\`check_secrets.py\`를 한 번 실행하고 마지막 요약 줄(검사/건너뜀/발견)과 발견 시 파일:줄만 보고한다. 호출 기록 파일을 통째로 읽지 않는다)`
3. harness/checklist.md ④ 54행 중 "겹침은 n-gram 비교 스크립트로 계산해"
   - 후: `겹침은 \`check_gt_overlap.py\`로 계산해 마지막 요약 줄과 의심 (파일, 행번호, 비율)만 보고한다(종료 2는 미확인으로 적는다)`
4. .claude/agents/verifier.md
   - 추가 문구: `정답 파일(ground_truth.csv)은 check_gt_overlap.py 실행에서만 읽는다. 직접 열어 규칙 문장을 보고서·로그에 옮기지 않는다. API 키 검색은 check_secrets.py 한 번으로 하고 값을 출력하지 않는다.`

verifier 검증이 필요하다.
