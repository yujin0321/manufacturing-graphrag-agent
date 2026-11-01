# Retrieval v3 — 행 단위 청킹 · BM25 하이브리드 · 별칭 연결 · 중복 병합

2026-10-28. 기존 v1/v2 코드·결과·잠금 파일은 수정하지 않았다. 새 파일만 추가했다.

## 왜 만들었나

| v2까지의 문제 | v3 해결 |
|---|---|
| v1 실패 6건이 모두 표 청크(정비 규칙 8행이 한 청크) | `chunking.py`: 표를 행마다 분리, 표 제목은 각 행에 반복, `parent_chunk_id` 보존 |
| v2의 어휘 점수는 IDF 겹침이고 GraphRAG에만 적용 | `lexical.py`: 표준 Okapi BM25, **세 방식이 같은 검색기를 공유** |
| 정확한 ID만 연결(`ST02 전류`, `서버실 온도`는 그래프에 못 닿음) | `linking.py` + `lexicon.json`: 스테이션 약칭·한국어 명칭 + 센서 유형어를 근접(14자)으로 묶어 센서 노드에 연결 |
| `MAINT-04`(seed)와 `candidate-SOP-003::MAINT-04`(추출)가 별도 카드 | 같은 정규 ID끼리 한 엔티티로 병합. **값이 다르면 출처와 함께 둘 다 표시**(예: "Inspect inlet filter and pump" vs "Inspect filter and pump") |
| v2 개선이 여러 변경의 합이라 그래프 효과를 분리할 수 없음 | 아래 4개 시스템으로 한 번에 하나씩만 다르게 비교 |

## 비교 시스템 (`policy.json`)

| 시스템 | 무엇이 다른가 |
|---|---|
| `full_context` | 검색 없이 86청크 전체(작은 코퍼스의 상한선) |
| `vector_v3` | BM25 + dense(RRF), 행 단위. KG 접근 없음 |
| `vector_v3_lex` | `vector_v3` + 별칭 사전으로 찾은 스테이션·센서 ID를 BM25 질의에 추가. KG는 **이름 사전으로만** 사용(간선·규칙·출처 미사용) |
| `graph_v3` | `vector_v3_lex` + 연결된 엔티티에서 2홉 탐색 → KG 출처의 **정확한 행**을 후보 앞에 삽입 + 병합 카드 |

`vector_v3_lex` 대비 `graph_v3`의 차이가 **그래프 탐색 고유의 효과**다.

## 실행

```powershell
$env:PYTHONPATH='src'; $env:PYTHONUTF8='1'
..\.venv\Scripts\python.exe -m unittest tests.test_retrieval_v3 -v
# 무료·오프라인: 검색 → 봉인 → 근거 회수율 채점
..\.venv\Scripts\python.exe scripts\run_benchmark_v3.py retrieve --out kg_build\benchmark_v3\retrieval_bm25
..\.venv\Scripts\python.exe scripts\run_benchmark_v3.py grade --run kg_build\benchmark_v3\retrieval_bm25
# 유료: 행 단위 임베딩(약 8천 토큰 1회) 후 dense 포함 재실행, 답변 생성(문항×4시스템×3회)
..\.venv\Scripts\python.exe scripts\run_benchmark_v3.py build-index
..\.venv\Scripts\python.exe scripts\run_benchmark_v3.py retrieve --out kg_build\benchmark_v3\retrieval_hybrid
..\.venv\Scripts\python.exe scripts\run_benchmark_v3.py answer --out kg_build\benchmark_v3\answers_run1 --repeat 3
```

## 오프라인 결과 (BM25만, dense 없음)

새 15문항, 필수 근거 48개(행 단위). 검색만 했고 답변은 생성하지 않았다.

| 시스템 | 근거 회수 | 근거 완비 문항 | 평균 컨텍스트 토큰* |
|---|---:|---:|---:|
| `vector_v3` | 13/48 (27.1%) | 4/15 | 1,615 |
| `vector_v3_lex` | 44/48 (91.7%) | 12/15 | 1,554 |
| `graph_v3` | 43/48 (89.6%) | 11/15 | 2,190 |

해석:
1. `vector_v3`가 낮은 것은 **BM25가 한국어 질문과 영어 문서를 잇지 못하기 때문**이다. 실제 비교에서는 dense 임베딩이 이 역할을 하므로 이 숫자를 v3의 벡터 성능으로 인용하면 안 된다.
2. 큰 개선은 **표 행 분할 + 별칭 사전**에서 왔다. 그래프 탐색을 더해도 회수율이 오르지 않았다(44→43).
3. G12에서는 그래프가 앞에 넣은 행 때문에 데이터시트 행이 후보 상한(24) 밖으로 밀렸다. 그래프 삽입에는 비용이 있다.
4. 그래프의 가치가 검색 회수율이 아니라 **답변 구성**(병합 카드의 출처 충돌 표시, 조인된 규칙 묶음)에 있는지는 답변 생성 비교로만 확인할 수 있다.

\* 이 환경에서는 o200k 토크나이저 파일을 받을 수 없어 단순 분절기로 셌다. 실제 예산 적용 결과는 PC에서 `retrieve`를 다시 실행해 확인해야 한다(무료).

## 한계

- `vector_v3_lex` 대조군은 첫 오프라인 실행(vector 27% vs graph 90%)을 본 뒤 추가했다. 그 차이가 사전 때문인지 그래프 때문인지 분리하려는 목적이며, 문항·정답·다른 시스템 설정은 바꾸지 않았다.
- 별칭 사전과 새 문항을 같은 작성자(AI)가 만들었다. 사전은 문항 작성 전에 만들고 해시로 고정했지만, 작성자가 사전을 알고 있었다는 사실은 남는다. 팀원이 사전을 보지 않고 쓴 문항 몇 개를 추가하면 가장 확실하게 보완된다.
- 집계형 질문(G01: CRITICAL 정비 규칙 전부)은 엔티티에서 출발하는 현재 탐색 방식으로는 풀 수 없다. `priority` 속성 필터 같은 구조 질의가 필요하며, CLAUDE.md ⑧의 자연어→Cypher가 그 역할이다.

## PC 무료 검증 (2026-10-28 보완)

프로젝트의 실제 가상환경 Python으로 다음을 실행한다.

```powershell
.\.venv\Scripts\python.exe scripts\validate_benchmark_v3_free.py
```

누락된 numpy/tiktoken/rdflib은 requirements-rag.txt로 설치하고 버전을 보고한다.
공식 o200k_base 파일의 최초 자동 다운로드는 허용한다. 다운로드가 막히면
대체 토크나이저 없이 중단한다. 테스트 30개 통과 후 BM25 검색을 봉인하고,
별도 프로세스로 PRIVATE 정답을 읽어 근거 회수율을 평가한다.
`--bm25-only`는 기존 dense 인덱스가 있어도 유료 질의 임베딩을 호출하지 않는다.
출력은 매번 새 폴더에 저장한다. build-index와 answer는 별도 승인 후 실행한다.
