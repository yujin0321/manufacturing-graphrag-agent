# ③ 기존 KG 변환 v2 검증 보고서
- 판정: PASS
- 실행 환경: .venv/Scripts/python.exe (시스템 python에는 pyshacl이 없어 run_shacl은 .venv로 실행)

## 항목별 결과
| 항목 | 결과 | 근거 |
| --- | --- | --- |
| 공통: check_raw_unchanged | PASS | PASS, 1121개 일치. 변환 재실행 후에도 rc=0 |
| 공통: check_leakage (기본 폴더) | PASS | 검사 파일 46, 폴더 8, 컬럼 목록 11. 금지 컬럼 없음 |
| 공통: 절대 경로 | PASS | src·tests에서 `C:\`, `/Users/`, `/home/` grep 결과 0건 |
| 공통: git 추적 | PASS | `.gitignore:228 /kg_build/`로 kg_build 전체 무시. src·tests는 무시 규칙 없음(check-ignore rc=1), `git ls-files src`에 나옴. imaks_data·preprocessed는 ls-files에 없음 |
| 공통: 이상값 삭제·보간 | PASS | convert_seed.py에 interpolat·rolling·smooth·fillna·dropna 없음. 센서 값은 다루지 않음 |
| 공통: API 키 | PASS | check_secrets: 검사 87, 건너뜀 0, 발견 0 |
| 공통: 보고서 형식·단위테스트 | PASS | `Ran 77 tests ... OK` |
| ③ 노드·엣지 수 | PASS | nodes 115, edges 341을 csv로 직접 셈. 변환 결과는 Station 9, Sensor 22, hasSensor 22, feedsInto 3, MaintenanceRule 8, Document 7, appliesToSensor 8, Provenance 47(seedCsv 39+document 8), 트리플 585가 TTL에서 독립 집계와 일치. 센서마다 스테이션 1개(22/22). Person·Zone 등 제외 사유는 summary.json의 seedNodeLabelCounts·seedEdgeTypeCounts로 대조 가능 |
| ③ SHACL | PASS | run_shacl.py --data kg_build/instances/instances.ttl 실행: Conforms: True. 문서 Provenance 8개도 같은 그래프에 있어 S7 포함 적합 |
| ③ 원본 ID 역추적 | PASS | 노드 유래 472건의 rowId가 해당 주체의 sourceNodeId와 일치, nodes.csv 해시 일치. 불일치 0 |
| ③ 적재 제외 대상 | PASS | TTL의 클래스·술어에 AnomalyEvent·5유형·Person·SafetyEvent·Zone(클래스)·System·CausalLink·triggers·correlatesWith·causallyAffects·authorized 없음. CSV 헤더·값에도 해당 파일 없음(zone은 Station 속성으로만 존재) |
| ③ 값 임의 통일 금지, 이중 기록 | PASS | MAINT-01 responseText "Inspect and lubricate main bearing"(시드)는 그대로 두고 문서 쪽 "...bearing"은 매핑표 sop003ActionRaw/Normalized, actionExactMatch=false로 병기 |
| ③ 노드·엣지 출처 | PASS | triple_sources.jsonl이 위치. rdflib로 읽은 585 트리플 ↔ 장부 585: 누락 0, 초과 0, 중복 0. edges 유래 엣지는 장부의 file/line/sha256로 추적 |
| ③ 재실행 동일성 | PASS | kg_build를 백업 후 `PYTHONPATH=src python -m imaks_kg.kg.convert_seed` 재실행. `diff -rq` 결과 전 파일 바이트 동일(TTL·장부·summary·매핑표 포함) |
| 특이점2: 장부 전수 | PASS | hasSensor 22건 모두 edges.csv의 monitors 양방향 두 줄(예: L11;L12)을 보존하고 행 번호가 edges.csv 행 위치와 일치. appliesToSensor 8건 모두 triggers 줄과 resolves 줄 두 개 보존. feedsInto 3건은 feeds_into 줄과 일치. 엣지 sha256은 edges.csv 해시와 일치 |
| 특이점3: 문서 Provenance 8개 | PASS | sourceKind=document, page=1, tableId=SOP-003:p1:table1, rowIndex 2~9, colIndex=1, sourceQuote, textSha256 모두 존재. sha256(sourceQuote)==textSha256 8/8, quote는 tables.jsonl rows_normalized 행을 " \| "로 이은 것과 일치, rows_normalized[rowIndex-1][colIndex-1]이 해당 MAINT ID 8/8(헤더행 Rule ID=1). 규칙당 hasProvenance 2개(seedCsv+document), extractionMethod="seedCsv" 8/8. TTL 값과 provenance_document.csv 일치 |
| 특이점6: PDF 해시 | PASS | 7개 PDF를 직접 SHA-256 계산해 TTL의 sourceSha256 및 documents.csv와 7/7 일치. 장부의 PDF·doc_manifest 근거 해시도 일치 |
| 특이점9: 금지 경로 | PASS | ontology_v1/ 변경 없음(git status 빈 출력). CLAUDE.md, harness/checklist.md, work_log.md는 허용된 수정 상태. 추가로 .claude/agents/verifier.md, .claude/skills/stage-check/SKILL.md 수정과 .claude/skills/stage-check/scripts/ 새 파일 2개가 있음. 이번 변환 코드와 별개의 점검 스크립트 작업으로 보이며 판정 외 관찰에 적음 |

## 불합격 사유
없음.

## 미확인 항목
없음. 실제 PDF 본문에서 표 셀 내용을 다시 추출해 대조하지는 않았고, preprocessed/documents/tables.jsonl을 기준으로 삼았다(전처리 단계 검증 범위).

## 판정 외 관찰
- 매핑표 `kg_build/mapping/maint_seed_vs_sop003.csv`의 sop003RowIndex는 0부터(MAINT-01=1... MAINT-08=8, 헤더=0)이고 Provenance rowIndex는 1부터(MAINT-01=2... MAINT-08=9). 8행 모두 정확히 1씩 어긋난다. 컬럼 이름이나 설명으로 기준을 구분하지 않으면 혼동 위험이 있다(수정하지 않음).
- .claude/ 아래 수정은 이번 ③ 구현 산출물 범위 밖이다. 사용자 승인 여부는 이 검증에서 알 수 없다.
- 시스템 python에는 pyshacl·rdflib가 없어 스킬 명령을 그대로 실행하면 실패한다. .venv가 필요하다.
- 임시 검증 스크립트는 scratchpad에만 두었다.
