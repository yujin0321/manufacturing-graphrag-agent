from pathlib import Path
import os
import nbformat as nbf
from nbclient import NotebookClient

ROOT=Path(__file__).resolve().parent
for key,folder in [('JUPYTER_RUNTIME_DIR','jupyter'),('IPYTHONDIR','ipython'),('MPLCONFIGDIR','matplotlib')]:os.environ.setdefault(key,str(ROOT/'tmp'/folder))
cells=[]
def md(s):cells.append(nbf.v4.new_markdown_cell(s))
def code(s):cells.append(nbf.v4.new_code_cell(s))
md('''# 04. GraphRAG 비교 재설계: 유형별·동일 예산·반복 평가
비교 대상은 **하이브리드 검색 / 그래프 검색어 확장 / 그래프 경로+원문**입니다.
전체 GraphRAG의 보편적 성능이나 수리 성공률을 증명하는 실험은 아닙니다. 기존 질문은 개발용이고, 이번 질문은 새 조합·시점의 후속 고정 평가용입니다. 같은 문서와 일부 규칙이 겹치며 외부 독립 검증은 아닙니다.''')
code('''from pathlib import Path
import json
import pandas as pd
from IPython.display import display, Markdown, Image
ROOT=Path.cwd()
if not (ROOT/'benchmark_v2_outputs').exists():ROOT=ROOT.parent
OUT=ROOT/'benchmark_v2_outputs'
def read(name):return pd.read_csv(OUT/name)
def obj(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
display(obj('completion.json'))
display(obj('protocol.json'))''')
md('''## 1. 질문과 정답 기준
단일 문서·여러 관계·과거 경보·문서 간 비교·정보 부족의 5유형, 각 3개 질문입니다.
유형은 집계에만 사용하고 검색·답변 생성에 정답 힌트로 제공하지 않습니다. 대상 센서 문맥은 모든 방법에 동일하게 제공합니다.
정답 기준에는 필수 사실뿐 아니라 '무엇을 단정하면 안 되는지'도 포함합니다.''')
code('''definition=json.loads((ROOT/'benchmark_v2.json').read_text(encoding='utf-8'))
display(pd.DataFrame(definition['cases'])[['id','type','question','expected','condition']])''')
md('''## 2. 비교 조건
일반 검색은 BM25와 로컬 다국어 MiniLM 벡터 검색을 RRF로 결합합니다. 가장 강한 검색기를 찾기 위한 모델 비교는 수행하지 않았습니다.
확장 방식은 같은 하이브리드 검색에 관련 설비·규칙 검색어를 추가합니다.
경로 방식은 최대 3단계 정적 관계를 탐색하고 관계 경로·연결 규칙·과거 경보를 원문과 함께 제공합니다.
공통 코퍼스에는 그래프 사실의 텍스트 버전도 있어, 일반 검색이 원천적으로 보지 못하는 정답을 그래프에만 주입하지 않습니다.
모든 방법의 최대 문맥 예산은 1,800토큰입니다. 그래프 경로도 예산에 포함합니다. 공통 계수기 cl100k_base를 썼으며 GPT-6 네이티브 토크나이저와 동일하다는 주장은 하지 않습니다.
각 질문·방법은 2회 새 세션에서 생성합니다. temperature는 Codex CLI에서 직접 제어할 수 없고, 동일 모델·추론 설정을 적용했습니다.''')
code('''retrieval=read('retrieval_metrics.csv')
display(retrieval.groupby('mode')[['evidence_recall','all_evidence_found','context_tokens','source_count']].mean())
display(read('retrieval_by_type.csv'))''')
code('''display(Image(filename=str(OUT/'retrieval_by_type.png')))''')
md('''## 3. 시간 누수 방지와 실제 그래프 입력
경보는 이전 탐지 모델의 관측된 시작 시각만 사용합니다. 주입된 이상 시작 시각·미래 경보·수리 결과는 제외합니다.
T01의 정답 시간 차는 모델이 관측한 ST02 전류 경보 09:15:30과 ST04 속도 경보 09:30:00 사이의 14분30초입니다. 이는 실제 고장 시작 시간 차나 인과 증거가 아닙니다.''')
code('''contexts=obj('prepared_contexts.json')
example=next(p for p in contexts if p['id']=='T01' and p['mode']=='graph_paths')
display(example['context']['time_window'])
display(pd.DataFrame(example['context']['graph_paths']))
display(pd.DataFrame(example['context']['sources'])[['source_id','kind','text']])''')
md('''## 4. 실제 LLM 답변 품질과 비용
인용 ID 유효성은 자동 검사합니다. 근거 일치·조건 처리·완전성은 0–2점의 AI 평가입니다.
평가자에는 방법·반복 이름을 숨기고 답변 순서를 섞습니다. 그래프 형태로 방법을 추측할 가능성이 있어 완전한 맹검은 아닙니다.
같은 모델 계열의 자기평가 편향이 있을 수 있으므로 사람의 독립 검토를 대체하지 않습니다.
아래 비용은 서비스가 보고한 토큰 수와 실행 시간입니다. 금액이나 독립된 백엔드 모델 버전을 인증하지 않습니다.''')
code('''if (OUT/'answer_summary.csv').exists():
    display(read('answer_summary.csv'))
    display(read('answer_by_type.csv'))
    if (OUT/'answer_quality.png').exists():display(Image(filename=str(OUT/'answer_quality.png')))
else:
    print('LLM 답변 생성/평가가 아직 완료되지 않았습니다. 검색 성능만 확인 가능합니다.')''')
md('''## 5. 짝 비교와 불확실성
동일 질문의 두 반복 점수를 먼저 평균한 뒤 질문 ID를 단위로 5,000회 부트스트랩합니다.
차이는 비교 방법 − hybrid입니다. 신뢰구간이 0을 포함하면 이 실험만으로 개선을 확정하기 어렵습니다.
15개 질문은 같은 데이터에서 작성됐고 유형별 3개뿐이므로, 이 구간은 다른 공장·데이터셋으로의 일반화 범위를 나타내지 않습니다.''')
code('''display(read('paired_bootstrap.csv'))
if (OUT/'repeat_score_range.csv').exists():display(read('repeat_score_range.csv'))''')
md('''## 6. 답변과 평가 이유 직접 보기
아래 `case_to_review` 값을 S01, M02, T01, C03, N01 등으로 바꾸세요.
숫자만 보지 말고 실제 문서 근거와 채점 이유를 검토해야 합니다.''')
code('''case_to_review='T01'
if (OUT/'answer_review_detail.json').exists():
    for item in obj('answer_review_detail.json'):
        if item['case_id']==case_to_review:
            display(Markdown(f"### {item['mode']} / repeat {item['repeat']}"))
            print(item['answer']['answer'])
            print('인용:',item['answer']['citations'])
            if item['AI_review']:print('AI 평가:',item['AI_review']['rationale'])
else:print('아직 생성 답변이 없습니다.')''')
md('''## 재현
```powershell
.\\.venv\\Scripts\\python.exe prepare_benchmark_v2.py
.\\.venv\\Scripts\\python.exe -m unittest test_benchmark_v2 -v
.\\.venv\\Scripts\\python.exe run_benchmark_v2.py generate --workers 3
.\\.venv\\Scripts\\python.exe run_benchmark_v2.py judge --workers 3
.\\.venv\\Scripts\\python.exe summarize_benchmark_v2.py
.\\.venv\\Scripts\\python.exe build_benchmark_v2_notebook.py
```
생성·채점은 외부 서비스에 문맥을 전송합니다. 이 실험 범위는 사용자 승인 후 실행되었습니다. 성공 결과는 입력 해시가 같을 때 재사용합니다.
외부 독립 질문셋, 다른 데이터셋·LLM, 실제 정비 결과 기반 효과 검증은 아직 남아 있습니다.''')
nb=nbf.v4.new_notebook(cells=cells,metadata={'kernelspec':{'display_name':'Python (iMAKS .venv)','language':'python','name':'python3'}})
path=ROOT/'notebooks/04_graphrag_fair_benchmark.ipynb'
nbf.write(nb,path)
NotebookClient(nb,timeout=180,kernel_name='python3',resources={'metadata':{'path':str(ROOT)}}).execute()
nbf.write(nb,path)
print(path)
