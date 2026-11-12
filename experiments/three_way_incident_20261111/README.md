# LLM 단독 · 텍스트 검색 RAG · GraphRAG — 탐지 사건 질문 오프라인 비교 (2026-11-11)

비교 보고서(문서): 「LLM 단독 · VectorRAG · GraphRAG 3종 비교 보고서」 (claude.ai 문서). 이 폴더는 그중 결과 3의 코드와 산출물이다.

- 질문 16개: GraphRAG v5에서 사건·구간 입력이 없어 보류됐던 CQ02·03·05·11·15·16·22·24를 룰 엔진 v3.1 상관 후보 2건으로 지정해 채우고, 집합 질문 2개를 더했다. 점수(`likelihoodScore`)가 필요한 CQ01·06·07 등은 계속 보류.
- 필수 근거: 봉인된 엔진 출력·오버레이·고정 KG에서 코드로 결정(`questions()`). 데이터셋 라벨 미열람, API 0회.
- 세 방식: LLM 단독(문맥 없음), 텍스트 검색 RAG(BM25, VectorRAG 대체), GraphRAG(엔티티 연결 + KG·오버레이 유형별 확장). 두 RAG는 같은 자료 묶음(문서 86, 사건 17, 상관 후보 2, 시계열 출처 17, KG 규칙 100, 공정 사실 12)과 같은 4,000토큰 예산.
- 결과: 평균 필수 근거 회수율 LLM 0% · 텍스트 검색 81.0%(전부 회수 8/16) · GraphRAG 100%(16/16).
- 한계: 필수 근거와 GraphRAG 탐색이 같은 KG 구조에서 나왔고 같은 작업자가 만들었다(유리한 설계 가능). BM25는 임베딩 검색과 다를 수 있다. 답변 정확도가 아니다.

```powershell
$env:PYTHONPATH="src"
python -m imaks_kg.detection.engine.run --config v3_1 --out kg_build/rule_engine_v3_1
python -m imaks_kg.detection.engine.overlay --run kg_build/rule_engine_v3_1 --out kg_build/rule_engine_v3_1_overlay
python experiments/three_way_incident_20261111/run_offline.py --out experiments/three_way_incident_20261111/results_rerun
```

`results/`: `questions.json`(질문·필수 근거), `results.json`(방식별 문맥·누락 근거·요약), `complete.json`(해시).
