# KG 구축 및 SBERT 평가 실산출물

사용자의 2026-10-14 명시적 요청으로 별도 보관했던 자료를 GitHub에 추가했다. 이전 보고서·노트북의 "GitHub 제외" 문구는 당시 방침이다. 고정 실험 파일의 원본 바이트는 변경하지 않았다.

| 경로 | 내용 |
|---|---|
| `predictions.jsonl` | 고정 LLM 추출 172건 |
| `lineage.json` | 추출 ID와 원문 규칙 연결 |
| `evaluation_inputs/ground_truth.csv` | 원본 정답 86건; 평가 전용 |
| `evaluation_inputs/nodes.csv`, `edges.csv` | 원본 seed 구조 입력 |
| `kg_followup/kg_final/graph.ttl` | **최종 KG**: 484노드, 4,697트리플 |
| `kg_followup/kg_final/neo4j_import.cypher` | Neo4j 적재용 파일; 서버 적재 미실행 |
| `kg_followup/kg_final/triple_lineage.jsonl` | 트리플별 출처 |
| `kg_followup/kg_final/shacl_report.txt` | SHACL 통과 결과 |
| `kg_followup/evaluation/` | 초기 ID·단어 겹침·수치 진단 |
| `sbert/iMAKS_SBERT_F1_content.ipynb` | Colab 재실행 노트북, 평가 입력 내장 |
| `sbert/executed.ipynb` | 실제 실행 출력이 저장된 노트북 |
| `sbert/metrics.json` | F1_content=0.5193798449612403, 67/86 매칭 |
| `sbert/assignments.json` | Hungarian 할당 86쌍, 임계값 이상 67쌍 |
| `sbert/cosine_matrix.npy` | 정답 86행 × 예측 172열; 입력의 원래 순서 |
| `sbert/imaks_sbert_results.zip` | metrics/assignments/cosine matrix 묶음 |
| `sha256_manifest.json` | 복사한 원본 51개 파일의 크기와 SHA-256 |

`kg_followup/kg/`는 초기 감사용 산출물이며 최종 파일은 `kg_final/`이다. 초기 보고서의 SBERT 미실행 표시는 Colab 실행 전 이력이다. 최신 점수는 `sbert/metrics.json`을 따른다.

## 재실행 및 범위

`sbert/iMAKS_SBERT_F1_content.ipynb`를 Colab 호스팅 CPU 런타임에서 모두 실행한다. API 키나 Drive 마운트는 필요 없다. 입력 해시를 확인한 뒤 평가하며, 패키지·모델은 Colab 서버에 설치된다. 모델 revision 및 패키지 버전은 실행 결과에 기록된다. 향후 환경이 바뀌면 점수가 달라질 수 있으며 이번 실행 환경은 `metrics.json`에 보존했다.

SBERT 평가는 내장 입력으로 재실행할 수 있다. 원문 LLM 추출이나 KG 전체 재구축에 필요한 SOP/데이터시트 source-only JSON 전체는 이번 추가 범위에 포함하지 않았다. 정답은 추출·KG 구축 입력에 섞지 않는다.

Gemini 시험 자료, API 키, 모델 가중치, 가상환경은 포함하지 않았다. 사람 검토와 Neo4j 서버 적재는 미완료다.
