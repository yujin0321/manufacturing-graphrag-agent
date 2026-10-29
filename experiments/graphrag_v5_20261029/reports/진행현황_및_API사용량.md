# API 실행 중단 시점의 저장 기록

사용자의 비용 우려에 따라 추가 API 실행을 중단했다. 전체 문항 비교·최종 채점은 완료되지 않았다.

저장된 답변: 104개. 모델별: GraphNoTopology 15개, GraphRAG 30개, LLM 30개, VectorRAG 29개

| 단계 | 저장된 API 응답 수 | 입력 토큰 | 출력 토큰 | 합계 토큰 |
|---|---:|---:|---:|---:|
| answer_generation | 104 | 189,333 | 42,673 | 232,006 |
| question_embeddings | 35 | 2,987 | 0 | 2,987 |
| additional_key_authoring | 10 | 103,888 | 11,490 | 115,378 |

이 수치는 로컬에 응답이 저장된 요청의 사용량이다. 실제 청구액은 확인하지 않았으며, 중단 당시 처리 중이던 요청은 별도 과금될 수 있다.
응답 미저장 시도: 1건. 자동 재전송하지 않는다.

문항집: `benchmark_catalog.py` (130개). 답변 비교 대상 102개, 별도 오류 주입 검증 2개, 입력 미지정 대기 26개.
1차 검색 평가: `reports/retrieval/retrieval_summary.json`. 검색 근거 회수율이며 답변 정확도와 다르다.
답변: `runs/answers_final/<방식>/<문항ID>/answer.json`. 현재 일반 LLM도 유료 API이며 무료 서비스 비교가 아니다.
