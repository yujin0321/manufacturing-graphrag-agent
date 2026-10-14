# ③ 기존 KG 변환 v2 구현 보고서 (2026-10-14)

이전 보고서(`reports/kg_convert_impl.md`)는 고치지 않았다. 이번에는 출처 장부, 문서 출처, 구조 방어, PDF 해시 대조를 더했다.

## 1. 바뀐 점
수정한 파일은 `src/imaks_kg/kg/convert_seed.py`와 `tests/test_kg_convert.py` 두 개다. CLAUDE.md, work_log.md, ontology_v1/, harness/, .claude/는 건드리지 않았다.

1. **트리플 장부.**
   - `Ledger.add(s,p,o,evidence)`가 `g.add`를 대신한다. 근거 없이 호출하면 예외를 낸다.
   - 변환 끝에서 `check_ledger_complete`가 그래프의 모든 트리플이 근거를 1개 이상 갖는지 본다. 장부에만 있는 트리플도 오류로 처리한다.
   - 결과는 `kg_build/instances/triple_sources.jsonl`에 쓴다. 한 줄은 `{"triple":[s,p,o의 n3], "sources":[...]}`이고 triple 기준으로 정렬한다.
   - 근거 형식:
     - nodes.csv 유래는 `{file,rowId=nodeId,sha256}`이다.
     - edges.csv 유래는 `{file,line,sha256}`이다. line은 파일 줄 번호이고 헤더가 1이다.
     - 문서 유래는 `{document,tableId,rowIndex,textSha256}`이다.
     - Document 노드의 속성 트리플은 `doc_manifest.csv` 행(`rowId=doc_id`)을 근거로 한다. `sourcePath`와 `sourceSha256` 트리플에는 실제 PDF 파일(file, 재계산한 sha256)도 근거로 붙인다.
   - hasSensor 22개는 monitors 두 줄을, appliesToSensor 8개는 triggers·resolves 두 줄을 모두 근거로 가진다. 합치거나 지우지 않았다. 테스트에서 확인한다.
   - `summary.json`에 `tripleCount`(585), `ledgerComplete: true`, `pdfHashesRecomputed: true`를 추가했다. 장부의 해시는 `outputSha256`에 들어간다.
2. **MaintenanceRule의 SOP-003 문서 출처.**
   - 규칙마다 `sourceKind="document"`인 Provenance를 `prov_doc_<ruleId>`로 추가하고 `hasProvenance`로 연결했다. 기존 seedCsv Provenance는 그대로이므로 규칙당 2개다.
   - 필드는 page, tableId, rowIndex, colIndex, sourceQuote, textSha256이다.
   - `extractionMethod="seedCsv"`도 MaintenanceRule에 추가했다.
   - 문서 Provenance 8개의 표 형태 사본을 `kg_build/instances/provenance_document.csv`에 새로 썼다. 기존 `provenance.csv`는 seedCsv 39행 그대로다. 바이트를 보존하고, 기존 테스트가 이 파일의 fileName이 모두 nodes.csv라고 가정하기 때문이다.
3. **구조 방어.**
   - `assert_no_later_stage_items`가 AnomalyEvent, Spike, Drift, StuckSensor, OutOfRange, Correlated, Person, CausalLink 타입과 causallyAffects, triggers, correlatesWith 트리플을 검사하고, 하나라도 있으면 예외를 낸다. TTL을 쓰기 전에 호출한다.
   - 센서마다 스테이션 1개 검사는 그대로 있다.
4. **Document 무결성.**
   - `verify_manifest_hashes`가 PDF 7개를 읽어 SHA-256을 다시 계산한다. manifest 값과 다르거나 파일이 없으면 예외를 낸다. 경로 기준은 `root` 인자로 바꿀 수 있어 테스트에서 임시 폴더를 쓴다.
   - **title은 추가하지 않았다.** `doc_manifest.csv`의 열은 doc_id, file, pages, file_sha256뿐이다. 청크 첫 줄은 SOP-001에서 "Standard Operating Procedures — Production Line A"처럼 문서 제목이 아닌 서식이 섞여 있다. 문서마다 제목 위치를 결정적으로 정할 규칙이 없어 추정이 된다. 그래서 만들지 않았다. 필요하면 doc_manifest에 title 열을 전처리에서 추가해야 한다.

## 2. rowIndex·colIndex 규약
- 둘 다 **1부터** 센다. 표 헤더 행이 rowIndex=1이고 첫 열이 colIndex=1이다. 온톨로지가 positiveInteger라서다.
- MAINT-01은 SOP-003:p1:table1의 rowIndex=2, colIndex=1이다. MAINT-08은 rowIndex=9다.
- **기존 매핑표 `maint_seed_vs_sop003.csv`의 `sop003RowIndex`는 0부터다**(헤더=0, MAINT-01=1). 이 파일은 바이트를 그대로 두었다. 그래서 **같은 규칙에서 두 파일의 행 번호가 1씩 어긋난다**(Provenance는 1-기반, 매핑표는 0-기반). 소비자가 혼동하지 않게 표기를 통일할지는 미결정이다.
- 위치는 SOP-003의 모든 표에서 `rows_normalized`의 셀이 ID와 정확히 같은 곳을 센다. 0번이나 2번 이상이면 예외를 낸다. 이번 실행은 8개 모두 1번씩이었다.
- sourceQuote는 `rows_normalized`(공백 정리본)의 그 행 셀들을 ` | `로 이은 문자열이다. 원문 줄바꿈(`rows_raw`)은 쓰지 않았다. textSha256은 sourceQuote를 UTF-8로 인코딩한 SHA-256이다.
- sourceQuote에는 SOP-003 표 텍스트에 있던 깨진 문자가 그대로 들어간다(MAINT-05~07의 온도 기호 자리 `��`). 전처리 산출물이 이미 그렇고 고치지 않았다. PDF 원문이 정말 그런지는 미확인이다.

## 3. 실행한 검증과 결과
실행 환경은 `.venv`다.

- `python -m imaks_kg.kg.convert_seed`: 개수는 Station 9, Sensor 22, hasSensor 22, feedsInto 3, MaintenanceRule 8, Document 7, appliesToSensor 8, **Provenance 47**이다. 47은 seedCsv 39에 문서 8을 더한 값이다. 개수 일치로 출력됐다. 트리플은 505개에서 585개로 늘었다. 증가한 80개는 문서 Provenance 8개 x 9트리플(type, sourceKind, page, tableId, rowIndex, colIndex, sourceQuote, textSha256, hasProvenance 연결)이 72개, extractionMethod가 8개다.
- `run_shacl.py --data kg_build/instances/instances.ttl --ont ontology_v1/ontology.ttl --shapes ontology_v1/shapes.ttl`: Conforms: True, "PASS: SHACL 적합".
- `check_leakage.py`: PASS. `check_raw_unchanged.py`: PASS(imaks_data 1121개 파일 불변). `check_secrets.py`: PASS.
- 전체 단위 테스트 `python -m unittest discover -s tests`의 마지막 요약: `Ran 77 tests in 36.975s` / `OK`. 새 테스트는 `KgConvertV2`의 7개다.
  - 장부 완결성
  - 이중 근거 보존
  - 규칙당 Provenance 2개와 S7 필수 필드 보유(SHACL 자체는 위의 run_shacl이 판정)
  - 근거 없는 트리플 거부
  - 금지 타입·관계 검출 시 예외
  - PDF 해시 불일치와 파일 없음 시 예외
  - 위치 검색이 정확히 1번일 때만 통과
- 새 테스트가 `imaks_kg`를 import하므로 `tests/test_kg_convert.py` 안에서 `sys.path`에 `src`를 넣었다. PYTHONPATH 없이도 돌아간다.
- **기존 출력 바이트 비교.** 변경 전에 `kg_build`를 복사해 두고 새 실행 결과와 `cmp`로 비교했다. stations, sensors, documents, maintenance_rules, has_sensor, feeds_into, applies_to_sensor, provenance 8개 CSV와 매핑표 CSV는 **바이트가 같았다.** `instances.ttl`과 `summary.json`은 새 트리플과 필드 때문에 달라졌다.
- **재실행 재현성.** 변환을 두 번 실행해 `kg_build/instances/*` 11개 파일이 바이트까지 같았다. 여기에는 `instances.ttl`, `triple_sources.jsonl`, `provenance_document.csv`가 포함된다. summary.json은 두 번째 실행 결과와는 비교하지 않았다. 다른 프로세스의 rdflib 직렬화 순서가 같은지는 이 환경에서 두 번만 확인했다.

## 4. 가정
- "원본 파일"의 해시는 파일 전체 해시이고, 같은 파일의 행들은 같은 값을 가진다.
- Document 속성 트리플의 근거로 전처리 산출물 `doc_manifest.csv`를 썼다. PDF 직접 근거는 sourcePath와 sourceSha256에만 붙였다. 다른 속성(pageCount 등)을 PDF에서 직접 확인하지는 않았다.
- `sourceDocument` 트리플의 근거는 SOP-003 문서 위치(표 행)로 했다. 규칙 자체의 근거는 nodes.csv 행이다.

## 5. 미확인
- 이전과 마찬가지로 PDF를 다시 열어 표 내용(SOP-003 행)을 확인하지는 않았다. 위치와 인용은 `tables.jsonl`을 믿는다. PDF 파일 해시만 재계산했다.
- `instances.ttl`이 환경이 달라도 바이트가 같은지는 미확인이다.
- Neo4j 적재 시 장부를 어떻게 쓰는지는 이번 범위가 아니다.

## 6. 한계
- 장부는 트리플 단위 근거일 뿐 Provenance 노드로 RDF화되지 않았다. hasSensor 같은 관계에는 여전히 RDF Provenance가 붙지 않는다(ontology의 hasProvenance domain에 관계가 없음).
- Document에는 title이 없다(위 1-4).
- `maintenance_rules.csv`에는 extractionMethod 열을 넣지 않았다(바이트 보존). TTL과 장부에만 있다.

## 7. 변경하지 못한 문서에 필요한 수정안 (제안)
- `ontology_v1/schema_tables.md` 4-5장: document 유래 Provenance의 rowIndex·colIndex가 1부터이고 헤더 행이 1이라는 규약을 명시한다. 같은 장에 MaintenanceRule이 seedCsv와 document 두 Provenance를 가진다는 예를 추가한다.
- 같은 문서 7장(변환 규칙): MaintenanceRule에 extractionMethod="seedCsv"를 넣는다는 줄과, 트리플 출처 장부(`triple_sources.jsonl`) 설명을 추가한다.
- `harness/checklist.md` ③: "모든 트리플에 장부 근거가 있다(ledgerComplete)"와 "PDF 해시 재계산 일치"를 점검 항목에 넣는 것을 제안한다.
- `work_log.md`: rowIndex 1-기반 결정, title 미추가 결정, 매핑표(0-기반)와의 불일치를 기록한다.
- `ontology_v1/ontology.ttl`: `im:rowIndex`/`im:colIndex` comment에 "1부터"를 적는 것을 제안한다.

커밋하지 않았다. verifier 검증이 필요하다.
