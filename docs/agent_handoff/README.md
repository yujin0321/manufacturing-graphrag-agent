# Agent → End-to-End(XAI) 백엔드 인계

작성: 2026-11-14. 기준 main `020c863`. 공유 브랜치 `codex/agent-e2e-xai-20261113`.

추가 개선: [판단 근거 구조화·실패 검사·선택적 한 번 보완](DECISION_EVIDENCE.md). 기존 실제 실행 결과와 46개 인계 검사는 당시 기록으로 유지하고 새 개발 검사를 구분한다. 기존 복원 ZIP은 새 검사에 그대로 사용할 수 있다.

## 역할과 완료 범위

예원 담당은 질문 라우팅·사건/문서/KG 도구 연결·답변 생성·근거 검토·XAI 응답 제공·백엔드 검증이다. UI 레이아웃, 화면 구현과 최종 시각 점검은 UI 담당자 영역이다. 저장소의 HTML은 기존 로컬 참고 화면이며 필수 UI 설계가 아니다.

| 순서 | 수행 결과 | 근거 |
|---|---|---|
| 1. 응답 데이터 점검 | 기존 4개 실행의 원문/해시·관측·실행 IR·저장 간선·인용·응답 매핑 점검. 보강 후 근거 토큰 표시 수정 | [기계 판독 점검 결과](response_audit.json) |
| 2. 기본 설정 확정 | `main_v3_1` + `auto`를 코드의 기본값으로 고정. 대안은 명시 선택 | [기본 설정](defaults.json), `team_runtime.DEFAULTS` |
| 3. 대표 시연 구성 | 사건→문서→KG 전수 조회→답변 불가의 4개 기본 사례와 성호 대안 사례 1개 | [시연 순서](SCENARIOS.md) |
| 4. 공유 준비 | API 명세, 실행·복원 스크립트, 작은 의존성 목록, 별도 로컬 런타임 ZIP | [API 인계](API.md), 아래 실행 순서 |

이 점검은 화면 모양이나 자연어의 모든 문장을 독립적으로 평가하지 않는다. 기록된 AI 검토 통과와 코드 검사를 구분한다. 과거 점수·입력 노출 이력은 유지하며, 이번 결과를 새 정확도나 새 인과관계 발견으로 표현하지 않는다.

## 기본 설정을 선택한 이유

v3.1은 고정 입력에서 준비·봉인·SHACL·사건 도구 연결을 검증한 공통 경로다. `auto`는 문서의 BM25·벡터 융합과 출처 필터를 사용한다. 이 선택은 인계와 시연의 일관성을 위한 운영 기본값이다. 모든 대안보다 우수하다고 실험으로 확정한 선택은 아니다. 센서 전체·규칙 집합·생산 방향 경로 질문은 문서 방식 선택과 별도로 고정 KG 전수 질의를 사용한다.

유진·예원·성호의 main 공개 코드는 해당 역할에서 재사용하고, 수민은 공개 보고서의 분석을 설계에 반영했다. 수민 미공개 실행 코드와 성호 11/9 정정 실험을 그대로 재현한 것은 아니다. 성호의 규칙별 후보 55/89개와 v3.1의 묶음 사건 17개는 단위가 달라 개수로 우열을 판단하지 않는다. 상세 [통합 범위](../TEAM_AGENT_APP_20261113.md).

## UI 담당자에게 전달할 두 가지

1. 이 개발 브랜치의 코드·문서.
2. 별도 파일 `imaks_agent_runtime_20261114.zip` (약 5.12 MB, 복원 후 약 28 MB).

ZIP은 작성자 PC의 `kg_build/agent_handoff_20261114/`에 있다. 원문 청크·전처리 입력·기존 벡터·봉인 산출물·대표 실행 기록·토크나이저 캐시를 담았다. API 키와 모델 가중치는 없다. [패키지 영수증](package_receipt.json)으로 SHA-256을 확인한다. 프로젝트 공개 정책에 따라 원문·벡터·API 캐시는 Git에 올리지 않으므로 **브랜치만 내려받아서는 로컬 데이터가 준비되지 않는다**. ZIP을 팀원에게 별도 전달한다.

ZIP이 공개 서버나 Git에 업로드된다는 뜻은 아니다. 원본 PDF, 정답 이벤트 주입 자료, 정답 CSV, 제외한 사건 17건 연계 재평가를 이 패키지에 넣지 않았다. 기록 재생은 API 호출이 없다.

## 팀원 PC 실행 순서

Python 3.11 이상과 Git을 사용한다. 프로젝트 폴더를 가져오고 개발 브랜치를 선택한다.

```powershell
git clone --branch codex/agent-e2e-xai-20261113 https://github.com/yujin0321/manufacturing-graphrag-agent.git
cd manufacturing-graphrag-agent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r docs/agent_handoff/requirements.txt
```

의존성 설치에는 인터넷과 일반 Python 패키지 저장공간이 필요하다. 로컬 LLM·SBERT 가중치를 설치하지 않는다.

팀원에게 받은 ZIP 경로로 복원한다. 아래 다운로드 경로는 자신의 파일 위치로 바꾼다.

```powershell
.\.venv\Scripts\python.exe scripts/agent_handoff.py restore "$env:USERPROFILE\Downloads\imaks_agent_runtime_20261114.zip"
.\.venv\Scripts\python.exe scripts/agent_handoff.py audit
.\.venv\Scripts\python.exe scripts/run_xai_agent.py --serve --read-only --port 8770
```

복원은 모든 파일 해시·상대 경로·기존 파일 충돌을 먼저 검사한다. 같은 파일은 유지하며, 내용이 다른 기존 파일은 덮어쓰지 않고 중단한다. `audit`은 외부 API 없이 저장 자료를 확인한다. 서버는 실행한 터미널을 닫으면 종료될 수 있으므로 인계 시 실행 방법도 안내한다.

읽기 전용 서버는 API 키 없이 저장 결과를 제공하고 새 생성 요청은 HTTP 503으로 거절한다. UI 개발은 이 모드로 시작한다. `http://127.0.0.1:8770/api/team-config`와 `/api/history`, `/api/run/<ID>`를 사용할 수 있다.

새 질문을 실제 생성할 때만 해당 팀원의 `OPENAI_API_KEY` 환경변수 또는 로컬 `.env`를 설정하고 `--read-only` 없이 실행한다. 이 경우 모델·질의 임베딩 비용이 발생할 수 있다. 키를 Git·ZIP·채팅에 넣지 않는다.

## 검증과 재현 명령

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m unittest tests.test_agent_handoff tests.test_incident_agent tests.test_team_app tests.test_agent_v4_1 tests.test_agent_contract tests.test_retrieval_v5 tests.test_team_app_server -v
```

46개 검사 통과. 기존 API 실행 4개는 모두 완료됐고, 이번에 추가한 답변 불가 사례는 모델 호출 0회다. 이번 마무리 작업에서 유료 API 재실행은 하지 않았다. 더 자세한 검증·인계 기록은 [완료 보고서](COMPLETION.md)를 따른다.
