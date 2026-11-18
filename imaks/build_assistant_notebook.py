from pathlib import Path
import os
import nbformat as nbf
from nbclient import NotebookClient

ROOT=Path(__file__).resolve().parent
for key,folder in [('JUPYTER_RUNTIME_DIR','jupyter'),('IPYTHONDIR','ipython'),('MPLCONFIGDIR','matplotlib')]:
    os.environ.setdefault(key,str(ROOT/'tmp'/folder))
cells=[]
def md(s): cells.append(nbf.v4.new_markdown_cell(s))
def code(s): cells.append(nbf.v4.new_code_cell(s))
md('''# 03. 한국어 질의 · 새 평가셋 · 조치 조건 검증
한국어 질문에서 설비/센서를 확인하고 PDF 근거를 찾습니다. 조치 조건이 검증된 경우만 별도 목록으로 표시합니다.
**LLM 호출 없음.** 검색 후보, 규칙 조건 판정, LLM 생성 답변은 서로 다른 단계입니다.
이번 질문셋은 고정된 후속 사례 20개이며, 기존 8개와 일부 규칙이 겹칩니다. 같은 개발자가 작성했으므로 외부 독립 평가나 맹검 검증은 아닙니다.''')
code('''from pathlib import Path
import sys, json
import pandas as pd
from IPython.display import display, Markdown, Image
ROOT=Path.cwd()
if not (ROOT/'imaks_assistant.py').exists(): ROOT=ROOT.parent
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from imaks_assistant import Assistant, RULES
app=Assistant()
OUT=ROOT/'assistant_outputs'
def read(name): return pd.read_csv(OUT/name)
def obj(name): return json.loads((OUT/name).read_text(encoding='utf-8'))
display(obj('evaluation_protocol.json'))''')
md('''## 1. 한국어 설비·센서 식별
일반 번역 모델이 아니라 설비 별칭·센서 종류·기술 용어 사전입니다. 질문에 설비 두 개가 명시되면 대상 센서를 지정하도록 요청합니다.
센서가 불명확하거나 범위 밖이면 근거 후보와 조치를 생성하지 않습니다. 정확한 `sensor_hint`를 명시할 수 있지만 질문과 모순되면 재확인합니다.''')
code('''data=json.loads((ROOT/'evaluation_ko.json').read_text(encoding='utf-8'))['cases']
rows=read('evaluation_per_question.csv')
routing=rows[rows.kind.eq('routing')]
display(routing[['id','expected','actual','correct']])
for question in ['온도가 올라갔어','ST99 온도 기준은?','밀봉기 전압이 높아졌어']:
    result=app.ask(question)
    print(question, '→', result['status'], result['reason'])''')
md('''## 2. 검색 비교: 14개 근거 질문, top-k=3
나머지 6개는 모호성·지원 범위 확인용입니다. 조회에 정답 센서 ID를 주입하지 않고 한국어에서 식별한 센서를 사용합니다.
`raw_korean`: 기존 영문 토큰 검색에 한국어 원문을 그대로 입력.
`normalized_text`: 기술 용어를 영문으로 보강한 일반 검색.
`normalized_graph`: 같은 보강에 기존 그래프 확장 적용.
필수 근거 회수율은 모든 정답 근거 그룹을 기준으로 계산합니다. 일부 질문은 SOP와 데이터시트 두 문서가 모두 필요합니다.
평가 후 검색 가중치를 재튜닝하지 않았습니다. 원문 비교 질문의 정답은 '문서가 검색되는가'이며 센서 모델 적용 가능성까지 검증한 결론이 아닙니다.''')
code('''summary=read('retrieval_summary.csv')
display(summary)
import matplotlib.pyplot as plt
ax=summary.set_index('mode')[['hit_at_3','recall_at_3','mrr_at_3']].plot.bar(figsize=(10,4),ylim=(0,1.08),rot=10)
ax.set_title('Fixed follow-up Korean questions: retrieval only')
plt.tight_layout()
plt.savefig(OUT/'korean_retrieval_comparison.png',dpi=150)
plt.close()
display(Image(filename=str(OUT/'korean_retrieval_comparison.png')))
pivot=rows[rows.kind.eq('retrieval')].pivot(index='id',columns='mode',values='recall_at_3')
display(pivot)
print('그래프 보강으로 회수율이 낮아진 질문:')
display(pivot[pivot.normalized_graph < pivot.normalized_text])''')
md('''## 3. 조치 조건 검증
현재 실행 가능한 규칙은 12개입니다. 지원하지 않는 규칙을 정상/조치 불필요로 해석하지 않습니다.
- 엄격한 `>` / `<` 경계, 측정 단위, 유한 수치, 현재 시각을 확인합니다.
- 공칭값보다 1.5A 초과 상태가 5분을 넘었는지는 연속 과거 관측으로 확인합니다.
- 속도 저하 규칙은 작업자 명령 여부가 없으면 판정을 보류합니다.
- 장력 정체는 11개 연속 동일 관측을 확인합니다.
- 시간 공백, 미래 데이터, 현재값 불일치가 있으면 판정을 보류합니다.
**구현 정책:** 30초 수집 간격과 최대 30초 최신성을 적용했습니다. 이는 이 데이터에 맞춘 구현 가정이며 SOP 자체의 요구로 주장하지 않습니다. 수치의 진실성은 입력 데이터에 의존합니다.''')
code('''checks=read('condition_validation.csv')
display(checks)
print(f"조건 검증: {checks.passed.sum()}/{len(checks)}")
display(pd.DataFrame(RULES)[['id','source','sensor','kind','action']])''')
md('''## 4. 실제 첫 ST02 측정값으로 확인
원본 raw의 2026-01-06 08:30 관측을 사용합니다. 정답 라벨 없이 수치와 SOP 조건을 비교합니다.
이 데이터의 기록 시각을 기준 시각으로 사용한 과거 재현입니다. 현재 공장의 실시간 상태라는 뜻은 아닙니다.''')
code('''first=obj('first_verified_action.json')
display(pd.DataFrame(first['checks'])[['rule_id','state','reason','value','threshold']])
for action in first['verified_actions']:
    print('조건 충족 시 문서상 조치:',action['action'])
    citation=action['citation']
    print(citation['document'], 'p.',citation['page'])
    print(citation['text'])''')
md('''## 5. 직접 한국어 질문하기
아래 `question`과 필요 시 `sensor_hint`를 바꾸세요. 관측값을 제공하지 않으면 문서를 검색하지만 조치 조건을 충족했다고 판단하지 않습니다.
`mode='text'`는 일반 검색, `mode='graph'`는 그래프 보강 검색입니다.''')
code('''question='포장기 속도가 명령 없이 떨어졌어. 관련 전류 규칙은?'
result=app.ask(question, sensor_hint='ST04_PACKAGING_SPD', mode='text')
print(result['status'])
if result['status']=='ready':
    display(pd.DataFrame(result['retrieved'])[['document','page','rule_id','score','text']])
    display(pd.DataFrame(result['checks'])[['rule_id','state','reason']])
    print('검증된 조치:',result['verified_actions'])
else: print(result['reason'])''')
md('''## 6. 같은 조건으로 LLM 답변 비교하기 위한 준비
`llm_requests.jsonl`은 일반 검색/그래프 검색 각 14개씩 총 28개 미실행 요청입니다.
동일한 시스템 프롬프트·질문·센서 문맥·temperature=0을 사용합니다. 모델은 아직 지정하지 않았습니다.
검색 문맥이 다르므로 길이도 달라질 수 있습니다. 토큰 예산이 완전히 같다고 주장하지 않습니다.
질문 속 숫자는 검증된 관측으로 입력하지 않습니다. 정답 규칙·평가 라벨은 프롬프트에 넣지 않습니다.
나중에 생성한 답변을 `evaluate_llm_answers.py`로 검사하면 동일 모델/온도/프롬프트 및 인용 ID를 확인합니다. 의미상 근거와 조치 일치 여부는 수동 평가 칸으로 남깁니다.''')
code('''requests=[json.loads(s) for s in (OUT/'llm_requests.jsonl').read_text(encoding='utf-8').splitlines()]
display(pd.DataFrame([{k:r[k] for k in ['id','mode','model','temperature','status']} for r in requests]))
print('실행된 LLM 요청 수:',sum(r['status']!='not_run' for r in requests))
print(requests[0]['messages'][0]['content'])''')
md('''## 실행 명령
```powershell
.\\.venv\\Scripts\\python.exe imaks_assistant.py
.\\.venv\\Scripts\\python.exe -m unittest test_assistant test_answer_review test_pipeline -v
.\\.venv\\Scripts\\python.exe -c "from test_assistant import save_condition_report; save_condition_report()"
.\\.venv\\Scripts\\python.exe build_assistant_notebook.py
```
범위: 한국어 사전 기반 검색, 일부 규칙 조건 검증, 고정 질문셋 비교. 범용 한국어 의미 이해, 센서 모델별 데이터시트 적용 감사, LLM 답변 평가는 아직 수행하지 않았습니다.''')
nb=nbf.v4.new_notebook(cells=cells,metadata={'kernelspec':{'display_name':'Python (iMAKS .venv)','language':'python','name':'python3'}})
path=ROOT/'notebooks/03_korean_conditions_evaluation.ipynb'
nbf.write(nb,path)
NotebookClient(nb,timeout=180,kernel_name='python3',resources={'metadata':{'path':str(ROOT)}}).execute()
nbf.write(nb,path)
print(path)
