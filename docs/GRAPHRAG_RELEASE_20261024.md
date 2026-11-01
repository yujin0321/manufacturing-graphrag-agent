# 예원 v2 기반 GraphRAG 검색 개선 및 평가 공유

2026-10-24 기준으로 검색 개선 1~4단계를 완료했다. 기존 예원 v2 KG를 유지하며, 다른 팀의 추출 결과나 priority overlay를 합치지 않았다.

## 최신 결과

- eval 24문항: 기존 GraphRAG 106.5/120 → 개선판 120/120, 완전 정답 18/24 → 24/24.
- dev 6문항: 23.5/30 → 30/30. dev와 eval은 분리 집계했다.
- 기존 문항의 개발 재시험이며 AI 단독·비블라인드 채점이다. 미노출 성능, 순수 그래프 효과 또는 새로운 인과관계 발견의 증거가 아니다.
- 상세: [실제 답변 평가 보고서](../reports/graphrag_v2_answers_20261024_verify.md).
- 검색 비교: [근거 회수 검사](../reports/graphrag_v2_retrieval_20261024_verify.md), [B/C 제거 실험](../reports/graph_ablation_20261024_verify.md).

이전 단계 README와 구현 보고서에 있는 '아직 실행하지 않음'은 작성 당시 상태다. 현재 완료 상태는 이 문서와 실제 답변 평가 보고서를 기준으로 확인한다. 해시로 고정한 이전 문서는 그대로 보존했다.

## 코드와 실행 순서

의존성은 `requirements-rag.txt`에 있다. 로컬 모델 가중치는 필요 없다. Python 환경에서 `PYTHONPATH=src`로 실행한다.

1. `imaks_kg.rag.vector`: 원문 청크 인덱스 및 Vector RAG 기준선.
2. `imaks_kg.rag.comparison`: 기존 LLM/GraphRAG 비교.
3. `scripts/preserve_comparison_baseline.py`: 로컬 기준선 보존·검증.
4. `imaks_kg.rag.graph_v2` 및 `scripts/verify_graph_v2_retrieval.py`: 개선 검색과 별도 근거 대조.
5. `scripts/run_graph_ablation.py`: B/C 검색 비교.
6. `scripts/run_graph_v2_answers.py dev` 후 `eval`: 고정된 3번 검색 컨텍스트로 API 답변 생성.
7. `scripts/grade_graph_v2_answers.py`: 명시적인 AI 검토 판정의 산술 집계. 자동 의미 채점기가 아니다.

현재 스크립트는 기록된 실험을 재현하기 위한 것이며, 임의 신규 질문을 처리하는 완성된 UI/Agent가 아니다. `graph_v2`는 질문 임베딩 캐시가 없으면 네트워크 호출 없이 중단한다.

## 공개 범위와 로컬 선행 자료

이 커밋에는 코드·공개 질문·고정 평가 규약·설정·테스트·보고서를 포함한다. 비공개 정답, 개별 채점표, API 요청/응답 원본, 벡터 캐시, 원문 작업 사본과 기준선 ZIP은 공개하지 않는다. 따라서 새 clone만으로 실제 평가 실행을 즉시 재현할 수는 없다.

실행에는 허가된 원문 `preprocessed/documents/chunks.jsonl`, `kg_build/vector_rag_v1/` 인덱스와 질문 캐시, 단계별 검색 완료 파일 및 해시 manifest가 필요하다. 채점에는 `evaluation/benchmark_yewon_v2_20261023/`의 비공개 정답과 기존/개선판 명시적 판정 파일이 추가로 필요하다. 파일은 각 실행 lock의 해시와 일치해야 한다. 다른 원문·질문은 새 실험 버전으로 관리한다.

API 키는 로컬 `OPENAI_API_KEY` 환경변수로만 공급한다. 생성 명령은 유료 API를 호출한다. 기존 답변은 보존하고 미해결 시도는 자동 재전송하지 않는다.

테스트는 `test_vector_rag.py`, `test_rag_comparison.py`, `test_graph_v2.py`, `test_graph_ablation.py`이며 네트워크를 호출하지 않는 합성/모의 검증이다.
