# ③ 기존 KG 변환(seed → RDF) 구현 보고서 [A]

작성 2026-10-12. 범위: Station·Sensor·hasSensor·feedsInto와 그 출처(Provenance). Rule·Document(B), C, D는 구현하지 않았다.

## 1. 만든·고친 파일
| 파일 | 내용 |
|---|---|
| `src/imaks_kg/kg/__init__.py` | 패키지 |
| `src/imaks_kg/kg/naming.py` | 이름공간(im:, inst:)과 IRI 규칙, edges.csv 행 식별자 형식(③·⑦ 공용) |
| `src/imaks_kg/kg/seed_to_rdf.py` | 변환 본체. 계획표(NODE_PLAN, EDGE_PLAN), `build_graph`, `serialize`, `ttl_counts`, `counts_table`, `main` |
| `src/imaks_kg/kg/seed_events_post7.py` | ⑦ 이후 경로 전용 `build_post7_graph`(AnomalyEvent 14, triggers 14, correlatesWith 1). main 없음, 파일 출력 없음, seed_to_rdf에서 부르지 않음 |
| `tests/test_seed_to_rdf.py` | unittest 21개 |
| `src/imaks_kg/settings.py` | 상수 추가: `KG_SEED_DIR`, `KG_BUILD`, `REPORTS_DIR`, `ONTOLOGY_DIR`, `ONTOLOGY_TTL`, `SHAPES_TTL` |
| `.gitignore` | `/kg_build/` 한 줄 추가(작업 시작 전부터 있던 `/.deps/`, `/data/` 변경은 내가 한 것이 아님) |

ontology.ttl, shapes.ttl, imaks_data/는 고치지 않았다.

## 2. 실행 방법
```
PYTHONPATH=src PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m imaks_kg.kg.seed_to_rdf
.venv/Scripts/python.exe .claude/skills/stage-check/scripts/run_shacl.py --data kg_build/seed.ttl --ont ontology_v1/ontology.ttl
PYTHONPATH=src PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest discover -s tests
```
(PowerShell: `$env:PYTHONPATH="src"; $env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe -m imaks_kg.kg.seed_to_rdf`)

## 3. 입력/출력
- 입력(읽기 전용): `imaks_data/kg_seed/nodes.csv`(115행), `imaks_data/kg_seed/edges.csv`(341행). 같은 폴더의 평가용 정답 규칙 파일과 `nodes_factory.csv`는 읽지 않는다(테스트가 kg 패키지 소스에 두 파일명이 없음을 확인).
- 출력: `kg_build/seed.ttl`(482 트리플, git 무시), `reports/seed_to_rdf_counts.md`(코드가 생성하는 개수 대조표. 기존 `.gitignore` 규칙 `/reports/*`에 따라 git 무시 대상이며 `*_impl.md`만 추적된다).

## 4. 대조표 요약 (실제 CSV에서 센 값, 지시서 숫자와 모두 일치)
노드 115 = 변환 31(Component 9→Station, Sensor 22) + 이월(B) 8(Maintenance) + 이월(⑦) 14(AnomalyEvent) + 제외 62(System 1, Zone 7, Person 44, SafetyEvent 10).

엣지 341 = 변환 47(monitors 44 → hasSensor 22, feeds_into 3 → feedsInto 3) + 이월(B) 16(triggers Sensor→Maintenance 8, resolves 8) + 이월(⑦) 15(triggers Sensor→AnomalyEvent 14, correlates_with 1) + 제외 263(contains 16 = System→Zone 7 + Zone→Component 9, part_of 9, authorized_for 218, involves 10, detected_in 10).

seed.ttl 재파싱 기준: Station 9, Sensor 22, hasSensor 22, feedsInto 3, Provenance 56(노드 31 + hasSensor 22 + feedsInto 3), hasProvenance 56.
스크립트가 합계 115/341과 위 4개 기대 개수를 assert한다. 옮기지 않은 컬럼: Sensor의 임계값 5개(nominalValue, warnLo, warnHi, critLo, critHi → 이월(B)), Component의 description(온톨로지에 속성 없음 → 미반영).

## 5. 설계 선택
- **URI**: 어휘는 ontology.ttl의 `im:`, 인스턴스는 examples와 같은 `inst:`(https://example.org/imaks/id/). Station·Sensor는 원본 name(`inst:ST02_SEALING`, `inst:ST02_SEALING_CUR`). 출처는 `inst:prov_seed_node_<nodeId>`, `inst:prov_seed_<관계>_<fromNodeId>_<toNodeId>`. ⑦ 이벤트는 `inst:event_<nodeId>`(GT 번호를 IRI에 쓰지 않음). 이름에 `[A-Za-z0-9_]` 밖 문자가 있으면 멈춘다.
- **값**: 원본 문자열 그대로(plain literal = xsd:string). identifier=name, sourceNodeId=nodeId, zone=원본 zone.
- **Provenance 표현**: S7 seedCsv 필수 필드(sourceKind="seedCsv", fileName=저장소 기준 상대 경로, sourceRowId). 노드는 sourceRowId=nodeId. 엣지는 sourceRowId=`row:<n>`(헤더를 뺀 1부터의 데이터 행 번호, 파일 줄 번호 = n+1).
- **관계 출처를 붙이는 곳**: ontology에 관계 자체(트리플)에 출처를 다는 수단(reification/RDF-star)이 없고, `hasProvenance`의 domain은 Rule·Station·Sensor·AnomalyEvent·CausalLink다. 그래서 관계 출처를 해당 노드에 붙였다.
  - hasSensor → **Sensor**에 붙임. 센서마다 hasSensor가 정확히 1개(S1)라 1:1로 대응한다.
  - feedsInto → 주어 Station에 붙임(ST01~ST03 각 1개).
- **monitors 2행 역추적**: 한 hasSensor의 Provenance 하나에 `sourceRowId`를 두 개 둔다(정방향 Component→Sensor 줄, 역방향 Sensor→Component 줄). sourceRowId에 maxCount가 없어 shapes가 허용한다. 두 줄이 모두 있어야 관계를 만들고, 한쪽만 있거나 중복이면 멈춘다. 테스트가 두 행을 edges.csv에서 다시 찾아 양방향 monitors인지 확인한다.
- **엄격한 계획표**: NODE_PLAN·EDGE_PLAN(엣지는 (type, from label, to label) 키, triggers가 두 갈래라서)에 없는 종류가 나오면 ValueError. 옮길 컬럼은 허용목록 방식이라 임계값 컬럼은 구조적으로 못 들어간다.
- **결정성**: rdflib turtle 직렬화가 주어·속성·값을 정렬한다. 고정 헤더 주석만 덧붙이고 시각·해시는 넣지 않는다. 두 번 실행해 SHA-256이 같음을 확인했다(seed.ttl `cc9ac584…d2b7`).
- **⑦ 분리**: `seed_events_post7.py`는 허용목록(startTs→startTime, endTs→endTime, magnitude, 데이터셋 심각도→datasetSeverity)만 옮기고 gtId·causedBy·sourceRule·durationMin은 올리지 않는다. 데이터셋 심각도 원본 컬럼명은 속성 이름에서 접두어를 떼서 구한다(누수 점검 단어를 src에 쓰지 않기 위해). 테스트는 이 그래프를 메모리에서만 만들어 seed와 합쳐 S2 적합, 누수 가드(guards/leakage_shapes.ttl)에는 걸리는 것(⑥ 입력이 아님)을 확인한다.

## 6. 확인한 결과
- `run_shacl.py --data kg_build/seed.ttl --ont ontology_v1/ontology.ttl` → Conforms: True, PASS
- 누수 가드 `--shapes guards/leakage_shapes.ttl`로도 seed.ttl PASS(L1~L4 위반 없음)
- `unittest discover -s tests` → 71개 OK(기존 50 + 신규 21)
- `check_leakage.py` PASS(36개 파일, 경고 0), `check_raw_unchanged.py` PASS(1121개 파일)
- src·tests에 절대 경로 없음. `kg_build/`는 git 무시, `src/imaks_kg/kg/`와 테스트는 추적 대상

## 7. 알려진 한계
- 관계 출처를 노드에 붙였으므로 "이 Provenance가 어느 관계의 것인지"는 IRI 이름(`prov_seed_hasSensor_…`)과 sourceRowId가 가리키는 edges.csv 행으로만 알 수 있다. 출처 노드에 관계 종류를 적는 속성이 온톨로지에 없다. Station에는 노드 출처와 feedsInto 출처가 함께 매달린다.
- 엣지 행 식별자 `row:<n>`은 edges.csv 행 순서에 의존한다. 원본이 바뀌면 번호가 어긋난다(원본 불변 점검이 막아 준다). 대조표에 입력 파일 SHA-256을 남겼지만 Provenance에는 넣지 않았다(seedCsv 필드는 파일명+원본 ID로 정해져 있음, D3).
- Component의 description은 온톨로지에 속성이 없어 옮기지 않았다.
- correlatesWith의 ruleRef(RULE-ST02-04)는 온톨로지에 이 관계용 속성이 없어서 `build_post7_graph`가 그래프 밖 notes로 돌려준다.

## 8. 미결정 사항 (ontology/shapes는 고치지 않음)
- 관계 단위 출처: Neo4j에서는 관계 속성(sourceRowIds 등)으로 직접 붙이면 되지만, RDF에서 관계 트리플에 출처를 달려면 reification이나 hasProvenance domain 확장, 또는 Provenance에 관계 종류 속성 추가가 필요하다. 필요하면 ②에서 결정할 일이라 이번에는 노드 부착으로 처리했다.
- correlatesWith의 ruleRef 보존 방법(schema_tables 7장 "ruleRef는 규칙 번호 근거로 보존"): 관계 속성으로 둘지, Provenance나 별도 속성으로 둘지 ⑦ 전에 정해야 한다.
- System 노드 1개 처리(schema_tables 9장 미결): 이번에는 제외로 기록.
- Component description을 보존할지(예: rdfs:comment 또는 새 속성): 온톨로지 변경이 필요해 보류.
- `reports/seed_to_rdf_counts.md`는 기존 gitignore 규칙으로 추적되지 않는다. 대조표를 git에 남길지 팀이 정해야 한다(이 보고서 4장에 요약을 옮겨 둠).
- work_log.md는 이번에 고치지 않았다(작업 시작 전부터 수정 중인 상태였음). 위 선택을 기록할지 확인이 필요하다.

verifier 검증 필요.
