# iMAKS 질문·Ontology·SHACL v1

다음 순서는 **KG 질문 정의 → Ontology v1 → SHACL 검증 → 문서 추출·검출 경보 연결**이다. 질문 5개와 최소 제출물의 초안을 실제 공통 입력으로 작성한다.

| 제출물 | 파일 |
|---|---|
| 질문 5개·필요 데이터·답변 한계 | [competency_questions.md](ontology_v1/competency_questions.md) |
| 클래스·관계·속성의 이름·의미·예시 | [schema_tables.md](ontology_v1/schema_tables.md) |
| OWL 어휘 | [ontology.ttl](ontology_v1/ontology.ttl) |
| 핵심 제약 5그룹 | [shapes.ttl](ontology_v1/shapes.ttl) |
| 제약별 통과·실패 예제와 검증 결과 | [shacl_examples.md](ontology_v1/shacl_examples.md), ontology_v1/examples, ontology_v1/validation |
| 재현 코드·처리 내역·미결정 사항 | [work_log.md](ontology_v1/work_log.md), build_ontology_v1.py, verify_ontology_v1.py |
| 데이터 누수·구체적 결함 주의사항 | [leakage_and_defects.md](ontology_v1/leakage_and_defects.md) |

기존 Component 9개는 Station으로 매핑한다. 정적 노드 83개·원본 관계 269개를 보존하며, 원문 PDF 7개와 문서에서 만든 Rule 24개를 별도 룰/설명 프로필에 연결한다. Rule 22개는 SOP-002 표 변환, 2개는 SOP-001 원문 수동 예제다. 정답 86건이나 정답 이벤트 14건을 입력으로 사용하지 않는다.

`ml_metadata.ttl`에는 정적 구조만 있다. `rule_context.ttl`에는 문서·규칙과 스키마 확인용 관측 22개가 있다. 전체 센서 211,200행, 정규화, 평균 윈도우 3개/STUCK 11개, 현재 탐지 결과는 기존 파일을 그대로 사용한다. 이 새 RDF를 탐지나 GraphRAG 코드에 자동 연결한 단계는 아니다.

SHACL은 데이터 형식·필수 관계·출처·임계값 설정·명시적 누수 필드를 검사한다. 문서 해석이나 실제 설치/고장/인과를 증명하는 도구로 보지 않는다. 구현 기준은 [W3C SHACL](https://www.w3.org/TR/shacl/)이며 검증 엔진은 [pySHACL](https://pypi.org/project/pyshacl/)이다.

재현 명령과 의존성은 work_log와 requirements-ontology.txt에 있다. 실제 검증 수치 및 엔진 버전은 ontology_v1/validation/validation_results.json에 기록한다.
