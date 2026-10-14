# ③ 기존 KG 변환 + Rule·Document 승격 구현 보고서 (2026-10-14)

범위: 작업 A(seed 변환)와 작업 B(Document 7개, MaintenanceRule 8개). OperationalRule·ThresholdRule·AccessRule은 만들지 않았다(④ 범위).

## 1. 만든 파일
- `src/imaks_kg/kg/__init__.py`, `src/imaks_kg/kg/convert_seed.py` (변환 본체)
- `tests/test_kg_convert.py` (산출물 불변 조건 8개)
- `src/imaks_kg/settings.py`: 경로 상수 2줄 추가(`RAW_KG_SEED_DIR`, `KG_BUILD`). CRLF 유지.
- `.gitignore`: `/kg_build/` 한 줄 추가(CRLF).
- 산출물(git 제외): `kg_build/instances/{stations,sensors,documents,maintenance_rules,has_sensor,feeds_into,applies_to_sensor,provenance}.csv`, `kg_build/instances/instances.ttl`, `kg_build/mapping/maint_seed_vs_sop003.csv`, `kg_build/summary.json`(개수·해시만)

## 2. 실행 방법
```
$env:PYTHONPATH="src"; .venv\Scripts\python.exe -m imaks_kg.kg.convert_seed
.venv\Scripts\python.exe .claude/skills/stage-check/scripts/run_shacl.py --data kg_build/instances/instances.ttl --ont ontology_v1/ontology.ttl --shapes ontology_v1/shapes.ttl
```
입력(읽기 전용): `imaks_data/kg_seed/nodes.csv`, `edges.csv`, `preprocessed/documents/doc_manifest.csv`, `tables.jsonl`, `chunks.jsonl`.

쓰지 않은 입력: `nodes_factory.csv`는 nodeId 충돌 6건이 있어 쓰지 않았다(지시에 따름. 충돌 내용은 직접 확인하지 않음). 정답 규칙 파일은 열지도 읽지도 않았고 코드에 이름도 없다.

## 3. 변환 규칙과 구현 메모
- Component 9 -> Station: identifier=name, sourceNodeId=nodeId, stationType, zone=원본 zone 값 그대로.
- Sensor 22 -> Sensor: identifier=name, sensorType, unit(원문 그대로, 예 `°C`), sourceNodeId.
- monitors 44줄 -> hasSensor 22개. 코드가 (a) 모든 쌍이 양방향 2줄인지, (b) 센서마다 스테이션이 정확히 1개인지 검사하고 어긋나면 예외를 낸다. 원본 두 줄의 위치는 `has_sensor.csv`의 `sourceEdgeRows`(`edges.csv:L<행>`, 헤더=1행)에 보존했다.
- feeds_into 3 -> feedsInto 3 (`feeds_into.csv`에 원본 행 위치).
- Document 7: doc_manifest.csv의 doc_id, file(저장소 상대 경로), file_sha256, pages를 그대로 옮겼다. pageCount는 xsd:positiveInteger.
- Maintenance 8 -> MaintenanceRule: identifier=ruleId, sourceNodeId, responseText=원본 action, priority.
- appliesToSensor 8: `Sensor->Maintenance triggers`와 `Maintenance->Sensor resolves`가 같은 8쌍인지 코드로 비교했다. 같았다(다르면 예외). 원본 두 줄의 위치를 `applies_to_sensor.csv`에 둘 다 보존했다. triggers 중 Sensor->AnomalyEvent는 도착점이 Maintenance인 것만 골라서 제외했다.
- sourceDocument=SOP-003: `tables.jsonl`의 SOP-003 표(`SOP-003:p1:table1`, 1쪽)에서 Rule ID 열에 MAINT-01~08이 모두 있고, `chunks.jsonl`의 SOP-003 표 청크에도 `Rule ID: MAINT-0x;`가 모두 있음을 코드가 확인한 뒤에만 연결한다(확인 실패 시 연결하지 않는 분기 있음). 이번 실행은 8개 모두 확인됐다.
- Provenance 39개(Station 9 + Sensor 22 + MaintenanceRule 8): sourceKind="seedCsv", fileName=`imaks_data/kg_seed/nodes.csv`, sourceRowId=nodeId, fileSha256=nodes.csv 해시(shapes S7 필수는 fileName, sourceRowId이며 fileSha256은 추가). Document에는 Provenance를 달지 않았다(shapes에서 요구하지 않음).
- IRI: `https://example.org/imaks/id/<이름>`(ontology_v1/examples와 같은 inst: 접두어), Provenance는 `prov_<nodeId>`.
- TTL은 rdflib으로 직렬화했다.

## 4. 실행한 검증과 결과
1. 변환 실행: 개수 Station 9, Sensor 22, hasSensor 22, feedsInto 3, MaintenanceRule 8, Document 7, appliesToSensor 8, Provenance 39. 모두 지시한 기대값과 일치. 센서마다 hasSensor 정확히 1개는 변환 코드와 테스트 둘 다에서 확인.
2. `run_shacl.py` (ont 포함, 추론 없음): `Conforms: True`, "PASS: SHACL 적합". 위반 없음이라 shapes·ontology 수정 제안은 없다.
3. 노드·엣지 대조(체크리스트 ③ 1항): 원본 nodes 115 / edges 341 중 적재한 것은 Component 9, Sensor 22, Maintenance 8(노드 39), 엣지는 monitors 44줄->22, feeds_into 3, triggers+resolves 중 Maintenance 연결 16줄->8. 적재하지 않은 것은 AnomalyEvent 14, Person 44, SafetyEvent 10, Zone 7, System 1(노드 76)과 해당 엣지이며 이유는 schema_tables.md 6·7장. 라벨·타입별 원본 개수는 `kg_build/summary.json`에 있다. 원본 엣지가 341줄인데 `edges.csv`는 헤더 포함 342줄이라 L번호가 데이터행 번호+1이다.
4. `check_leakage.py`: PASS(금지 컬럼 없음, 44개 파일). `check_raw_unchanged.py`: PASS(imaks_data 1121개 파일 불변).
5. 역추적: `tests/test_kg_convert.py`가 stations/sensors/maintenance_rules의 sourceNodeId, provenance의 sourceRowId로 `nodes.csv` 행을 찾아 라벨과 값(이름, 타입, 단위, zone, action, priority)이 같은지 전수 대조하고, 엣지 위치(`edges.csv:L<행>`)로 원본 엣지 행을 찾아 타입·양끝 nodeId가 같은지 전수 대조한다. 8개 테스트 통과. 샘플이 아니라 전수다.
6. 전체 단위 테스트(`python -m unittest discover -s tests`): 58개 실행 OK (기존 50 + 신규 8, 115초). 이후 테스트 파일의 파일 핸들 경고를 고쳐 test_kg_convert만 다시 실행해 8개 OK를 확인했고, 전체 재실행은 하지 않았다.

## 5. 매핑표 `kg_build/mapping/maint_seed_vs_sop003.csv` 결과
원본 MAINT 노드와 SOP-003 표 행을 같은 ruleId로 대조했다. 두 쪽 텍스트를 그대로 싣고(SOP 쪽은 원문 줄바꿈 포함 `Raw`와 공백 정리본 `Normalized` 둘 다) 일치 여부만 표시했으며 어느 쪽도 고치지 않았다.
- priority, 센서 유형, 스테이션 이름은 8행 모두 일치.
- action 문구(공백 정리본 기준): 일치 3건(MAINT-05, 06, 08), 불일치 5건. 불일치는 MAINT-01 `Inspect and lubricate main bearing` vs `Inspect and lubricate bearing`, MAINT-02 `Inspect sealing jaw alignment` vs `Inspect sealing jaw`, MAINT-03 `Replace TEN sensor` vs `Replace sensor`, MAINT-04 `Inspect inlet filter and pump` vs `Inspect filter and pump`, MAINT-07 `Activate emergency ventilation; notify safety officer` vs `Emergency ventilation; notify safety officer`. 기준은 CSV의 `actionExactMatch` 열이다.
- 이 파일에는 SOP-003 표의 Trigger 열도 같이 담았다. 원본 Maintenance 노드에는 Trigger가 없다(저장하지 않은 정보).

## 6. 가정과 판단
- `responseText`에는 원본 action을 넣었다(SOP-003 표 문구가 아니다). 두 문구가 다른 5건은 매핑표로만 대조하고 통일하지 않았다. 어느 쪽을 정본으로 할지는 미결정.
- 센서-스테이션은 Component 쪽 끝을 Station으로 두었다(monitors 방향이 원본에서 양쪽이라 라벨로 방향 판정).
- Provenance는 엔티티마다 1개(39개)다. nodes.csv 같은 파일 해시는 모든 Provenance에 같은 값이 들어간다.
- 엣지(hasSensor, feedsInto, appliesToSensor)에는 RDF Provenance를 달지 않고 CSV에 원본 행 위치만 남겼다(온톨로지의 hasProvenance domain에 관계가 없음).

## 7. 알려진 한계
- SOP-003 확인은 `tables.jsonl`/`chunks.jsonl`(전처리 결과)에 의존한다. PDF 원본을 다시 열어 확인하지는 않았다.
- TTL 직렬화를 rdflib에 맡겨 바이트 단위 재현성(트리플 순서)은 확인하지 않았다. summary.json에 TTL 해시를 남기지만 실행마다 같은지는 미확인.
- Neo4j 적재는 이번 범위 밖(CSV/TTL까지만).
- System 노드 1개(iMAKS)의 처리는 미결정 그대로 두었다(적재 안 함).
- 원본 Sensor 노드의 임계값 열(nominalValue, warnHi 등)은 적재하지 않았다(ThresholdRule 쪽 범위, ④).

## 8. 미결정
- MaintenanceRule의 responseText 정본(원본 action vs SOP-003 문구).
- System 노드 처리, Task 클래스(work_log 2026-10-14에서 보류).
- CLAUDE.md·work_log.md·ontology_v1/·harness/는 수정하지 않았다. 필요한 수정 제안 없음.

커밋하지 않았다. verifier 검증이 필요하다.
