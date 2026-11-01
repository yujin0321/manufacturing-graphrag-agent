# Vector RAG v1 — 3단계 구현

완료일: 2026-10-24 (한국 시간). 예원 v2 기반 비교 실험을 위한 문서 검색 기준선이다. 인덱스 생성과 구현 검증은 완료했으며, 4단계 dev 6문항 실행과 실제 답변 생성 API 검증은 아직 하지 않았다.

## 고정 설정

- 입력: `preprocessed/documents/chunks.jsonl`의 SOP 4개·데이터시트 3개, 총 86개 청크. 이 86은 추출 정답 86건과 별개의 문서 청크 개수다.
- 임베딩: OpenAI `text-embedding-3-small`, 1,536차원. 문서 ID·절 제목·원문을 입력한다.
- 검색: 정규화 벡터의 코사인 유사도, 상위 8개. 동점은 chunk ID 순서. 키워드 혼합 검색·재순위화·질문 확장은 사용하지 않는다.
- 컨텍스트: `o200k_base` 기준 최대 4,000토큰. 청크 전체가 들어갈 때만 포함하므로 표와 규칙을 중간에 자르지 않는다. 초과 청크를 건너뛴 기록을 보존한다. 이 인코더는 비교 실험의 예산 측정 기준이며 생성 모델의 정확한 토크나이저라고 가정하지 않는다.
- 생성 모델 설정: `gpt-6.1-sol`, 최대 출력 4,096토큰, temperature/seed 생략, `store:false`. 이번 단계에서는 생성 API를 호출하지 않아 모델 접근 권한·실제 반환 모델은 아직 검증하지 않았다. 자동 모델 대체는 하지 않는다.
- 생성 지시문: `answer_instructions.txt`. 향후 LLM·GraphRAG 비교에도 공통 지시와 동일한 생성 설정을 적용해야 한다.

## 실행 방법

저장소 루트의 PowerShell에서 실행한다. 기존 가상환경에 필요한 패키지가 있어 이번에는 설치하지 않았다. 다른 환경의 최소 의존성은 `requirements-rag.txt`에 있다. 로컬 LLM이나 벡터 DB는 필요 없다.

```powershell
$env:PYTHONPATH='src'
$env:PYTHONUTF8='1'
# OPENAI_API_KEY는 로컬 환경변수로 설정하며 문서·채팅·Git에 적지 않는다.
..\.venv\Scripts\python.exe -m imaks_kg.rag.vector inspect
# 같은 인덱스는 추가 API 호출 없이 검증 후 재사용한다.
..\.venv\Scripts\python.exe -m imaks_kg.rag.vector build
..\.venv\Scripts\python.exe -m unittest discover -s tests -p test_vector_rag.py -v
```

다음 4단계에서 질문별로 새 실행 폴더를 지정한다. 아래는 사용 형식이며 이번에는 실행하지 않았다.

```powershell
..\.venv\Scripts\python.exe -m imaks_kg.rag.vector ask --question '실행할 질문' --run-dir kg_build/vector_rag_runs/dev_run_001
```

`ask`는 질문 임베딩과 답변 생성 API를 사용한다. 질문·검색 청크가 생성 API에 전달된다. 실제 벤치마크 실행 전에는 모델 접근 가능 여부와 세 비교 시스템의 공통 조건을 확인한다. 응답을 생성하는 것과 채점은 분리되어 있다.

## 저장·실패 처리

- `kg_build/vector_rag_v1/`: corpus, plan, vectors.npy, index_manifest, API 원시 요청·응답, verification.json. Git에서 제외된다.
- `kg_build/tokenizer_cache/`: 약 5.3MB의 토크나이저 사전. 모델 가중치가 아니다.
- 질문별 실행 폴더: input.json, retrieval.json, answer.json 또는 failure.json 및 생성 API 기록. 검색 순위·선택된 근거·사용량·실제 모델 ID를 기록한다.
- 정답 파일·채점표·후보 관계·다른 팀 결과를 검색 입력으로 읽지 않는다. scoring_lock의 원문 해시만 참조한다.
- API 키·Authorization 헤더는 기록하지 않는다. 기록 파일에는 원문과 모델 출력이 포함되므로 무심코 공개 저장소에 추가하지 않는다.
- 실패한 API 요청은 자동 재시도하지 않는다. attempt만 있고 response가 없으면 중복 과금을 막기 위해 중단한다. 이때 계정 사용량과 오류 기록부터 확인하며 attempt 파일을 무조건 삭제하거나 새 실행 폴더로 재호출하지 않는다.
- 원문·설정·지시문이 바뀌면 기존 인덱스를 조용히 덮어쓰지 않는다. 변경 이유를 기록하고 새 버전/폴더로 구축한다.

## 해석의 한계

이번 결과는 검색 시스템 구현 검증이다. QA 점수나 추출 F1을 새로 계산한 결과가 아니다. 기존 v2 개발 과정의 정답 노출 이력은 이번 입력 분리로 사라지지 않으며 이 벤치마크를 독립 홀드아웃으로 주장하지 않는다. 원문의 상충 규정은 그대로 보존한다. 현장 안전·인과관계의 전문가 검증을 대신하지 않는다.

API 형식 참고: [Embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create), [Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).
