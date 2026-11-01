# 새 질문 처리 — GraphRAG v2

현재 상태(2026-10-27): 이 문서는 CLI 연결 당시의 기록이다. 이후 시연 화면과 후보 설명을 구현했다. 최신 완료 범위는 [통합 안내](PROJECT_HANDOFF_20261027.md)를 참고한다.

`imaks_kg.rag.live.answer(question, run_dir)`는 새 질문을 임베딩한 뒤 기존 GraphRAG v2 검색과 공통 답변 생성 지침을 연결한다. 화면은 아직 없으며 Python 함수 또는 CLI로 사용할 수 있다.

## 실행

저장소 루트 PowerShell에서 기존 가상환경과 로컬 `OPENAI_API_KEY`를 사용한다. 새 질문은 임베딩 1회와 답변 생성 1회의 유료 API 호출이 발생한다. 동일 질문의 저장된 임베딩은 재사용하지만 새 실행의 답변은 다시 생성한다.

```powershell
$env:PYTHONPATH='src'
$env:PYTHONUTF8='1'
..\.venv\Scripts\python.exe -m imaks_kg.rag.live --question '질문을 입력하세요' --run-dir kg_build/graphrag_live/my_question_001
```

`--run-dir`은 매번 존재하지 않는 폴더를 지정한다. 완료/실패한 폴더를 덮어쓰지 않는다. 실패하면 저장된 기록을 확인하고, 원인 불명의 API 실패를 새 폴더로 무조건 반복하지 않는다. 원래 API helper의 unresolved attempt 차단도 유지한다.

필요한 로컬 선행 자료는 `kg_build/vector_rag_v1/`의 인덱스/manifest, 원문 청크, 고정 예원 v2 KG와 공개 평가 lock이다. 필요한 패키지는 `requirements-rag.txt`에 있다. 비공개 정답과 기존 채점 결과를 읽지 않는다. 새 clone만으로 로컬 인덱스가 자동 복구되지는 않는다.

## 보존 및 결과

- 기존 평가 캐시는 읽기만 하며 새 질문 임베딩은 `kg_build/graphrag_live/query_cache/`에 저장한다.
- 기존 `graph_v2.context`의 동일 검색 정책을 사용한다. 원문 후보 최대24개, 총 컨텍스트4000 기준 토큰이다.
- 모델·공통 지침은 기존 설정을 사용한다. 입력 질문은 비어 있지 않은 8000 UTF-8 바이트 이하 문자열이어야 한다.
- 실행 폴더: `input.json`, `run_lock.json`, `embedding.json`, `retrieval.json`, `answer.json`, `api/`. 실패 시 `failure.json`을 남긴다.
- `retrieval.json`에는 실제 방문 노드, 탐색한 관계, 문서 규칙 참조, 원문 출처 연결과 선정 이유가 있다. 참조 탐색을 신규 인과관계로 표시하지 않는다.
- `answer.json`의 `retrieved_sources`는 검색에 포함된 원문이며, 모두 답변에서 인용됐거나 주장 단위로 검증됐다는 뜻은 아니다. 실제 인용은 답변 본문에 있다.
- 답변은 정적 문서 기반이다. 검색 근거 충분성·문서 충돌을 자동 판정하는 별도 탐지기는 없으며, 실시간 설비 상태도 알 수 없다. 관련 안내와 미포함 명시 문서 목록을 결과에 제공한다.

실행 결과/캐시는 Git 제외 경로에 보존한다. 기존 평가 결과와 분리하며 새 질문 실행을 미노출 성능 평가로 자동 집계하지 않는다. 다음 단계에서 이 함수를 입력 화면과 연결할 수 있다.
