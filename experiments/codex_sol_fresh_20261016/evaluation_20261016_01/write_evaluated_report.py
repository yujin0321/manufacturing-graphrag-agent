import pathlib,json,hashlib,csv,re
O=pathlib.Path(__file__).resolve().parent;R=O.parent/'run_20261016_01'
def j(p):return json.loads(p.read_text(encoding='utf-8'))
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
E=j(O/'evaluation_results.json');L=j(O/'pre_evaluation_lock.json');V=j(R/'validation_summary.json');K=j(R/'kg_repair.json')
M=E['scores']['plain']['0.6'];C=M['class_matched']
def pct(v):return f'{v*100:.2f}%'
docs='\n'.join(f"| {d} | {v['predictions']} | {v['gold']} | {v['TP']} | {v['FP']} | {v['FN']} | {pct(v['precision'])} | {pct(v['recall'])} | {pct(v['F1_content'])} | {v['granularity_ratio']:.3f} | {pct(v['theoretical_F1_upper_bound'])} |" for d,v in M['per_document'].items())
sens='\n'.join(f"| {s} | {t} | {v['TP']} | {v['FP']} | {v['FN']} | {pct(v['precision'])} | {pct(v['recall'])} | {pct(v['F1_content'])} |" for s,run in E['scores'].items() for t,v in run.items())
confusion='\n'.join(f"| {v['gold_class']} | {v['prediction_class']} | {v['count']} |" for v in M['class_confusion'])
sensor=M['sensor_set_exact_match'];sensor_text=(f"매칭된 {sensor['matched_pairs']}쌍 중 센서 집합이 같은 쌍은 {sensor['equal']}쌍, 일치 비율은 {pct(sensor['ratio'])}입니다. 정답 필드는 {sensor['gold_field']}이며 전체 필드 정확도를 뜻하지 않습니다." if sensor.get('ratio') is not None else '센서 집합 일치 비율은 N/A입니다. 정답에 지원되는 센서 열이 없어 임의로 텍스트에서 추정하지 않았습니다.')
defs='\n'.join(f"| {n} | `{m['sha256']}` |" for n,m in L['definition_files'].items())
versions=', '.join(f"{n} {v}" for n,v in E['versions'].items())
report=f'''# iMAKS 제조 문서 추출 — 최종평가

**모델(요청 설정): GPT-6.1 Sol**  
평가 기준일: 2026-10-16 (Asia/Seoul).

## 1 결과 요약

첨부한 두 평가 정의서에 따라 고정 원본 예측을 채점했습니다. **F1_content는 {pct(M['F1_content'])}**입니다. 평가 대상은 SOP 예측 {E['sop_predictions']}건과 정답 {E['gold_rows']}건입니다. 데이터시트 예측 {E['out_of_scope_datasheet_predictions']}건은 범위 밖으로 분리했습니다.

| 지표 | 결과 |
|---|---:|
| TP / FP / FN | {M['TP']} / {M['FP']} / {M['FN']} |
| Precision | {pct(M['precision'])} |
| Recall / Coverage | {pct(M['recall'])} |
| F1_content (주 지표, 임계값 0.6) | **{pct(M['F1_content'])}** |
| 처리 문서 범위 F1_content | {pct(M['processed_scope']['F1_content'])} |
| 분류까지 일치 F1 | {pct(C['F1'])} |
| 현재 예측·정답 건수의 이론적 F1 상한 | {pct(M['theoretical_F1_upper_bound'])} |

이 점수는 의미 유사도 기반 개발 평가입니다. 수치·단위·부등호·인과의 정확도와 같지 않습니다. 원문 검증 {V['validated_rules']}건과 최종 KG SHACL 위반 {K['validation_results']}건이라는 결과는 별도 검사입니다.

## 2 데이터와 구현 범위

원본 추출 범위는 SOP 4개와 데이터시트 3개, {V['pages']}쪽·{V['chunks']}개 청크·{V['tables']}개 표입니다. 원본 예측은 총 {E['predictions_total']}건이며 수정하지 않았습니다. 이번 평가는 predictions.validated.jsonl이나 AI 검토본 대신 **predictions.raw.jsonl**을 기준선으로 사용했습니다.

정답은 정의서가 지정한 원본 ground_truth.csv입니다. 평가 코드가 source 열을 manifest의 문서 ID·원본 경로·PDF 파일명에 대응시켜 검사했습니다. 알 수 없는 문서를 추정하는 방식은 사용하지 않았습니다. 정답의 문서별 분포는 아래 집계에서 확인했습니다. 첨부 문서의 다른 사람 점수나 예시 문장을 평가 결과로 사용하지 않았습니다.

## 3 자동 추출 과정과 고정한 추출 정책

추출 당시 고정한 정책·스키마·설정과 원본 예측은 초기 run_20261016_01 폴더에 그대로 보존했습니다. 영어 조건·조치, 원문 식별자, 센서·설비 연결과 근거 좌표를 유지하고, 복합 규칙은 한 식별자에 clauses로 분기를 기록했습니다. 이번 평가에서는 분할 예측을 임의로 합치지 않았습니다.

평가 규칙은 evaluation_policy.json에 기록한 뒤 pre_evaluation_lock.json으로 고정했습니다. 여기에는 원본 예측·두 정의서·프롬프트·스키마·설정·평가 코드 해시, 임베딩 revision과 라이브러리 버전이 있습니다. 정답을 읽은 뒤 예측 문장·분류·건수를 바꾸지 않았습니다.

## 4 평가 방법과 실행

유사도 문장은 `(condition 또는 빈 문자열) + 공백 + (action 또는 빈 문자열)`입니다. ID·인용·분류는 넣지 않았습니다. sentence-transformers/all-MiniLM-L6-v2, revision `{E['embedding_model']['revision']}`을 로컬 CPU에서 실행해 임베딩을 정규화하고 코사인 유사도를 계산했습니다.

동일 문서 안에서만 Hungarian 일대일 할당을 수행했습니다. 코사인 ≥0.6인 유효 쌍 수를 먼저 최대화하고, 동률이면 유효 쌍의 유사도 합을 최대화했습니다. 무효 쌍은 목적함수에서 0입니다. 클래스는 매칭 제한에 사용하지 않았습니다. 유효 쌍 수=TP, 미매칭 예측=FP, 미매칭 정답=FN입니다.

주 보고는 SOP 예측 전체와 정답 전체를 분모로 삼습니다. 모든 SOP 문서를 처리했으므로 처리 범위 보고와 주 보고가 같습니다. 정의서의 0.5/0.7 및 문장 형식 민감도는 보조 보고로만 사용했고, 점수에 유리한 설정으로 주 기준을 바꾸지 않았습니다.

## 5 문서별 추출·검증 집계

| 문서 | 예측 P | 정답 G | TP | FP | FN | Precision | Recall | F1_content | P/G | F1 상한 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{docs}
| 전체 SOP | {M['predictions']} | {M['gold']} | {M['TP']} | {M['FP']} | {M['FN']} | {pct(M['precision'])} | {pct(M['recall'])} | {pct(M['F1_content'])} | {M['granularity_ratio']:.3f} | {pct(M['theoretical_F1_upper_bound'])} |

데이터시트는 DS-ELEC-3300 2건, DS-MECH-4400 1건, DS-THERM-2200 1건입니다. 이 4건을 주 지표의 FP에 넣지 않았습니다. 원문·구조 검증에서는 {V['raw_rules']}건 중 {V['validated_rules']}건 통과, {V['rejected_rules']}건 제외였습니다. 원문 검증 통과와 정답 매칭 성공은 서로 다른 기준입니다.

## 6 보조 검사

| 문장 형식 | 임계값 | TP | FP | FN | Precision | Recall | F1_content |
|---|---:|---:|---:|---:|---:|---:|---:|
{sens}

plain은 단순 이어 붙이기, labeled는 `Condition: …`와 `Action: …`를 줄바꿈으로 연결한 형식입니다. 주 결과는 plain·0.6으로 고정했습니다.

분류까지 일치하는 보조 점수는 같은 매칭 쌍 중 분류까지 같은 {C['TP']}쌍만 TP로 계산했습니다. 이때 FP {C['FP']}, FN {C['FN']}, F1 {pct(C['F1'])}입니다.

| 정답 분류 | 예측 분류 | 매칭 수 |
|---|---|---:|
{confusion}

{sensor_text} GT-0009 binary는 후속 이벤트 단계 지표여서 N/A입니다. 등급 문자열 일치율은 이번 정의서 범위에서 제외했습니다.

매칭 알고리즘은 유효 쌍 수 우선·무효 유사도 제외·0.6 포함 경계·빈 문서 입력 검사에 통과했습니다. 원문 검증의 표 24개는 페이지 평탄 텍스트와 표 표현이 달라 직접 일치하지 않았고, 실제 표 셀·행·열·bbox로 검증했습니다. PDF 렌더 대조와 바이너리 해시 재계산은 실행하지 않았습니다.

## 7 KG와 원문 기반 검토

최종 후보 kg.candidate.v2.ttl은 {K['triples']:,}개 트리플이며 SHACL Conforms: True, 위반 {K['validation_results']}건입니다. Rule {V['validated_rules']}개, Document 7개, Station {V['stations']}개, Sensor {V['sensors']}개를 포함합니다. 첫 KG의 문자열 열거 표기 실패와 조정 이력도 초기 폴더에 보존돼 있습니다.

ai_review.jsonl은 원문 기반 AI 검토 기록이며 사람 승인본이 아닙니다. 센서 제품의 실제 설치 모델이 확인되지 않아 데이터시트와 SOP의 정격 차이는 검토 후보로 유지했습니다. 이번 정답 매칭에서 숫자 토큰이 다른 쌍 {E['numeric_disagreement_pairs']}개를 별도 로컬 진단 파일로 기록했습니다. 이는 원문의 오류나 수치 정확도를 확정하는 판정이 아니며, 정답이나 예측을 수정하는 데 사용하지 않았습니다.

## 8 재현성과 한계

| 고정 대상 | SHA-256 |
|---|---|
| 원본 freeze.json | `{h(R/'freeze.json')}` |
| 원본 predictions.raw.jsonl | `{E['prediction_sha256']}` |
| pre_evaluation_lock.json | `{h(O/'pre_evaluation_lock.json')}` |
| ground_truth.csv | `{E['gold_sha256']}` |
{defs}

버전: {versions}. 임베딩 가중치·토크나이저 파일 해시는 pre_evaluation_lock.json에 기록했습니다. 전체 입력·프롬프트·스키마·설정 해시는 초기 freeze.json을 참조합니다.

프로젝트의 과거 정답 노출 이력과, 허용 스키마·이번 첨부 정의서에 포함된 정답 집계 메타데이터 노출을 기록합니다. 이번 채점에서는 잠금 후 평가 코드만 정답을 읽었습니다. **독립 비공개 시험으로 주장하지 않습니다.** 유사도는 수치 오류에 관대할 수 있고, 복합 규칙의 원자화 차이도 일대일 지표에 영향을 줍니다. 추출 원본과 평가 결과는 분리했습니다.

## 9 기준 준수 상태

| 기준 | 상태 |
|---|---|
| 사용자 지정 두 평가 정의 적용 | 완료 |
| 예측·정의서·모델 revision·버전 사전 잠금 | 완료 |
| 동일 문서·일대일·유효 쌍 우선·클래스 제한 없음 | 완료 |
| 데이터시트 분리·정답 전체 분모·예측 합치기 금지 | 완료 |
| 정답 접근 후 기존 예측 변경 금지 | 준수: 원본 해시 동일 |
| 주·보조 점수와 민감도 분리 | 완료 |
| 개별 매칭 목록 공개·업로드 | 하지 않음: 로컬 파일만 저장 |
| 사람 승인·원본 PDF 렌더 대조 | 미실행 |

## 10 KG 연결 내용과 근거

KG에는 hasSensor, appliesToSensor, actionTarget, sourceDocument, hasProvenance와 원문 공정 순서 feedsInto를 사용했습니다. RULE-ST02-02는 ST02 온도 센서에 적용되며 ST02·ST03·ST04를 비상 정지 대상으로 연결합니다. MAINT-01은 SOP-003의 표 근거로 ST04 진동 센서에 연결합니다.

숫자 신뢰도 근거가 없는 인과 후보, 후속 단계 제한이 있는 상관 연결, 온톨로지 밖 Role/Zone·OccupancyEvent 연결은 별도 후보로 유지했습니다. 규칙별 인용·위치·해시와 연결은 [KG_근거.md](../run_20261016_01/KG_근거.md), kg.rule_links.jsonl, provenance.index.jsonl에서 확인할 수 있습니다.

## 11 산출물 경로와 재현 방법

평가 폴더: `{O.as_posix()}`

- 최종평가.md: 이번 채점 보고서.
- evaluation_results.json: 문서별·민감도·분류·센서 집계.
- pre_evaluation_lock.json / pre_evaluation_lock.sha256: 사전 고정 기록.
- evaluation_policy.json: 적용한 평가 규칙.
- src/imaks_kg/eval/__main__.py: 정답을 읽는 평가 코드.
- matches.local.jsonl / similarity_matrices.local.npz / numeric_diagnostics.local.json: 비공개 로컬 매칭·유사도·진단.
- evaluation_artifact_manifest.json: 평가 산출물 해시.

원본 추출·검증·KG는 형제 폴더 run_20261016_01에 있습니다. 초기 보고서와 freeze는 그대로 보존했습니다. 재현 명령과 제한은 [평가_재현방법.md](평가_재현방법.md)에 기록했습니다.

## 12 완료 범위와 남은 평가

고정 원본 예측에 대한 두 정의서 기준 F1_content 평가, 문서별 집계, 분류·센서 보조 검사, 임계값·문장 형식 민감도와 보고서 작성을 완료했습니다. 남은 항목은 숫자·단위·부등호·인과의 개별 원문 판정 및 사람 검토입니다. 새 점수에 맞춰 예측을 고치지 않았습니다.
'''
assert not (O/'최종평가.md').exists()
(O/'최종평가.md').write_text(report,encoding='utf-8')
repro=f'''# 평가 재현 방법

사용한 Python: `{O.as_posix()}/runtime/Scripts/python.exe`

이 평가는 최초 실행 전 pre_evaluation_lock.json으로 예측·정의서·코드·임베딩 모델·버전을 고정했습니다. 정의서와 정답 원본 경로는 lock과 evaluation_results.json에 있습니다. 평가 중 정답 문장을 화면에 출력하지 않으며 매칭 목록은 로컬에만 저장합니다.

평가 코드는 기존 결과 덮어쓰기를 막으므로 새 형제 평가 폴더를 사용해야 합니다. 새 폴더에 src/, evaluation_policy.json, prepare_evaluation.py, write_evaluated_report.py를 복사하고 같은 runtime/과 embedding_model/을 준비한 뒤 다음 순서로 실행합니다.

```powershell
& '<새 폴더>/runtime/Scripts/python.exe' '<새 폴더>/prepare_evaluation.py' lock
& '<새 폴더>/runtime/Scripts/python.exe' '<새 폴더>/src/imaks_kg/eval/__main__.py'
& '<새 폴더>/runtime/Scripts/python.exe' '<새 폴더>/write_evaluated_report.py'
```

새 평가 폴더는 원본 run_20261016_01 및 input과 같은 부모 아래 두어야 합니다. model revision은 1110a243fdf4706b3f48f1d95db1a4f5529b4d41이고, 다른 임베딩 모델로 자동 대체하지 않습니다. 이번 평가의 실제 패키지 버전은 pre_evaluation_lock.json과 requirements.lock.txt에 있습니다.

이미 정답을 채점한 뒤의 재실행이므로 최초 비공개 실험이라는 뜻은 없습니다. 원본 예측 SHA-256이 동일한지를 확인하고 결과를 비교합니다. 새 모델 추출이나 원문 예측 수정은 별도 실험으로 다뤄야 합니다.
'''
(O/'평가_재현방법.md').write_text(repro,encoding='utf-8')
with (O/'document_scores.csv').open('x',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=['document_id','predictions','gold','TP','FP','FN','precision','recall','F1_content','granularity_ratio','theoretical_F1_upper_bound']);writer.writeheader()
    for doc,v in M['per_document'].items():writer.writerow({'document_id':doc,**{k:v[k] for k in writer.fieldnames if k!='document_id'}})
files=[p for p in O.rglob('*') if p.is_file() and not any(part in ['runtime','embedding_model','model_cache','__pycache__'] for part in p.relative_to(O).parts) and not p.name.startswith('evaluation_artifact_manifest')]
manifest={p.relative_to(O).as_posix():h(p) for p in sorted(files)}
(O/'evaluation_artifact_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(O/'evaluation_artifact_manifest.sha256').write_text(h(O/'evaluation_artifact_manifest.json')+'  evaluation_artifact_manifest.json\n',encoding='ascii')
print(json.dumps({'report':str(O/'최종평가.md'),'F1_content':M['F1_content'],'precision':M['precision'],'recall':M['recall'],'TP':M['TP'],'FP':M['FP'],'FN':M['FN']},ensure_ascii=False))
