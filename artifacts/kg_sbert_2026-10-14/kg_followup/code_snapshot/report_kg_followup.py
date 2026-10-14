from pathlib import Path
import json, shutil, hashlib
out=Path('outputs/kg_followup_v1'); repo=Path('work/github-repo')
k=json.loads((out/'kg_final/summary.json').read_text(encoding='utf-8'))
m=json.loads((out/'evaluation/metrics.json').read_text(encoding='utf-8'))
n=json.loads((out/'evaluation/numeric_diagnostic.json').read_text(encoding='utf-8'))
rows=[]
for d,v in m['by_document'].items():
    score=f"{v['f1']:.4f}" if v['gold'] else '평가 정답 없음'
    rows.append(f"| {d} | {v['predictions']} | {v['gold']} | {v['matched']} | {score} |")
report='''# KG 변환 및 고정 추출 결과의 첫 진단 대조

완료일: 2026-10-14. 브랜치: `2nd-yewon`.

## 완료 범위

API 호출 없이 기존 seed 구조와 이전 대화에서 고정한 172개 예측을 RDF KG로 변환했다. Rule·Document·Provenance 노드를 생성하고 SHACL(inference=none)을 통과했다. 원본 규칙 정답 86건은 평가 모듈에서만 읽었다. API 추출 테스트와 SBERT F1_content, Neo4j 서버 적재는 수행하지 않았다.

| 항목 | 결과 |
|---|---:|
| Station | 9 |
| Sensor | 22 |
| Rule | 172 |
| Document | 7 |
| Provenance | 274 |
| 서로 다른 노드 | 484 |
| RDF 트리플 | 4,697 |
| hasSensor | 22 |
| feedsInto | 3 |
| appliesToSensor | 86 |
| actionTarget | 105 |

Rule 172는 하위 클래스 172건과 같은 노드 집합이다. 상위/하위 클래스를 더해서 중복 집계하지 않는다. 모든 4,697개 트리플에 파일·행 또는 문서 단위·해시를 담은 출처 ledger가 있다. 정비 seed 8개는 예측 MAINT-01~08과 클래스·센서·우선순위가 모두 대응한다. 원본 정비 관계 16줄을 8개의 appliesToSensor 관계로 합치고 두 원본 행의 출처를 보존했다. seed 조치 문장이 추출 조치를 덮어쓰지는 않는다.

## 정답 86건 대조

**아래 수치는 F1_lexical_proxy이며, 프로젝트 주지표 SBERT F1_content가 아니다. 의미 정확도 또는 사람이 승인한 정답률로 해석하면 안 된다.**

- 입력: 고정 예측 172건, ZIP 내부 `kg_seed/ground_truth.csv` 원본 86건.
- 방법: condition+action의 소문자 유니코드 단어/숫자 다중집합 Dice 유사도, 문서별 Hungarian 일대일 할당 후 0.6 이상 연결. ID·인용문·클래스는 유사도 입력에 넣지 않았다.
- 연결 60건, 미연결 정답 26건, 미연결 예측 112건.
- 진단 Precision **0.3488**, Recall **0.6977**, F1_lexical_proxy **0.4651**.
- 정답 ID와 완전히 같은 예측 ID는 30건, 분할 전 원문 ID 계보로 연결되는 정답은 31건. ID 일치 자체는 내용 정답 판정이 아니다.

| 문서 | 예측 | 정답 | 텍스트 연결 | 진단 F1 |
|---|---:|---:|---:|---:|
'''+ '\n'.join(rows)+'''

데이터시트 3개에는 이 정답 CSV의 대응 행이 없다. 전체 172건을 분모로 쓰는 수치는 이 11개 규칙도 미연결로 세므로 해당 규칙이 잘못됐다는 뜻이 아니다. SOP-004는 역할/구역과 심각도별로 원자화하여 71건, 정답은 19건이므로 일대일 비교의 분할 불일치도 크다. 부등호와 부정을 구별하지 못하는 토큰 지표의 한계를 테스트에 명시했다. 기존 예측을 정답에 맞춰 합치거나 고치지 않았다.

## 수치와 원문 차이에 대한 보충 진단

이 검사는 텍스트 대조 이후 별도로 추가한 진단이며 사전 고정된 주지표가 아니다. SOP-002의 같은 센서에 해당하는 경고/위험 상하한 88개 중 **84개 일치**, 센서 22개 중 **20개는 네 값 모두 일치**했다.

불일치 4개는 ST03_LABELLING_SPD의 critLo/warnLo/warnHi 및 ST04_PACKAGING_SPD의 critLo다. 예측 값은 제공된 원문 표와 일치한다. 원본 정답 CSV의 값이 다른 것이므로 추출 결과를 정답 수치로 수정하지 않았다. 상세 전후 값과 정확한 sourceQuote는 로컬 `evaluation/numeric_diagnostic.json`에 있다.

원본 정답의 일부 조치는 원문 규칙보다 추가적인 내용을 담는다. 예를 들어 운전 범위 유지 문장과 정답의 검사/정비 통보 조치가 다를 수 있다. 원문 근거 없는 조치를 추출 결과에 추가하지 않았다. 이 차이도 의미 평가의 별도 검토 대상이다.

## 검증과 한계

- 새 단위 테스트 10개 통과. Hungarian 구현은 작은 행렬의 완전 탐색 결과와 대조했다.
- 최종 RDF SHACL 통과 및 직렬화 후 재읽기 성공.
- 최종 구조·출처·정비 매핑·추출 불변성 검사 10개 통과.
- 기존 고정 산출물 56개와 predictions.jsonl의 해시가 모두 유지됐다.
- SBERT 라이브러리와 all-MiniLM-L6-v2 로컬 모델이 없고 새 설치/다운로드를 하지 않았으므로 **F1_content는 null(미실행)**이다.
- 사람 검토 미수행. 현재 대화 추출 결과를 사용했으며 OpenAI API로 생성한 결과가 아니다.
- Neo4j 가져오기용 Cypher 파일을 생성했지만 서버에 연결하거나 실행하지 않았다. 서버 적재/쿼리 검증 완료로 표시하지 않는다.
- `kg/`는 정비 seed 출처 보완 전의 첫 빌드이고 **최종본은 `kg_final/`**이다. 보완 전 빌드도 감사용으로 보존했다.

## 로컬 산출물

`kg_final/graph.ttl`, `kg_final/triple_lineage.jsonl`, `kg_final/neo4j_import.cypher`, `kg_final/shacl_report.txt`, `kg_final/maintenance_mapping.json`, `evaluation/metrics.json`, `evaluation/assignments.json`, 미연결 목록, `evaluation/numeric_diagnostic.json`, `verification.json`, `pre_evaluation_lock.json`, `evaluation_policy.md`, `contamination_log.json`, `manifest.json`.

Git에는 재현 코드·테스트·집계 보고서·평가 정책을 올린다. 원문, 정답 CSV, 개별 정답/예측 대조표, RDF 실데이터는 올리지 않는다.

## 다음 단계

1. 허용된 로컬 SBERT 환경을 준비한 뒤 사전 정의한 F1_content를 계산한다. 이번 진단 점수와 이름/결과를 분리한다.
2. 원자화 단위와 원문-정답 수치 차이에 대한 사람 검토를 기록한다. 기존 고정 추출은 유지하고 개선 실험은 새 버전으로 진행한다.
3. Neo4j 접속 환경에서 생성된 Cypher를 검토·적재하고 출처 및 Rule 검색 질의를 확인한다.
4. API 크레딧이 준비되면 별도의 API 추출 실험을 실행한다.
'''
(out/'completion_report_ko.md').write_text(report,encoding='utf-8')
(repo/'reports/kg_followup_2026-10-14.md').write_text(report.replace('## 로컬 산출물','## 로컬 산출물 (이 저장소에는 실데이터 미포함)'),encoding='utf-8')
shutil.copyfile(out/'evaluation_policy.md',repo/'docs/offline_evaluation_policy.md')
cont={'phase':'post_extraction_authorized_evaluation','authorized_by':'사용자의 API 없이 가능한 KG 적재 및 정답 대조 후속 작업 요청','predictions_modified_after_ground_truth':False,'gold_source':'iMAKS_dataset.zip::kg_seed/ground_truth.csv','gold_sha256':m['hashes']['ground_truth_original'],'predictions_sha256':m['hashes']['predictions'],'exposure':['프로젝트 CLAUDE.md의 평가 프로토콜 및 기대 구조','원본 규칙 ground_truth.csv 86건 (평가 단계)','seed nodes.csv/edges.csv의 레이블과 구조. 이벤트/사람 행은 그래프에서 제외','work_log.md의 과거 설계 근거 일부 (이번 후속 구현 기록을 위해 열람)'],'not_used':['이전 평가 점수/벤치마크 결과','수정된 ground truth CSV','API 호출','새 모델 다운로드'],'future_note':'이후 수행하는 추출은 평가 정답 노출 이후의 새 실험임을 밝혀야 한다.'}
(out/'contamination_log.json').write_text(json.dumps(cont,ensure_ascii=False,indent=2),encoding='utf-8')
(out/'code_snapshot').mkdir(exist_ok=True)
for rel in ['src/imaks_kg/kg/build.py','src/imaks_kg/evaluation/offline.py','src/imaks_kg/evaluation/numeric.py','tests/test_kg_followup.py']:
    shutil.copyfile(repo/rel,out/'code_snapshot'/Path(rel).name)
shutil.copyfile(Path('work/verify_kg_final.py'),out/'code_snapshot/verify_kg_final.py')
text=(repo/'CLAUDE.md').read_text(encoding='utf-8')
marker='일정 기준:'
note='실행 상태(2026-10-14, `2nd-yewon`): ③ 및 Rule·Document 승격은 로컬 RDF 생성/SHACL 검증 완료. ④는 새 대화에서 직접 추출한 고정 172건을 사용하며 API 실험·사람 검토는 미실행. ⑤는 원본 86건의 ID/텍스트 진단 대조를 수행했으나, SBERT F1_content는 로컬 모델 부재로 미실행이다. Neo4j 서버에는 아직 적재하지 않았다. 상세: `reports/kg_followup_2026-10-14.md`.\n\n'
assert marker in text
(repo/'CLAUDE.md').write_text(text.replace(marker,note+marker,1),encoding='utf-8')
with (repo/'work_log.md').open('a',encoding='utf-8') as f:
    f.write('\n\n## 2026-10-14 — API 없이 가능한 KG 승격 및 첫 진단 대조\n\n고정 추출 172건을 변경하지 않고 seed 구조를 RDF로 변환했다. Station 9, Sensor 22, Rule 172, Document 7, Provenance 274; SHACL 통과. MAINT 8개 원본 ID와 관계 16행 출처를 보존했다. 규칙 정답 CSV는 평가 모듈에서만 읽고 KG 구축에는 사용하지 않았다.\n\nSBERT/로컬 모델이 없어 주지표 F1_content는 계산하지 않았다. 사전 고정한 별도 F1_lexical_proxy는 0.4651(60/86 정답 연결, 예측 172건); 의미 정확도 점수로 부르지 않는다. 수치 보충 진단은 88값 중84 일치이며 4개는 원문-정답 속도 한계값 차이다. 원본 예측과 원문을 수정하지 않았다. 새 테스트 10개/실산출물 검증 10개 통과. Neo4j 서버 적재·API 실험·사람 검토는 남았다. 상세 재현 및 한계는 docs/kg_followup.md와 reports/kg_followup_2026-10-14.md. 원문/정답/실데이터는 Git에 넣지 않는다.\n')
with (repo/'llm_extraction_design/STATUS.md').open('a',encoding='utf-8') as f:
    f.write('\n\n## 2026-10-14 후속 작업\n\nAPI 실험 보류는 유지한다. 별도 `imaks_kg.kg.build` 모듈로 기존 대화의 고정 추출을 Rule·Document RDF로 승격하고 SHACL 검증했다. `imaks_kg.evaluation.offline`로 정답 86건에 대한 진단 대조를 수행했다. 이는 API 응답 검증기나 SBERT F1_content 완성을 의미하지 않는다. [후속 보고서](../reports/kg_followup_2026-10-14.md) 참조.\n')
print('reports and audit written')
