# UI 담당자를 위한 API 계약

별도 업로드 CSV를 분석할 때는 [CSV·시계열 API](SENSOR_ANALYSIS_API.md)를 사용한다. 일반 질문 Agent와 별도이며 `--allow-local-analysis`로 명시 활성화한다. 일반 읽기 전용 실행·기존 저장 결과 계약은 아래와 같다.

백엔드: `python scripts/run_xai_agent.py --serve --read-only --port 8770`.
현재 서버는 단일 사용자 로컬 개발용이다. JSON은 UTF-8, 응답은 `Cache-Control: no-store`다. 외부 배포용 인증 서버·CORS 설정을 포함한 배포 구성은 별도 작업이다.

## 연결 순서

1. `GET /api/session`으로 세션 토큰과 생성 가능 여부를 받는다.
2. `GET /api/team-config`의 `defaults`로 두 선택 메뉴의 기본값을 설정한다.
3. `GET /api/incidents?profile=main_v3_1`으로 해당 방식의 과거 후보를 표시한다.
4. `GET /api/history`로 저장 실행을 읽는다. `integration.version`, `detector_profile`로 구분한다.
5. 저장 답변은 `GET /api/run/<실행 ID>`로 읽는다. 새 질문을 생성하려면 읽기 전용 서버를 종료하고 일반 서버로 실행한다.

브라우저 요청은 `http://127.0.0.1:8770`과 같은 origin으로 연결한다. `localhost`와 `127.0.0.1`은 이 서버에서 같은 호스트로 취급하지 않는다. 별도 프론트엔드 개발 서버에서 직접 CORS 요청을 허용한 구성은 아니다. 프론트엔드의 같은 origin에서 서버 측 API 프록시를 구성하거나 같은 origin으로 제공하는 방법은 UI 담당자와 결정한다.

## 엔드포인트

| 메서드·경로 | 용도 | 새 API 비용 |
|---|---|---|
| GET `/api/session` | `csrf_token`, `generation_enabled` | 없음 |
| GET `/api/team-config` | `defaults`, 탐지·문서 방식 목록, 기여 범위 | 없음 |
| GET `/api/incidents?profile=<ID>` | 봉인된 과거 후보, 상관 후보, 주의사항 | 없음 |
| GET `/api/history` | 최근 저장 실행 최대 50개, 각 실행의 선택 설정 | 없음 |
| GET `/api/run/<ID>` | 아래의 화면 전달 응답 | 없음 |
| GET `/api/decision-evidence/<ID>` | 저장 사건의 관측·규칙·출처와 지원되는 단순 발동 조건을 별도로 재점검. 원 답변 유지 | 없음 |
| GET `/api/claim-catalog/<ID>` | 저장 사건에서 현재 허용되는 주장 목록. 과거 답변 문장의 검증 결과는 아님 | 없음 |
| GET `/api/claim-paths/<ID>` | 게시된 주장 또는 현재 허용 목록의 근거 경로. `path_scope`와 과거 문장 미검증 표시 확인 | 없음 |
| GET `/api/rule-explanations/<ID>` | 과거 사건의 현재 규칙 경계·사후 종료 점검. 원 답변 보존 | 없음 |
| GET `/api/document-claims/<ID>` | 저장 문서 검색의 현재 발췌 목록. 과거 자유문장 소급 검증 아님 | 없음 |
| POST `/api/agent` | 질문→도구→답변→검토, 완료 후 응답 | 일반 서버에서 발생 가능 |

`csrf_token`은 OpenAI 키가 아니다. 서버 재시작 후 새 토큰을 받아야 한다. 새 질문 요청에는 `Content-Type: application/json`, `X-Demo-Token: <csrf_token>` 헤더를 사용한다. 브라우저 Origin과 Host를 검사한다. 키는 백엔드 환경변수로만 관리한다.

## 질문 요청

```json
{
  "question": "MAINT-05의 발동 조건과 조치를 설명해 주세요.",
  "detector_profile": "main_v3_1",
  "document_mode": "auto"
}
```

질문은 공백만으로 구성할 수 없고 8,000 UTF-8 바이트 이하다. 요청 본문은 최대 40,000바이트다. 선택값을 생략하면 기본값을 사용한다.

- 탐지: `main_v3_1`, `yujin_v3_2`, `seongho_two_point`, `seongho_drift`.
- 문서: `auto`, `vector`, `graph`, `full`.

추가 선택값 `repair_incident`는 JSON boolean이며 기본값 `false`다. `true`인 경우 사건 설명의 근거 검토가 거절되면 같은 근거로 한 번만 수정·재검토한다. 최대 계획1 + 초안2 + 검토2회다. 실제 요청에서는 추가 비용이 생길 수 있다. 전송 실패·잘못된 검토 JSON·구조적 근거 불일치는 자동 재시도하지 않는다. 문서 Agent의 기존 제한은 이 옵션과 별도다.

선택된 탐지기는 사건 경로에, 문서 방식은 문서 경로에 적용한다. `xai.integration.route`와 `actual_*_backend`로 실제 사용 경로를 확인한다. KG 집합·경로는 전수 질의로 계산하며 모든 질문이 문서 검색을 거치는 것은 아니다.

## 저장 조회·생성 완료 응답

실제 전체 예제 5개는 로컬 `kg_build/agent_handoff_20261114/examples/`에 저장한다. 복원 후 `python scripts/agent_handoff.py audit`로 다시 생성할 수 있다. 파일은 원문이 포함되어 Git에 넣지 않는다.

| 필드 | 의미·UI 처리 |
|---|---|
| `id`, `question`, `answer` | 실행 식별자, 원 질문, 답변 문자열. 문자열은 HTML로 신뢰하지 말고 안전하게 표시 |
| `agent_status` | `complete`, `needs_clarification`, `insufficient_evidence`, `failed` |
| `model` | 실행 당시 모델 설정. 과거 기록은 해당 당시 설정 유지 |
| `usage.total_tokens` | 생성·검토 모델 토큰 합계. 임베딩 토큰은 이 합계에서 제외 |
| `context_tokens` | 최종 사건 근거 또는 최종 문서 검색 근거의 토큰 수. KG 전수 질의에서는 0일 수 있음 |
| `tool_evidence_tokens` | 사건 도구가 반환한 누적 토큰 수. 보강 후 최종 근거와 다를 수 있음 |
| `agent_steps` | 실제 도구 호출, 인자, 처리 상태. 문서 검색은 어댑터의 실행 요약 |
| `verification` | 기록된 검토 결과. `method=deterministic_full_KG_query`는 코드 계산이고, 나머지는 AI 검토. 테스트 정확도 아님 |
| `sources` | 인용 가능한 원문 청크·쪽·문서·해시. KG 질의에서는 RDF 사실을 직렬화한 레코드가 들어옴 |
| `edges` | `{s,p,o,depth}`의 실제 저장 간선. 순서가 하나의 연속 경로라는 뜻은 아님 |
| `warnings` | 과거 후보·인과 미확정·사후 정보 등의 한계 |
| `candidate_ids` | 선택하거나 설명한 후보 식별자 |
| `xai.integration` | 선택 설정, 실제 경로, 역할 적용 범위 |
| `xai.incident`, `alarms` | 사건 구간·관측값·규칙. 문서/KG 질문에는 없을 수 있음 |
| `xai.execution_parameters`, `implementation_policy`, `type_definitions` | 실행 조건·기본값의 출처·유형 정의 |
| `xai.document_retrieval` | 문서 방식, 선택 청크, 근거 완전성. 이 경로에서만 존재 |
| `xai.kg_query` | 전수 질의 인자·전체 결과 개수·항목·방향 경로. 이 경로에서만 존재 |
| `xai.decision_evidence` | 새 사건 실행의 구조적 근거 검사. 알람별 관측·규칙·출처 ID·지원되는 조건 재계산·명시적 미검증 범위. `consistent`는 이 범위의 일치이며 전체 자연어 정확도나 인과 확정이 아님 |
| `claims` | 새 사건 답변에서 실제 게시한 주장. 각 문장의 `claim_id`, 종류·근거·확인 방식. 실패/보류·미적용·과거 기록은 빈 배열 |
| `xai.claim_binding` | 사건 주장의 선택·조립 상태와 `published`, 시도·보류 사유·목록 해시. 게시 여부를 반드시 확인 |
| `xai.claim_catalog_summary` | 전체 주장 수·선택용 입력 토큰·목록 해시 |
| `claims[*].evidence_paths` | 주장의 실제 RDF·실행 참조·파일 참조 경로, 방향·분기·완료/단절 상태·이유 |
| `xai.claim_path_summary` | 전체 허용 주장 경로의 `complete`·`scope_only`·`broken` 개수 |
| `xai.rule_explanations` | 사건의 규칙 경계·시간 정책·사후 종료 검사. `machine_recovery_verified=false` |
| `xai.document_answer_complete` | 새 문서 발췌 답변의 AI 검토 완전성 판단. 코드의 의미 인증이 아님 |

자료가 없으면 `sources=[]`, `edges=[]`, `verification=[]`일 수 있다. 빈 검토 배열을 ‘통과’로 표시하지 않는다. `complete`는 실행 완료 상태이며 사실 정확도 100%를 뜻하지 않는다. 성호의 `UNCLASSIFIED`는 미분류, `severity_origin`이 표시용인 `ADVISORY`는 실제 심각도 판단이 아니다.

Agent v3의 사건 답변은 모델이 허용 주장 ID를 선택하고 코드가 문장을 조립한다. `[CLM-...]`는 원문 인용과 구분되는 주장 식별자다. `validation.status=grounded`는 명시된 방법의 근거 연결이고 `scope_statement`는 한계 표현이다. 조건부 권고는 KG 저장 필드와 출처의 확인이며 현장 실행 승인·원문 의미 전체 검증은 아니다. 문서 자유답변과 정형 KG 조회는 `not_applied`, 과거 기록은 `not_recorded`로 표시한다. `/api/claim-catalog/<ID>`의 `past_answer_claim_binding=not_performed`는 과거 문장에 새 검증을 소급하지 않는다는 뜻이다. 상세 [주장 연결 계약](CLAIM_BINDING.md).

사건 Agent v4는 각 주장에 연결된 근거 경로를 제공하고 단절된 주장을 선택·게시하지 않는다. `rdf`의 원래 트리플과 `traversal`을 함께 사용하고, `runtime_reference`·`file_lookup`은 KG 간선으로 표시하지 않는다. 문서 분기는 실제 Rule 노드에서 시작한다. `scope_only`는 한계 표현으로 관계 경로가 아니다. `/api/claim-paths/<ID>`는 `path_scope`를 구분하고 `past_answer_prose_revalidated=false`로 과거 문장의 새 검증을 주장하지 않는다. 상세 [근거 경로 계약](EVIDENCE_PATHS.md).

자기수정 실행에서는 `verification`에 첫 거절과 두 번째 승인 모두 남을 수 있다. 각 항목의 `attempt`를 표시하고 최종 상태와 마지막 검토를 함께 읽는다. 과거 기록에는 새 구조 검사 필드가 없을 수 있다. 기존 결과는 수정하지 않고 `/api/decision-evidence/<ID>`로 무료 재점검한다. 이 응답의 `answer_unchanged_sha256`과 `audit_version`은 원래 답변과 별도 점검을 구분한다. 문서·KG 전용 실행은 사건 근거가 없어 이 재점검 경로에서 HTTP 400이다. 상세 [구조 검사 범위](DECISION_EVIDENCE.md).

창 연산 확장에서는 `verified_trigger_count`가 지원되는 전체 발동 조건 수이고, `simple_trigger_checks`는 그중 기존 단순 임계값 조건 수다. 파생 감시의 원래 신호가 승격 후 파일에서 제거된 경우 `source_signal_reference_status`와 정확한 해시 복원 결과를 제공한다. 모델 컨텍스트에 추가로 조회한 의존 출처는 `xai.dependency_retrieval`, 과거 기록을 별도로 점검하며 추가한 출처는 `dependency_sources_added_for_recheck`에 표시한다. 과거 입력에 출처가 있었다고 소급 해석하지 않는다. 상세 [창 연산 검사](WINDOW_CHECKS.md).

Agent v5에서는 `xai.rule_explanations`로 경계·시간 조건·사후 종료를 제공한다. 저장 `recovered`는 규칙 조건 해제이며 실제 설비 회복이 아니다. 통합 문서 경로의 `DCL` 주장은 원문 발췌를 그대로 조립한다. 사건과 같은 `claims[*].evidence_paths.paths[*].steps` 구조이며 모든 문서 단계는 파일 참조다. `published`를 확인하고, `answer_complete`는 AI 검토 판단으로 취급한다. 독립 문서 Agent의 기존 기본 모드와 과거 답변에는 소급 적용하지 않는다. 상세 [XAI 확장](XAI_EXTENSIONS_20261115.md).

## 상태와 오류

| HTTP·상태 | UI 처리 |
|---|---|
| 200 + `complete` | 답변·근거·한계를 함께 제공 |
| 200 + `needs_clarification` | 대상 또는 사건 선택 안내 |
| 200 + `insufficient_evidence` | 근거 부족·검토 보류·지원하지 않는 실제 조회를 표시 |
| 200 + `failed` | 완료된 답변처럼 표시하지 않고 실행 기록 확인 안내 |
| 400 | 질문·옵션·본문 형식 확인 |
| 403 | Host·Origin·세션 토큰 확인 |
| 404 | 저장 ID나 경로 확인 |
| 409 | 다른 실행 처리 중. 자동 재생성하지 않음 |
| 503 + `code=read_only` | 저장 결과만 조회 가능한 서버 |
| 503 (사건 목록) | 봉인 결과 누락·무결성 문제 |
| 500 | 처리 실패. `run_id`가 있으면 로컬 기록 확인, 자동 유료 재시도 금지 |

모델 호출 중 실패한 요청도 비용이 발생했을 수 있어 자동 반복하지 않는다. 새 실행을 사용자가 명시적으로 요청할 때만 다시 생성한다. 현재 동기식 응답이므로 서버 프록시의 타임아웃은 모델 지연을 고려해야 한다. 스트리밍·다중 사용자 인증·실제 설비 제어는 이번 인계 범위가 아니다.
