import pathlib,json,hashlib,collections
O=pathlib.Path(__file__).resolve().parent
def j(n):return json.loads((O/n).read_text(encoding='utf-8'))
def rs(n):return [json.loads(x) for x in (O/n).read_text(encoding='utf-8').splitlines()]
def sha(n):return hashlib.sha256((O/n).read_bytes()).hexdigest()
S=j('validation_summary.json');K=j('kg_repair.json');F=j('freeze.json');A=j('supplemental_checks.json');R=rs('predictions.validated.jsonl')
assert K['conforms'] and not A['failed']
assert not (O/'최종평가.md').exists()
def esc(x):return str(x if x is not None else '명시 없음').replace('|','\\|').replace('\n',' ')
def loc(e):
    if e['table_id']:return f"{e['document_id']} p{e['page']} · {e['table_id']} · 행 {e['row_index']}, 열 {e['col_index']} · bbox {e['bbox']}"
    return f"{e['document_id']} p{e['page']} · {e['chunk_id']} · 문자 [{e['char_start']}, {e['char_end']})"
appendix=['# 규칙별 KG 연결과 원문 근거','', 'AI가 원문을 검토한 기록이며 사람 승인 기록이 아닙니다. 전체 evidence 배열과 개별 SHA-256은 predictions.validated.jsonl 및 provenance.index.jsonl에 있습니다. 문자는 정규화 페이지 기준 0부터 시작하는 반열린 구간, 표 행·열은 헤더를 포함하여 1부터 시작합니다.','']
for r in R:
    appendix.extend([f"## {r['identifier']}",'',f"- 문서/분류: {r['document_id']} / {r['class']}",f"- 조건: {esc(r['condition'])}",f"- 조치/요구: {esc(r['action'])}",f"- 센서: {', '.join(r['sensors']) or '명시적 설치 연결 없음'}",f"- 설비/제품 문맥: {', '.join(r['equipment']) or '없음'}",f"- KG actionTarget: {', '.join(r['action_targets']) or '없음'}"])
    if r.get('clauses'):
        appendix.append('- 분기: '+ ' / '.join(f"{esc(x['condition'])} → {esc(x['action'])}" for x in r['clauses']))
    if r['evidence'][0]['table_id']:
        t=r['evidence'][0]['table_id'];rn=r['evidence'][0]['row_index'];ev=[e for e in r['evidence'] if e['table_id']==t and e['row_index']==rn]
    else:ev=[r['evidence'][0]]
    appendix.extend(['',*[f"> {esc(e['quote'])}\n\n위치: {loc(e)}  \n인용 SHA-256: `{e['text_sha256']}`\n" for e in ev]])
(O/'KG_근거.md').write_text('\n'.join(appendix)+'\n',encoding='utf-8')
table='\n'.join(f"| {d} | {v['pages']} | {v['chunks']} | {v['tables']} | {v['raw']} | {v['validated']} | {v['rejected']} |" for d,v in S['documents_detail'].items())
inputs='\n'.join(f'| {n} | `{h}` |' for n,h in F['inputs'].items())
artifacts='\n'.join(f'| {n} | `{F["artifacts"][n]}` |' for n in ['prompt.txt','extraction_policy.txt','output_schema.json','configuration.json','extract.py','predictions.raw.jsonl'])
report=f'''# iMAKS 제조 문서 추출 — 최종평가

작성 기준일: 2026-10-16, Asia/Seoul. 이 문서는 추출·검증 단계 보고서입니다. **점수: 고정 후 별도 평가 대기**.

## 1 결과 요약

요청 모델은 **GPT-6.1 Sol**, 실제 모델은 **미확인**입니다. 이 채팅에서 실제 실행 모델을 입증하는 신뢰할 수 있는 런타임 식별 정보를 확보하지 못했습니다. 요청 모델명으로 실제 사용 모델을 단정하지 않았습니다.

Codex 구독 대화에서 AI가 원문을 해석하고 로컬 Python 코드로 변환·검증했습니다. 별도 모델 API 호출 실험이 아닙니다. 자동 원본 예측 **{S['raw_rules']}건**, 원문·구조 검증 통과 **{S['validated_rules']}건**, 검증 제외 **{S['rejected_rules']}건**입니다. 이는 정확도나 재현율을 뜻하지 않습니다.

SOP 4개와 데이터시트 3개, 총 **{S['documents']}개 문서·{S['pages']}쪽·{S['chunks']}개 청크·{S['tables']}개 표**를 처리했습니다. 최종 KG 후보는 **{K['triples']:,}개 트리플**, SHACL 결과는 **Conforms: True, 위반 {K['validation_results']}건**입니다. 정답 접근·점수 계산은 실행하지 않았습니다.

## 2 데이터와 구현 범위

추출에 읽은 파일은 지정된 input 폴더의 chunks.jsonl, pages.jsonl, tables.jsonl, doc_manifest.csv, ontology.ttl, shapes.ttl 6개뿐입니다. 원본 PDF와 다른 실험 자료는 열지 않았습니다. PDF 경로와 해시는 manifest에 실린 주장으로 보존했으며, PDF 바이너리 해시를 재계산한 것은 아닙니다.

문서별 페이지·청크·표를 확인했습니다. SOP의 명시적 요구, 임계값·이상 정의, 정비·장애 해결 절차, 역할·구역 허용표·인원·확인 시간을 추출했습니다. 데이터시트에서는 명시적 운용·설정 권고를 추출하고 단순 사양표 전체를 규칙으로 바꾸지는 않았습니다. 설치 모델이 명시되지 않은 제품을 특정 공정 센서에 연결하지 않았습니다.

## 3 자동 추출 과정과 고정한 추출 정책

입력 구조를 확인한 뒤 extraction_policy.txt, output_schema.json, configuration.json, prompt.txt를 작성하고 전체 문서를 읽었습니다. AI의 문서 해석과 분기·문구 매핑은 extract.py에 기록했습니다. 이 코드가 자동 원본 predictions.raw.jsonl을 생성한 직후 freeze.json을 만들었고, 이후 검증·AI 검토본을 별도 파일로 저장했습니다.

분류 집계는 OperationalRule **{S['class_counts']['OperationalRule']}**, ThresholdRule **{S['class_counts']['ThresholdRule']}**, MaintenanceRule **{S['class_counts']['MaintenanceRule']}**, AccessRule **{S['class_counts']['AccessRule']}**입니다. 원문 식별자가 있는 복합 규칙은 한 건으로 유지하고 clauses에 조건별 조치 쌍을 보존했습니다. 무조건적 요구는 condition=null, 조치 없는 정의·진단은 action=null을 허용합니다. 영어 조건·조치, 수치·단위·시간을 유지했습니다.

표 임계값은 센서별 한 행으로 유지하며 경계의 등호 포함 여부를 만들지 않았습니다. nominal의 ± 표기는 condition에 남기고 수치 속성 nominal에는 중심값만 넣었습니다. CRITICAL Response는 critical 상태의 조치이며 모든 경고에 적용한다고 해석하지 않았습니다. SOP-002 p2 첫 HUM 행은 continued_from과 앞쪽 서버룸 제목을 함께 사용했습니다.

## 4 평가 계획(아직 미실행)

**모든 점수 항목: 고정 후 별도 평가 대기.** 이번 채팅은 정답·평가 파일에 접근하지 않았고 정밀도, 재현율, F1, 목표 규칙 수를 산출하거나 추정하지 않았습니다.

별도 평가 단계에서는 먼저 freeze SHA-256과 원본 예측 해시를 확인하고, 정답을 이 채팅 문맥에 넣지 않은 상태로 평가합니다. 원본과 AI 검토본은 별도로 평가해야 합니다. 식별자 매칭, 복합 규칙 분할 단위, 분류·조건·조치·센서·출처의 비교 기준과 문서별 누락 판정은 채점 전에 별도로 고정해야 합니다.

## 5 문서별 추출·검증 집계

| 문서 | 쪽 | 청크 | 표 | 원본 | 검증 통과 | 제외 |
|---|---:|---:|---:|---:|---:|---:|
{table}
| 합계 | {S['pages']} | {S['chunks']} | {S['tables']} | {S['raw_rules']} | {S['validated_rules']} | {S['rejected_rules']} |

SOP-002는 센서 임계값 행과 이상 정의를 포함합니다. SOP-003은 번호 있는 정비 규칙과 별도 장애 해결 절차를 포함합니다. SOP-004의 행 단위 복합 규칙은 여러 역할·구역 셀을 한 건에 보존합니다. 집계는 이 정책의 출력 단위이며 정답의 규칙 수와 같다는 뜻이 아닙니다. reading_coverage.json에 모든 문서·쪽·청크·표 목록이 있습니다.

## 6 보조 검사

입력 6개·고정 산출물 해시, 원문 인용 {S['evidence_occurrences']}개 출현, 문서·쪽·청크·표 셀·bbox 좌표, 중복 식별자, 분류와 센서/설비 참조를 검사했습니다. 필드 매핑·이어지는 표·문서 포함·복합 분기 보조 검사 **{A['passed']}건 통과, {A['failed']}건 실패**입니다. 원문에 번호가 있는 규칙 28개의 누락은 없었습니다. 이것은 번호 없는 모든 의미 단위의 재현율 검사가 아닙니다.

입력 무결성 세부 검사 {S['input_checks_passed']}건 통과, **24개 표 청크의 페이지 평탄 텍스트 직접 일치 검사 불일치**를 기록했습니다. 정규화 표 청크와 페이지의 레이아웃 표현이 다릅니다. 표 근거는 페이지 문자 위치 대신 실제 tables.jsonl의 셀 문자열·행·열·bbox로 검증했습니다. 이 불일치를 숨기거나 PDF 렌더 검증 완료로 바꾸지 않았습니다. 비표 청크와 입력 청크 자체 SHA-256 검사는 통과했습니다.

미실행: 원본 PDF 렌더 대조, manifest의 PDF 바이너리 해시 재계산, 실제 설비 설치 확인, 사람 승인, 정답 기반 누락·정확도 검사, 시계열 인과 검증. API usage·요청 ID·서버 응답·과금액·모델 추론 시간을 생성하지 않았습니다.

## 7 KG와 원문 기반 검토

최종 사용 후보는 **kg.candidate.v2.ttl**입니다. 규칙 {S['validated_rules']}개, Document 7개, Station {S['stations']}개, Sensor {S['sensors']}개, Provenance {S['provenance_nodes']}개를 포함합니다. 출처는 중복 인용도 각 연결에서 보존했습니다. ontology.ttl을 ont_graph로 제공하고 inference="none"으로 SHACL을 실행했습니다.

첫 후보 kg.candidate.ttl은 SHACL 위반 1,121건이었습니다. stationType·sensorType·sourceKind에 명시적 xsd:string을 쓴 값이 제공된 sh:in의 단순 문자열과 RDF 항등 비교에서 달랐습니다. 해당 문자열 표기 {sum(K['changes'].values())}개만 단순 문자열로 다시 직렬화해 **두 번째 파일에서 위반 0건**을 확인했습니다. 원본 예측·입력·온톨로지·제약은 수정하지 않았고 첫 후보와 실패 보고서도 보존했습니다. kg_repair.json에 변경 이유와 수가 있습니다.

ai_review.jsonl은 **원문 기반 AI 검토**이며 사람 승인 기록이 아닙니다. 원본 예측 변경은 없습니다. review_issues.json에는 화학물 보관소의 허용 역할 범위, 데이터시트 200°C 연속 정격과 SOP의 210°C 임계값, 데이터시트 14 A 권고와 SOP의 15 A 임계값 등 확인 후보를 기록했습니다. 실제 설치 모델이 불명확하므로 장비 위반으로 확정하지 않았습니다.

## 8 재현성과 한계

freeze.json SHA-256:

`{sha('freeze.json')}`

입력 SHA-256:

| 파일 | SHA-256 |
|---|---|
{inputs}

고정한 지시·설정·원본 예측 SHA-256:

| 파일 | SHA-256 |
|---|---|
{artifacts}

prompt.txt는 작업용 추출 지시 기록입니다. 시스템·개발자 지침과 전체 대화의 완전한 로그가 아니며, 해석표는 extract.py에 함께 고정했습니다. 실제 모델·샘플링 설정·서버 내부 추론은 확인할 수 없습니다. 재실행은 고정 해석표의 코드 변환을 재현하며, 모델의 새 추론 결과가 동일함을 보장하지 않습니다.

이 프로젝트에는 과거 정답 노출 이력이 있다는 사실을 인계받았습니다. 이 새 채팅은 지정 입력으로 분리했지만 **프로젝트 전체의 독립 비공개 시험으로 주장하지 않습니다**. 허용된 ontology.ttl·shapes.ttl에는 설계 이력·집계·평가 분류 정렬에 관한 주석이 있습니다. 이를 스키마 문맥 노출로 기록하며 추출 목표 수로 사용하지 않았습니다. 자동 제공된 시스템·개발자·환경 지침과 위임 요청은 보았고, 별도 상위 README/CLAUDE/work_log/AGENTS 파일은 읽지 않았습니다.

API 키 열람, 유료 모델 API 호출, 별도 API 결제, 모델 자동 전환을 하지 않았습니다. 검증 라이브러리 설치를 위한 공개 패키지 다운로드는 모델 API 실험과 구별됩니다. 로컬 Python·라이브러리 버전은 validation_summary.json에 있습니다.

## 9 기준 준수 상태

| 기준 | 상태 |
|---|---|
| 지정 입력만 사용·입력 불변 | 완료: 입력 6개 해시 재확인 |
| 정책·스키마 선고정 | 완료 |
| SOP·데이터시트 전 문서 처리 | 완료: 7개 문서 10쪽 |
| 원본과 필터·AI 검토 분리 및 freeze | 완료 |
| 원문 언어·좌표·해시·센서/설비 참조 | 완료: 제공된 정규화 표현 기준 |
| 온톨로지 밖 연결 별도 보존 | 완료: relations.deferred.jsonl |
| KG·SHACL | 완료: v2 후보 통과, v1 실패 보존 |
| 사람 승인·원본 PDF 대조 | 미실행 |
| 정답 접근·점수 계산 | 미실행: 고정 후 별도 평가 대기 |
| API 사용·Git 업로드/커밋/브랜치 변경/병합 | 하지 않음 |

## 10 KG 연결 내용과 근거

KG에는 Station → hasSensor → Sensor, Rule → appliesToSensor → Sensor, Rule → actionTarget → Station, Rule → sourceDocument → Document, 각 노드 → hasProvenance → Provenance와 원문 공정 순서 feedsInto를 넣었습니다. 스키마 밖 속성·관계는 KG에 넣지 않았습니다.

예를 들어 RULE-ST02-02는 ST02_SEALING_TMP에 적용되고 ST02·ST03·ST04를 조치 대상으로 가리킵니다. 원문은 “TMP > 210°C (CRITICAL) — emergency stop ST02, ST03, ST04.”이며 SOP-001 p1 해당 규칙 청크가 근거입니다. MAINT-01은 SOP-003 p1 표1의 VIB 정비 행에 근거해 ST04_PACKAGING_VIB에 연결합니다. SOP-002 p2 첫 HUM 행은 앞쪽 서버룸 표와의 명시적 연속 정보로 SRV01_SERVERROOM_HUM에 연결합니다.

ST01 → ST02 → ST03 → ST04는 공정 순서로만 넣었습니다. ST02 전류와 ST04 속도의 상관 서술은 스키마가 정한 후속 단계 적재 제한 때문에 보류했습니다. 인과 후보도 필수 likelihoodScore가 없어 보류했습니다. 점수·시차를 만들거나 이상 정의를 실제 AnomalyEvent로 생성하지 않았습니다. Role/Zone·OccupancyEvent 관련 스키마 밖 연결도 별도 후보로 남겼습니다.

규칙별 전체 조건·조치·센서·설비·인용과 위치는 [KG_근거.md](KG_근거.md), 기계 판독용 연결은 kg.rule_links.jsonl, 출처별 문서/청크 좌표는 provenance.index.jsonl, 공정·센서 소속 연결 근거는 relations.raw.jsonl에 있습니다. Provenance의 문서 ID·chunk ID는 이 색인에서 보완합니다. 복합 분기는 JSONL clauses와 원문을 함께 읽어야 합니다.

## 11 산출물 경로와 재현 방법

출력 폴더: `{O.as_posix()}`

| 산출물 | 용도 |
|---|---|
| predictions.raw.jsonl / freeze.json / freeze.sha256 | 원본 예측·고정 기록 |
| predictions.validated.jsonl / validation.decisions.jsonl | 검증 통과본·판정 |
| ai_review.jsonl / review_issues.json | 별도 AI 검토·확인 후보 |
| kg.candidate.v2.ttl / shacl.v2.report.txt / shacl.v2.report.ttl | 최종 KG·SHACL 결과 |
| kg.candidate.ttl / shacl.report.txt / kg_repair.json | 첫 실패본·변환 이력 |
| KG_근거.md / kg.rule_links.jsonl / provenance.index.jsonl | 규칙별 연결·원문 근거 |
| reading_coverage.json / supplemental_checks.json / input_integrity_checks.json | 범위·보조·입력 검사 |
| artifact_manifest.json / artifact_manifest.sha256 | 후속 검증·보고서 파일 해시 |

이 폴더에서 기존 설치 Python으로 `reproduce.py`를 실행하면 입력과 고정 파일 해시를 검사합니다. `reproduce.py --output replay_01 --extract-only`는 존재하지 않는 새 형제 폴더에 결정적 추출을 재생하고 freeze 해시 동일성을 검사합니다. `--extract-only`를 빼면 검증·SHACL·보고서도 재생합니다. 기존 폴더 덮어쓰기는 허용하지 않습니다. Python 경로와 상세 명령은 [재현방법.md](재현방법.md)에 있습니다.

## 12 완료 범위와 남은 평가

추출, 원본 freeze, 원문·위치·해시 검증, 별도 AI 검토, KG 후보와 SHACL 검증, 한국어 Markdown 보고서를 완료했습니다. 남은 작업은 별도 단계의 정답 평가와 필요 시 사람의 원문·설치정보 검토입니다. **점수는 고정 후 별도 평가 대기**입니다.
'''
(O/'최종평가.md').write_text(report,encoding='utf-8')
python=pathlib.Path(__import__('sys').executable).as_posix()
(O/'재현방법.md').write_text(f'''# 재현 방법

PowerShell에서 다음 명령을 실행합니다. 기존 입력과 원본 예측을 바꾸지 않습니다.

```powershell
Set-Location -LiteralPath '{O.as_posix()}'
& '{python}' reproduce.py
& '{python}' reproduce.py --output replay_01 --extract-only
```

전체 검증·KG·보고서를 재생하려면 새 이름으로 `--output replay_full_01`을 사용하고 `--extract-only`를 생략합니다. 설치해 둔 vendor 라이브러리를 새 폴더에 복사하며 네트워크·모델 API 호출은 하지 않습니다. 실행 시 이미 존재하는 출력 폴더를 사용하면 중단합니다.

순서: extract.py → 원본 freeze → validate_build.py → supplemental_checks.py → repair_kg_literals.py → build_report.py. 첫 KG의 문자열 제약 실패와 두 번째 후보의 통과를 모두 재현합니다. validate_build.py 이후 검토는 원문 기반 AI 해석을 코드에 기록한 것으로, 사람이 승인한 결과가 아닙니다.

검증 의존성: rdflib=={S['versions']['rdflib']}, pyshacl=={S['versions']['pyshacl']}, jsonschema=={S['versions']['jsonschema']}. vendor에 이 버전과 종속 패키지를 설치했습니다. Python은 {__import__('sys').version.split()[0]}입니다. 새 모델 추론, 비용 측정, 정답 점수 계산을 재현하는 명령은 포함하지 않습니다.

원본 추출의 freeze JSON은 결정적 재생 시 동일성을 검사합니다. Turtle 직렬화와 SHACL blank node 식별자는 라이브러리 처리 순서에 따라 파일 바이트가 달라질 수 있어 의미·검증 결과를 비교해야 합니다. 각 실행의 최종 산출물 바이트 해시는 artifact_manifest.json에 보존합니다.
''',encoding='utf-8')
manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(O.iterdir()) if p.is_file() and p.name not in ['artifact_manifest.json','artifact_manifest.sha256']}
(O/'artifact_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(O/'artifact_manifest.sha256').write_text(sha('artifact_manifest.json')+'  artifact_manifest.json\n',encoding='ascii')
print(json.dumps({'report':str(O/'최종평가.md'),'freeze_sha256':sha('freeze.json'),'artifact_manifest_sha256':sha('artifact_manifest.json'),'final_shacl_conforms':K['conforms']},ensure_ascii=False))
