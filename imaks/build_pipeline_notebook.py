from pathlib import Path
import os
import nbformat as nbf
from nbclient import NotebookClient

ROOT=Path(__file__).resolve().parent
for key,folder in [('JUPYTER_RUNTIME_DIR','jupyter'),('IPYTHONDIR','ipython'),('MPLCONFIGDIR','matplotlib')]:
    os.environ.setdefault(key,str(ROOT/'tmp'/folder))
cells=[]
def md(text): cells.append(nbf.v4.new_markdown_cell(text))
def code(text): cells.append(nbf.v4.new_code_cell(text))
md('''# 02. 설비 그래프 → SOP 근거 → 이상탐지 → 검색 비교
**실행 범위:** 6단계 중 그래프·근거 연결·예측 이벤트 연결·시간 분할·사건 평가·검색 비교를 로컬에서 실행했습니다.
사용자 선택에 따라 **LLM을 호출하지 않았습니다**. 생성 답변의 정확성이나 조치 일치율은 측정하지 않았습니다.
이 노트북은 재현 스크립트가 저장한 결과를 읽습니다. 아래 마지막 셀의 명령으로 파이프라인을 재실행할 수 있습니다.''')
code('''from pathlib import Path
import json
import pandas as pd
from IPython.display import display, Image, Markdown
ROOT=Path.cwd()
if not (ROOT/'pipeline_outputs').exists(): ROOT=ROOT.parent
OUT=ROOT/'pipeline_outputs'
def read(name): return pd.read_csv(OUT/name)
def obj(name): return json.loads((OUT/name).read_text(encoding='utf-8'))
display(obj('manifest.json'))''')
md('''## 1. 설비·센서·공정 그래프
원본의 양방향 `monitors` 중 설비→센서 방향을 `has_sensor`로 정규화했습니다. 원본 관계와 출처는 보존합니다.
정답 이상 이벤트·causedBy·대응 결과는 검색용 정적 그래프에 포함하지 않습니다. 빨간 선은 문서에 명시된 상관 관계로, 관측만으로 인과를 증명하는 것은 아닙니다.''')
code('''display(Image(filename=str(OUT/'equipment_graph.png')))
graph=obj('static_graph.json')
display(pd.DataFrame(graph['edges']).groupby('relation').size().to_frame('edges'))
display(pd.DataFrame(obj('graph_document_links.json')).head())''')
md('''## 2. 첫 이상과 SOP 원문 연결
PDF 7개, 총 10페이지를 추출·렌더링했습니다. 모든 검색 청크는 해당 페이지에 동일한 원문이 존재하는지 검사합니다.
ST02 사례에서는 **측정값, SOP의 규정 조치, 이후 대응 로그**를 구분합니다. 아래 근거의 페이지는 PDF 실제 페이지 번호(1부터)입니다.''')
code('''first=obj('first_event_evidence.json')
display(first['observation'])
evidence=first['source_evidence']
display(Markdown(f"**{evidence['document']} / p.{evidence['page']} / {evidence['rule_id']}**"))
print(evidence['text'])
print('이상 발생 시점에 이용 가능한 대응 기록:',first['logged_responses_available_as_of'])
display(first['retrospective_only'])
display(Image(filename=str(OUT/'sources/SOP_001_OperatingProcedures_p1.png'),width=760))''')
md('''## 3. 시간순 학습·검증·평가
학습 1/6, 검증 1/7, 평가 1/8–1/9. 알려진 이상 사건이 분할 경계를 가로지르면 실행을 중단합니다.
학습에 라벨을 쓰지 않는 median/MAD 모델입니다. 학습일에도 이상이 있으므로 오염된 학습 데이터에 대한 강건한 기준 모델입니다.
rolling은 현재와 과거만 사용하고 분할 경계와 시간 공백에서 초기화합니다. 검증의 사건 F1로 임계값을 선택하며 평가 결과로 재선택하지 않습니다.''')
code('''display(read('temporal_splits.csv'))
display(obj('selected_model.json'))
display(read('validation_selection.csv').head(8))''')
md('''## 4. 사건 단위 탐지 성능
`sop_threshold`: raw CSV에 제공된 경고 상·하한 기준. `robust_causal`: 학습 통계의 순간 편차 + trailing 평균 편차 + 정체 규칙.
예측 양성이 30초 간격으로 이어지는 구간을 경보 한 건으로 봅니다. 실제 사건과 같은 센서에서 시간 구간이 겹치면 일대일 매칭합니다.
중복 조각 경보는 unmatched에 포함합니다. `pure_false_alarm_events`는 실제 사건과 전혀 겹치지 않는 경보입니다.
지연은 탐지된 사건만 대상으로 계산합니다. `onset_offset_min`이 음수이면 실제 시작 전부터 경보가 활성화되어 있던 경우입니다.
관측 센서-일 기준으로 오탐을 정규화합니다. 소수 사건 결과를 장기 운영 성능으로 일반화하지 않습니다.''')
code('''metrics=read('detection_metrics.csv')
display(metrics[metrics['split'].eq('test')].T)
display(Image(filename=str(OUT/'detection_comparison.png')))
display(read('robust_causal_test_event_matches.csv'))''')
md('''## 5. 탐지 이벤트를 그래프·문서 검색으로 연결
아래 패키지는 정답 라벨이 아니라 평가 구간의 모델 경보 시작 시각에서 생성합니다.
현재 측정값·관련 설비·이미 관측된 경보·문서 후보만 포함합니다. 미래의 경보 종료 시각이나 대응 결과를 검색 문맥에 넣지 않습니다.
검색 결과는 후보입니다. 조건 충족을 검증한 자동 조치 권고나 LLM 답변으로 간주하지 않습니다.''')
code('''packages=obj('predicted_event_evidence.json')
print('예측 경보 근거 패키지 수:',len(packages))
if packages:
    p=packages[0]
    display({k:v for k,v in p.items() if k!='source_candidates'})
    display(pd.DataFrame(p['source_candidates'])[['chunk_id','document','page','rule_id','score','text']])''')
md('''## 6. 일반 검색 vs 그래프 보강 검색
동일한 문서 청크, 질문 8개, 센서 문맥, top-k=3을 사용합니다. 기본은 BM25, 비교군은 정적 그래프의 공정 인접 설비·명시된 상관 관계를 쿼리에 추가합니다.
질문은 PDF에서 수작업으로 만든 **영문 개발용 사례**이며 독립 평가셋이 아닙니다. 한국어 의미 검색을 검증하지 않았습니다.
`hit_at_3`: 관련 규칙 하나 이상 회수. `gold_rule_recall_at_3`: 필요한 규칙의 회수 비율. `mrr_at_3`: 첫 관련 규칙 순위 역수.
`action_evidence_coverage`: 정해진 조치 문구가 검색된 문맥에 있는 비율. **생성 답변의 조치 일치율이 아닙니다.**''')
code('''display(read('retrieval_comparison.csv'))
display(read('retrieval_per_question.csv'))
details=obj('retrieval_details.json')
for item in details:
    if item['question_id']=='Q03':
        print(item['mode'],item['query'])
        display(pd.DataFrame(item['hits'])[['document','page','rule_id','score','text']])''')
md('''## 재현 및 다음 단계
VS Code 터미널에서 프로젝트 루트를 기준으로 실행:
```powershell
.\\.venv\\Scripts\\python.exe inspect_sources.py
.\\.venv\\Scripts\\python.exe imaks_pipeline.py
.\\.venv\\Scripts\\python.exe -m unittest test_pipeline -v
.\\.venv\\Scripts\\python.exe build_pipeline_notebook.py
```
추가 작업은 독립 질문셋 작성, 한국어 쿼리 처리, 근거 조건 검증, LLM 선택 후 동일 프롬프트·모델로 답변 비교입니다.
외부 서비스 호출 및 설비 제어 명령은 실행하지 않았습니다.''')
nb=nbf.v4.new_notebook(cells=cells,metadata={'kernelspec':{'display_name':'Python (iMAKS .venv)','language':'python','name':'python3'}})
path=ROOT/'notebooks/02_graph_detection_retrieval.ipynb'
nbf.write(nb,path)
NotebookClient(nb,timeout=180,kernel_name='python3',resources={'metadata':{'path':str(ROOT)}}).execute()
nbf.write(nb,path)
print(path)
