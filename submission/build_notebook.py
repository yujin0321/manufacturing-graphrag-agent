"""Create and execute the study notebook with an isolated local kernel spec."""
from pathlib import Path
import json
import os
import sys
import nbformat as nbf
from nbclient import NotebookClient

ROOT=Path(__file__).resolve().parent
md=nbf.v4.new_markdown_cell
code=nbf.v4.new_code_cell
nb=nbf.v4.new_notebook(cells=[
md('# iMAKS 전처리 + Ontology v1 실습\n2026-10-05 개인 제출용. 원본 ZIP을 보존하고 변경은 파생 파일에만 반영합니다. **출력까지 실행한 노트북**입니다. 알고리즘 상세는 `prepare.py`, 설계 이유는 `ontology_v1.md`를 읽으세요.'),
md('## 1. 경로와 원본 확인\n`submission` 폴더 또는 그 상위 프로젝트 폴더에서 실행할 수 있습니다.'),
code("from pathlib import Path\nimport sys, json\nimport pandas as pd\nfrom IPython.display import display\nROOT = Path.cwd() if (Path.cwd() / 'prepare.py').exists() else Path.cwd() / 'submission'\nassert (ROOT / 'prepare.py').exists()\nsys.path.insert(0, str(ROOT))\nfrom prepare import prepare\nsummary = prepare()\ndisplay(pd.DataFrame([summary])[['rows','sensors','stations','time_start','time_end']])"),
md('## 2. 파일·컬럼 파악\n센서 시계열과 KG는 `sensor_id ↔ Sensor.name`, `station_id ↔ Component.name`으로 연결합니다. 내부 KG 키는 `nodeId`입니다.'),
code("dictionary = pd.read_csv(ROOT / 'data_dictionary.csv')\ndisplay(dictionary.groupby('file', sort=False).agg(rows=('rows','first'), columns=('column','count')))\ndisplay(dictionary[dictionary.file.eq('sensors/timeseries_raw.csv')])"),
md('## 3. 센서별 품질 점검\n중복 키는 `(timestamp, sensor_id)`입니다. 같은 시각에 여러 센서가 측정한 것은 중복이 아닙니다.'),
code("raw = pd.read_csv(ROOT / 'data/raw/sensors/timeseries_raw.csv')\nraw['parsed_time'] = pd.to_datetime(raw.timestamp, errors='coerce')\nprint('결측 셀:', raw.isna().sum().sum())\nprint('중복 키:', raw.duplicated(['timestamp','sensor_id']).sum())\ndisplay(pd.read_csv(ROOT / 'reports/sensor_checks.csv'))"),
md('## 4. 전처리 결과와 정답 분리\n입력은 측정 시각·센서·스테이션·유형·값·단위만 허용합니다. 값 보정·평활화·정규화·보간은 하지 않았습니다. 정규화는 향후 학습 구간에서만 fit해야 합니다.'),
code("clean = pd.read_csv(ROOT / 'data/processed/timeseries_input.csv')\nassert list(clean.columns) == ['timestamp','sensor_id','station_id','sensor_type','value','unit']\nassert len(clean) == len(raw)\njoined = clean.merge(raw[['timestamp','sensor_id','value']], on=['timestamp','sensor_id'], suffixes=('_out','_raw'), validate='one_to_one')\nassert (joined.value_out == joined.value_raw).all()\nprint('측정값 및 행 수 보존 확인:', len(clean))\ndisplay(clean.head())"),
md('## 5. KG 구조와 평가용 이벤트 확인\n이 셀은 데이터 감사·평가 설계용입니다. 여기서 읽은 정답 이벤트를 탐지 특징이나 검색용 입력 KG에 넣지 않습니다.'),
code("display(pd.Series({k:summary[k] for k in ['node_count','edge_count','duplicate_node_ids','dangling_edges','metadata_mismatches','nodes_factory_conflicts','static_nodes','static_edges','production_events']}))\ndisplay(pd.read_csv(ROOT / 'reports/nodes_factory_conflicts.csv'))\nevents = pd.read_csv(ROOT / 'data/evaluation/events.csv')\ndisplay(events)\nassert events.rows_in_interval.sum() == summary['event_interval_rows']\nassert summary['anomaly_rows_outside_event_intervals'] == 0\nassert not summary['event_label_mismatches']"),
md('## 6. 문서 추출과 출처\n페이지별 텍스트, 레이아웃 텍스트, 표를 함께 보존합니다. 표 내부 줄바꿈과 페이지를 넘는 표는 LLM 추출 전에 추가 정리가 필요합니다.'),
code("docs = json.loads((ROOT / 'data/processed/documents.json').read_text(encoding='utf-8'))\ndisplay(pd.read_csv(ROOT / 'reports/document_checks.csv'))\nsample = next(x for x in docs if x['document_id'] == 'SOP-003')\nprint(sample['source_file'], 'page', sample['page'])\ndisplay(pd.DataFrame(sample['tables'][0][1:], columns=sample['tables'][0][0]))"),
md('## 7. SHACL 실습\n정상 예제가 통과하고 잘못된 예제가 실패하는지 확인합니다. `sample_valid.ttl`의 이벤트는 연습용이며 실제 탐지 결과가 아닙니다.'),
code("from validate_graph import run\nvalidation = pd.DataFrame(run())\ndisplay(validation)\nassert validation.test_passed.all()"),
md('## 8. 질문에 답하는 경로 확인\n문서 점검 단계는 수동 예제입니다. 규칙의 발동 조건 충족이나 GraphRAG 성능을 평가한 결과가 아닙니다.'),
code("answers = json.loads((ROOT / 'reports/competency_queries.json').read_text(encoding='utf-8'))\nfor name, answer in answers.items():\n    print(name, answer['rows'])"),
md('## 9. 회의 준비\n1. 제조 4개 스테이션으로 좁히면 이벤트는 9개입니다.\n2. ZIP 실제 이벤트 ID·날짜가 소개 페이지 일부와 다릅니다. 파일 해시를 고정합니다.\n3. 현재 SHACL은 구조를 검증하며 수치 임계값 및 문서 사실성 검증은 후속 단계입니다.\n4. `README.md`와 `reports/findings.md`를 보고 본인이 설명할 수 있는지 확인하세요.')
])
kernel='imaks-local'
kdir=ROOT/'.jupyter/kernels'/kernel
kdir.mkdir(parents=True,exist_ok=True)
(kdir/'kernel.json').write_text(json.dumps({'argv':[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}'],'display_name':'iMAKS local','language':'python'}),encoding='utf-8')
os.environ['JUPYTER_PATH']=str(ROOT/'.jupyter')
os.environ['JUPYTER_RUNTIME_DIR']=str(ROOT/'.jupyter/runtime')
nb.metadata={'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python','version':sys.version.split()[0]}}
NotebookClient(nb,timeout=180,kernel_name=kernel,resources={'metadata':{'path':str(ROOT)}}).execute()
nbf.write(nb,ROOT/'01_data_check.ipynb')
print('Notebook executed:',len([c for c in nb.cells if c.cell_type=='code']),'code cells')
