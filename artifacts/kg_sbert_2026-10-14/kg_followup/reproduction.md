# 오프라인 KG 승격 및 진단 평가 재현

구현 범위: source-only JSON + 고정 예측 + seed 구조를 RDF로 변환한다. API 호출과 Neo4j 접속은 없다. 평가 모듈만 규칙 정답 CSV를 받는다.

검증 환경: Python 3.12.14, rdflib 7.1.4, pyshacl 0.30.1. 이번 실행에서는 기존 환경만 사용했고 패키지나 모델을 설치하지 않았다. 정확한 Python 버전은 로컬 실행 메타데이터를 확인한다.

## 준비 입력

- seed `nodes.csv`, `edges.csv`: 원본 ZIP의 kg_seed/ 내 두 파일만 별도 작업 폴더에 꺼낸다.
- source-only 폴더: 문서 JSON 7개, ontology.ttl, shapes.ttl, input_manifest.json.
- 추출 단계에서 고정한 predictions.jsonl 및 lineage.json.
- 평가에만 쓰는 원본 `kg_seed/ground_truth.csv`. 수정 정답이나 기존 평가 점수는 사용하지 않는다.

출력 폴더는 새 경로여야 한다. 예측/원문/정답을 같은 이름으로 덮어쓰지 않는다. 아래 `<...>`는 로컬 경로로 바꾼다.

```powershell
$env:PYTHONPATH = "src"
python -m imaks_kg.kg.build --nodes "<nodes.csv>" --edges "<edges.csv>" --source-dir "<source-only 폴더>" --predictions "<predictions.jsonl>" --ontology ontology_v1/ontology.ttl --shapes ontology_v1/shapes.ttl --output "<새 KG 출력 폴더>"
python -m unittest discover -s tests -p test_kg_followup.py -v
python -m imaks_kg.evaluation.offline --predictions "<predictions.jsonl>" --gold "<원본 ground_truth.csv>" --lineage "<lineage.json>" --policy docs/offline_evaluation_policy.md --output "<새 평가 출력 폴더>"
python -m imaks_kg.evaluation.numeric --predictions "<predictions.jsonl>" --gold "<원본 ground_truth.csv>" --output "<새 numeric_diagnostic.json>"
```

## 산출물 해석

- graph.ttl: 최종 인스턴스 그래프. 스키마 선언을 데이터 노드로 합치지 않는다.
- triple_lineage.jsonl: 각 트리플의 원본 행 또는 문서 단위/해시. 동일 센서 관계에 두 원본 CSV 행이 대응하면 둘 다 남는다.
- maintenance_mapping.json: 원본 정비 ID/센서/우선순위와 문서 추출 간 대조. 원본 action이 예측 responseText를 덮어쓰지 않는다.
- shacl_report.txt: inference=none 검증 결과.
- neo4j_import.cypher: 노드 URI별 MERGE와 관계 생성문. 생성만 검증했고 Neo4j에서 실행하지 않았다. 독립된 검토용 데이터베이스에서 사용해야 하며 이전 버전의 불필요한 노드를 삭제하는 동기화 도구는 아니다.
- metrics.json: SBERT F1_content=null과 명확히 구별된 F1_lexical_proxy 진단.
- assignments.json: 임계값 전후의 일대일 대응 및 점수. 미연결 목록은 완전한 실패 목록이 아니다.
- numeric_diagnostic.json: source 문서/센서로 정렬한 네 한계값 비교. 정답 수치로 원문을 수정하지 않는다.

출처 문자 좌표는 제공된 unit의 좌표이며 재계산한 PDF 부분문자 오프셋은 아니다. 표 인용은 행 전체를 포괄하므로 colIndex는 그 행의 모든 실제 열 번호로 기록한다. 추가적으로 정확한 quote_offset_in_unit을 ledger에 남긴다.

주 지표 F1_content를 구현/실행할 때는 사전 합의한 SBERT 모델과 Hungarian 임계값을 유지해야 한다. 토큰 지표는 부등호·부정의 의미를 구별하지 못하므로 그 대체 점수로 사용하지 않는다. 실험 데이터를 Git에 추가하지 말고 코드·집계 보고서만 커밋한다.
