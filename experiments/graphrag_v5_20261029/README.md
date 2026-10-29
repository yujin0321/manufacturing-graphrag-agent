# GraphRAG v5 — 비용을 제한한 검색 비교

2026-10-29. `4th-yujin`의 Agent v4.1을 기반으로 검색 실험을 추가했다. 기본 Agent 실행 경로는 v4.1이며, v5는 별도의 검색·평가 실험이다.

## 결과를 먼저 보기

- [전체 비교 보고서](reports/offline_budget_v1/검색성능_전체문항_비교보고서.md)
- [문항별 검색 결과](reports/offline_budget_v1/문항별_검색비교.csv)
- [요약 CSV](reports/offline_budget_v1/검색성능_요약.csv)
- [대표 6문항·18개 저장 답변의 원문 대조](reports/offline_budget_v1/대표6문항_답변검토.md)
- [130문항 실행·대기 상태](reports/offline_budget_v1/전체문항_실행현황.csv)
- [전체 문항 코드](benchmark_catalog.py)

130문항 중 102개 검색 비교, 별도 오류 주입 2개, 입력 미지정 대기 26개다. 동일 원문을 공유하는 문항이 있으며 독립 미노출 평가가 아니다.

| 로컬 검색 문항군 | 수 | VectorRAG 필수 근거 회수율 | GraphRAG | 구조화 KG 조회 제거 |
|---|---:|---:|---:|---:|
| 문서 QA, 최대 4,000토큰 | 72 | 76.9% | 96.9% | 96.9% |
| KG 관계·집합·경로, 최대 8,000토큰 | 12 | 46.5% | 83.7% | 55.0% |
| YB 구조·메타데이터·문서, 최대 8,000토큰 | 18 | 58.8% | 91.2% | 85.3% |

이번 오프라인 평가의 새 API·생성·모델 채점 호출은 0회다. API 임베딩 캐시 35문항은 별도 트랙(80.8% / 98.6%)이며, 로컬 모델 결과와 섞지 않는다. 그래프의 이득은 구조화 관계 조회에서 확인됐고, 문서 QA 전체에 반드시 필요하다고 결론 내리지 않는다. 이 수치는 검색 지표이며 전체 답변 정확도가 아니다.

## 구현

- `src/imaks_kg/rag/retrieval_v5.py`: 원문·해시를 검증한 행 연결, 센서→규칙 역조회, 출처별 문맥 구성, 명시적 규칙 참조.
- `src/imaks_kg/rag/kg_query_v5.py`: 같은 KG 사실의 텍스트 직렬화, 방향·집합·출처·결측 필드의 제한된 구조화 조회. seed/candidate 노드를 합치지 않는다.
- VectorRAG와 GraphRAG는 같은 질문·원문·KG 사실·토큰 상한에 접근한다. 그래프를 제거한 대조군을 함께 둔다.
- 자연어→임의 Cypher 완성, 실시간 제어, 새 인과관계 발견, 전체 답변 정확도 평가를 주장하지 않는다.

## 재현 입력과 비용

원문·모델 가중치·유료 API 요청/응답·평가 정답은 이 커밋에 포함하지 않는다. 기존 저장소의 허가된 로컬 입력이 필요하다. 공개 clone만으로 과거 실행을 즉시 재생할 수 있는 묶음은 아니다.

필요한 로컬 입력:

1. 저장소 루트의 `preprocessed/documents/chunks.jsonl`, 고정 v2 `candidate.ttl`, 기존 `docs/benchmark_yewon_v2_20261023/scoring_lock_v1.json`.
2. 기존 `kg_build/retrieval_v3_rows/{manifest.json,vectors.npy}`와 질문 임베딩 캐시. 추가 캐시는 이 폴더의 `runs/retrieval_v2/query_embeddings/`에 둘 수 있다.
3. 이미 설치된 `jhgan/ko-sroberta-multitask` 로컬 모델. `V5_LOCAL_MODEL_DIR`로 snapshot 폴더를 지정한다. 자동 다운로드하지 않는다.
4. 평가 담당자의 이 폴더 아래 `evaluation/expanded/answer_key.json`. 공개 질문·정답을 검색 색인에 넣지 않는다. 봉인 후 별도 `grade` 과정만 정답을 읽는다.
5. 대표 답변 재검토에는 기존 `runs/answers_final/`과 선택 파일의 원본 해시가 필요하다. 공개 Markdown에는 검토한 18개 답변과 관련 원문 발췌가 들어 있다.

```powershell
# 저장소 루트, 기존 의존성이 설치된 환경에서 실행. API 키는 필요 없다.
$env:PYTHONPATH='src'
$env:PYTHONUTF8='1'
$env:V5_LOCAL_MODEL_DIR='로컬에 이미 있는 모델 snapshot의 절대 경로'
python experiments/graphrag_v5_20261029/offline_retrieval.py prepare
# sentence-transformers/torch가 이미 설치된 로컬 Python에서 실행한다.
python experiments/graphrag_v5_20261029/offline_local_encode.py
python experiments/graphrag_v5_20261029/offline_retrieval.py retrieve
python experiments/graphrag_v5_20261029/offline_retrieval.py grade
```

네트워크 연결은 오프라인 실행 코드에서 차단하고 `local_files_only=True`로만 모델을 읽는다. 같은 실행 폴더를 덮어쓰지 않는다. 과거 실행의 해시는 기록으로 보존하며, 공개용 경로 조정본을 과거 바이트 그대로의 실행본으로 주장하지 않는다.

## 검증과 한계

관련 테스트 12개 통과. 입력이 있는 환경에서:

```powershell
python -m unittest discover -s tests -p 'test_*v5.py' -v
```

정답은 AI 원문 대조 초안과 별도 결정적 KG 조회를 사용했다. 독립 전문가 검토는 없다. 대표 답변은 과거 동일 API 모델의 저장 결과를 정성 검토했으며 로컬 검색의 생성 성능 점수로 합산하지 않는다. 이전 유료 수집은 비용 우려로 중단됐고, 그 사용량과 미완료 상태도 `reports/`에 구분해 남겼다. 유료 일괄 수집 실행기는 이번 기본 오프라인 배포에 넣지 않았다.
