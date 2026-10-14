# ③ 인스턴스 생성 [A] 기존 KG 변환(seed → RDF) 검증 보고서

검증일 2026-10-12. 판정은 산출물 파일, 원본 CSV(`imaks_data/kg_seed/nodes.csv`, `edges.csv`), `harness/checklist.md`만 근거로 했다. 구현 보고서(`reports/seed_to_rdf_impl.md`)는 대상 파일 위치를 찾는 데만 썼다. `ground_truth.csv`는 열지 않았다.

실행 환경: `.venv/Scripts/python.exe`, `PYTHONPATH=src`, `PYTHONIOENCODING=utf-8`, 저장소 루트에서 실행.

- 판정: **PASS**

## 항목별 결과

### 공통 (5항목)
| 항목 | 결과 | 근거 |
|---|---|---|
| `check_raw_unchanged.py` PASS | PASS | `check_raw_unchanged.py` → `PASS: imaks_data/ 원본 불변 (1121개 파일)`, 종료 0. seed_to_rdf를 두 번 다시 실행한 뒤 다시 돌려도 같은 결과 |
| `check_leakage.py` PASS | PASS | 인자 없이 실행했을 때와 `preprocessed ontology_v1 kg_build src` 인자를 줬을 때 모두 `검사한 파일 36개, 금지어 8개, 컬럼 전용 11개` / `PASS: 금지 컬럼 없음`, 종료 0. 스크립트 기본 폴더에 `kg_build`가 있고 CODE_EXT에 `.ttl`이 있어 seed.ttl도 검사됨(check_leakage.py 21~22줄) |
| 코드에 절대 경로 없음 | PASS | `grep -rnE 'C:\\|C:/|/Users/|/home/' src tests --include=*.py` → 일치 0건(rc=1). `settings.py` 변경분은 모두 `REPO_ROOT / ...` 상대 구성(git diff 확인) |
| 큰 산출물·원본이 git 미추적 | PASS | `git ls-files \| grep -E "kg_build\|imaks_data\|seed\.ttl\|seed_to_rdf_counts\|preprocessed\|evaluation"` → 0건. `git check-ignore -v`: `kg_build/seed.ttl`은 `.gitignore:230:/kg_build/`, `reports/seed_to_rdf_counts.md`는 `.gitignore:224:/reports/*`, `imaks_data/kg_seed/nodes.csv`는 `.gitignore:220:imaks_data/`로 무시됨. `src/imaks_kg/kg/*.py`, `tests/test_seed_to_rdf.py`는 무시 대상 아님(출력 없음). `reports/seed_to_rdf_impl.md`는 부정 규칙 `!/reports/*_impl.md`로 추적 대상. 추적 파일 52개 중 가장 큰 파일은 `harness/raw_manifest.json` 162,960바이트 |
| 이상값 삭제·보간·평활화 코드 없음 | PASS | `grep -rnE "interpolate\|fillna\|rolling\|dropna\|smooth\|savgol\|ewm\|\.drop\(\|clip\(" src` → 0건. seed_to_rdf.py는 값을 `Literal(row[c])` 원본 문자열 그대로 넣음(seed_to_rdf.py `_add_entity`). 독립 스크립트로 Station 4개 속성, Sensor 4개 속성이 CSV 값과 문자열로 같음을 확인(아래) |

### ③ 인스턴스 생성 (3항목)
| 항목 | 결과 | 근거 |
|---|---|---|
| 노드·엣지 수가 115/341과 일치하거나 차이 사유가 reports에 있음 | PASS | 아래 "독립 대조" 1·2. CSV를 직접 센 값: 노드 115(Person 44, Sensor 22, AnomalyEvent 14, SafetyEvent 10, Component 9, Maintenance 8, Zone 7, System 1), 엣지 341(13개 (type, from label, to label) 조합). `reports/seed_to_rdf_counts.md`의 원본 열 13줄과 노드 8줄이 모두 일치. 변환 31 + 이월(B) 8 + 이월(⑦) 14 + 제외 62 = 115, 변환 47 + 이월(B) 16 + 이월(⑦) 15 + 제외 263 = 341을 직접 합산해 확인. 모든 미변환 종류에 사유 열이 있음 |
| `run_shacl.py`로 적합 판정 | PASS | `run_shacl.py --data kg_build/seed.ttl --ont ontology_v1/ontology.ttl` → `Conforms: True` / `PASS: SHACL 적합`, 종료 0. 스크립트가 `inference="none"`임을 확인(run_shacl.py 43줄). 누수 가드 `--shapes guards/leakage_shapes.ttl`로도 PASS. 검증기가 공허하지 않음을 보려고 seed.ttl 복사본(scratchpad)에 hasSensor 1개 추가와 sourceKind 제거를 넣자 S1 위반 1건, S7 위반 56건으로 FAIL |
| 원본 ID 보존, 원본 행으로 역추적 | PASS | 아래 "독립 대조" 4. 노드 31개 모두 `sourceNodeId`=nodeId, Provenance(fileName=`imaks_data/kg_seed/nodes.csv`, sourceRowId=nodeId) 정확히 1개. 엣지 Provenance 25개(hasSensor 22, feedsInto 3)의 `row:<n>`을 `edges.csv` n번째 데이터 행으로 열어 보니, hasSensor는 두 행이 정확히 (Component→Sensor monitors, Sensor→Component monitors) 쌍이고 feedsInto는 해당 feeds_into 행과 일치 |

## 독립 대조 (구현 코드 import 없이 csv + rdflib로 작성한 스크립트)

스크립트: scratchpad `verify_seed.py`(저장소 밖). 결과 `FAILS: 0`.

1. **원본 개수**: nodes 115행(nodeId 고유 115), edges 341행. 엣지 조합: authorized_for(Person→Zone) 218, contains(System→Zone) 7, contains(Zone→Component) 9, correlates_with(Sensor→Sensor) 1, detected_in(SafetyEvent→Zone) 10, feeds_into(Component→Component) 3, involves(SafetyEvent→Person) 10, monitors(Component→Sensor) 22, monitors(Sensor→Component) 22, part_of(Component→System) 9, resolves(Maintenance→Sensor) 8, triggers(Sensor→AnomalyEvent) 14, triggers(Sensor→Maintenance) 8.
2. **seed.ttl 개수**: 트리플 482. rdf:type은 Station 9, Sensor 22, Provenance 56뿐. 술어: type 87, identifier 31, sourceNodeId 31, stationType 9, zone 9, sensorType 22, unit 22, hasSensor 22, feedsInto 3, hasProvenance 56, sourceKind 56, fileName 56, sourceRowId 78(= 노드 31 + hasSensor 22×2 + feedsInto 3).
3. **변환 규칙**
   - Station 9: identifier=name, sourceNodeId=nodeId, stationType, zone가 각 1개이고 CSV 값과 같음. 그 밖의 술어 없음.
   - Sensor 22: identifier=name, sourceNodeId, sensorType, unit이 CSV와 같음. `nominalValue/warnLo/warnHi/critLo/critHi` 및 `nominal|warn|crit`로 시작하는 술어가 그래프 전체에 0건.
   - hasSensor: monitors 정방향 집합과 역방향(뒤집은) 집합이 같고 22쌍. seed.ttl의 hasSensor 22쌍이 이 집합과 정확히 같음. 모든 Sensor가 정확히 1개 Station에 연결, 주어는 모두 Station, 목적어는 모두 Sensor.
   - feedsInto 3쌍이 feeds_into 3행과 정확히 같음.
4. **Provenance**: 56개 모두 sourceKind="seedCsv", fileName은 nodes.csv 또는 edges.csv 1개, sourceRowId 1개 이상, 고아 없음. 엣지 출처는 각각 노드 1개에만 매달림(hasSensor → Sensor, feedsInto → 주어 Station).
5. **제외 확인**: AnomalyEvent 및 하위 5클래스, Rule/MaintenanceRule, Maintenance, Person, Zone, System, SafetyEvent, Component 클래스 0건. triggers, correlatesWith, appliesToSensor, resolves, monitors, contains 등 술어 0건. 제외 노드(84개)의 nodeId가 seed.ttl 텍스트에 0건. Zone 이름 6개가 리터럴로 나오지만 모두 Station의 `zone` 값(흡수 규칙대로)임.

## 그 밖의 요청 확인
| 항목 | 결과 | 근거 |
|---|---|---|
| 단위 테스트 | PASS | `python -m unittest discover -s tests` → `Ran 71 tests ... OK` |
| 결정성 | PASS | 실행 전 seed.ttl SHA-256 `cc9ac584943fd6755fa7bab716c0f7416f71dc69b9b0b510c28f739f2ca2d2b7`, counts.md `9036bb6c…15ae`. `python -m imaks_kg.kg.seed_to_rdf`를 두 번 다시 실행한 뒤에도 두 해시 모두 같음. 실행 출력: 노드 `{'원본': 115, '변환': 31, '이월(B)': 8, '이월(⑦)': 14, '제외': 62}`, 엣지 `{'원본': 341, '변환': 47, '이월(B)': 16, '이월(⑦)': 15, '제외': 263}` |
| ⑦ 경로가 main에서 호출되지 않음 | PASS | `grep -rn "post7\|seed_events" src` → seed_to_rdf.py에는 docstring(10줄)과 사유 문자열(45줄)만 있고 import·호출 없음. seed_events_post7.py에 `main`·파일 쓰기 없음(함수는 `_source_col_of`, `_prov`, `build_post7_graph`뿐) |
| 코드가 ground_truth를 읽지 않음 | PASS | `grep -rn "ground_truth\|nodes_factory" src` → 0건. 입력은 `KG_SEED_DIR / "nodes.csv"`, `"edges.csv"`(seed_to_rdf.py 27~28줄) 두 개뿐이고 `read_csv_rows`는 받은 경로 하나만 엶(io_utils.py 45~47줄). 테스트(test_seed_to_rdf.py 153줄)는 파일명 문자열 검사용으로만 씀 |
| schema_tables 7장 대조 | PASS | Component→Station(sourceNodeId, stationType, zone), Sensor(identifier=name, sensorType, unit), monitors 44 → hasSensor 22("두 줄을 같은 관계에 연결해 보존": Provenance 하나에 두 행 ID), feeds_into → feedsInto, Zone·System·Person·SafetyEvent와 해당 엣지 미적재, AnomalyEvent·correlates_with는 ⑦ 이후. 모두 산출물과 일치 |

## 불합격 사유와 수정이 필요한 위치
없음.

## 미확인 항목과 이유
없음(판정 대상 8항목 전부 직접 확인).

## 판정에 포함하지 않는 관찰 (설계상 한계·개선 후보)
1. **shapes.ttl이 Sensor의 임계값 속성을 막지 않는다.** seed.ttl 복사본에 `ST01_FILLING_TMP im:nominalValue "22.0"`를 넣어도 SHACL 위반이 나오지 않았다. 현재 seed.ttl에는 임계값이 없음을 직접 질의로 확인했지만, 이 보장은 코드의 허용목록(`SENSOR_COLS`)과 테스트에만 의존한다. B 단계에서 ThresholdRule을 넣을 때 Sensor에 임계값이 붙지 않게 하는 shape(예: sh:closed 또는 nominalValue 등의 domain 대상 제한) 추가를 검토할 만하다.
2. **관계 출처가 노드에 붙는다.** hasSensor 출처는 Sensor에, feedsInto 출처는 주어 Station에 붙어 있어 Station에는 노드 출처와 feedsInto 출처가 섞인다. 어느 관계의 출처인지는 IRI 이름(`prov_seed_hasSensor_…`)과 edges.csv 행으로만 구분된다. 독립 스크립트로 역추적은 가능했지만, Provenance에 관계 종류 속성이 없어 질의만으로 구분하기는 어렵다(②의 결정 사항).
3. **엣지 행 식별자 `row:<n>`은 edges.csv 행 순서에 의존한다.** edges.csv에는 엣지 ID 컬럼이 없어(`fromId,toId,type,ruleRef`) 불가피하다. Provenance에 파일 해시가 없어서 원본이 바뀌면 번호가 어긋나도 그래프만으로는 알 수 없다. 해시는 무시 대상인 counts.md에만 있다.
4. **`reports/seed_to_rdf_counts.md`는 `/reports/*` 규칙으로 git 미추적이다.** 체크리스트의 "차이 사유가 reports에 있다"는 로컬 파일 기준으로는 충족하지만, 저장소에서는 impl 보고서 4장의 요약으로만 남는다.
5. **Component의 `description` 컬럼은 옮기지 않았다**(온톨로지에 속성 없음). counts.md "옮기지 않은 컬럼"에 기록되어 있다.
6. `.gitignore`에 이번 범위 밖인 `/.deps/`, `/data/` 줄도 함께 추가돼 있다(작업 전 변경이라고 impl 보고서에 적혀 있음). 판정에는 영향 없다.
7. 재실행하면 `reports/seed_to_rdf_counts.md`가 다시 써진다. 검증 중 재실행했지만 해시가 같아 내용은 바뀌지 않았다.
