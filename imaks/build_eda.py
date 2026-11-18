from pathlib import Path
import nbformat as nbf
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parent
cells = []
def md(s): cells.append(nbf.v4.new_markdown_cell(s))
def code(s): cells.append(nbf.v4.new_code_cell(s))

md('''# iMAKS — 설비 이상탐지 + 지식그래프 EDA
원본 ZIP을 직접 읽습니다. `csi`는 파일 목록만 조사하고 설비 센서, 그래프, 대응 이력을 우선 분석합니다.
**읽는 순서:** 데이터 지도 → 품질 → 시계열 → 이상 → 그래프 → 프로젝트 적용.
실제 측정/합성 여부와 SOP 원문 내용은 이 노트북에서 검증하지 않습니다.''')
code('''from pathlib import Path
from zipfile import ZipFile
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from IPython.display import display
ROOT = Path.cwd()
if not (ROOT / 'iMAKS_dataset.zip').exists():
    ROOT = ROOT.parent
OUT = ROOT / 'eda_outputs'
OUT.mkdir(exist_ok=True)
z = ZipFile(ROOT / 'iMAKS_dataset.zip')
pd.set_option('display.max_columns', 25)
def read_csv(name):
    with z.open(name) as f:
        return pd.read_csv(f)
def save_table(df, name):
    df.to_csv(OUT / (name + '.csv'), index=False, encoding='utf-8-sig')
def save_plot(name):
    plt.tight_layout()
    plt.savefig(OUT / (name + '.png'), dpi=150, bbox_inches='tight')
    plt.show()
''')
md('## 1. 데이터 지도\nCSV가 많아 보이는 이유와 프로젝트에서 필요한 파일을 구분합니다.')
code('''inventory = pd.DataFrame([{'path': e.filename, 'folder': e.filename.split('/')[0],
    'extension': Path(e.filename).suffix, 'bytes': e.file_size}
    for e in z.infolist() if not e.is_dir()])
save_table(inventory, 'file_inventory')
display(inventory.groupby(['folder', 'extension']).agg(files=('path','size'), bytes=('bytes','sum')))
core_paths = inventory.loc[(inventory.extension == '.csv') & (inventory.folder != 'csi'), 'path']
tables = {p: read_csv(p) for p in core_paths}
summary = pd.DataFrame([{'file': p, 'rows': len(df), 'columns': len(df.columns),
    'duplicate_rows': int(df.duplicated().sum())} for p, df in tables.items()])
display(summary)
save_table(summary, 'table_summary')
csi = inventory[inventory.folder.eq('csi') & inventory.extension.eq('.csv')].copy()
csi['subject'] = csi.path.str.split('/').str[1]
csi['activity'] = csi.path.str.split('/').str[-1].str.replace(r'\\d+\\.csv$', '', regex=True)
display(csi.groupby('activity').agg(files=('path','size'), subjects=('subject','nunique')))
''')
md('## 2. 스키마와 결측\n빈 severity는 정상 관측에 해당할 수 있습니다. 결측을 일괄 삭제하거나 0으로 채우지 않습니다.')
code('''profiles = []
for path, df in tables.items():
    for col in df:
        profiles.append({'file': path, 'column': col, 'dtype': str(df[col].dtype),
            'missing': int(df[col].isna().sum()), 'missing_pct': round(100*df[col].isna().mean(),3),
            'unique': int(df[col].nunique()), 'example': str(df[col].dropna().iloc[0]) if df[col].notna().any() else ''})
profile = pd.DataFrame(profiles)
save_table(profile, 'column_profile')
display(profile[profile.file.eq('sensors/timeseries_annotated.csv')])
sensor = tables['sensors/timeseries_annotated.csv'].copy()
raw = tables['sensors/timeseries_raw.csv'].copy()
sensor['timestamp'] = pd.to_datetime(sensor.timestamp, errors='coerce')
raw['timestamp'] = pd.to_datetime(raw.timestamp, errors='coerce')
keys = ['timestamp', 'sensor_id']
common = list(raw.columns)
raw_matches = raw[common].sort_values(keys).reset_index(drop=True).equals(sensor[common].sort_values(keys).reset_index(drop=True))
quality = {'invalid_timestamps': int(sensor.timestamp.isna().sum()),
    'duplicate_sensor_time': int(sensor.duplicated(keys).sum()),
    'missing_values': int(sensor.value.isna().sum()),
    'nonfinite_values': int((~np.isfinite(sensor.value)).sum()),
    'raw_matches_annotated_common_columns': raw_matches}
display(pd.Series(quality))
display(pd.crosstab(sensor.anomaly_label, sensor.severity.fillna('(missing)')))
display(sensor.quality.value_counts(dropna=False))
''')
md('## 3. 시간 범위·센서별 통계\n서로 다른 단위의 센서값은 합쳐서 평균내지 않습니다. 긴 간격은 교대·일자 경계와 함께 해석합니다.')
code('''sensor_stats = sensor.groupby(['station_id','sensor_id','sensor_type','unit']).agg(
    rows=('value','size'), start=('timestamp','min'), end=('timestamp','max'),
    mean=('value','mean'), std=('value','std'), minimum=('value','min'), maximum=('value','max')).reset_index()
display(sensor_stats)
save_table(sensor_stats, 'sensor_statistics')
ordered = sensor.sort_values(['sensor_id','timestamp']).copy()
ordered['interval_sec'] = ordered.groupby('sensor_id').timestamp.diff().dt.total_seconds()
intervals = ordered.groupby(['sensor_id','interval_sec']).size().rename('count').reset_index()
save_table(intervals, 'sampling_intervals')
display(intervals.groupby('interval_sec')['count'].sum().sort_values(ascending=False).head(15))
daily = sensor.groupby(sensor.timestamp.dt.date).size()
daily.plot.bar(figsize=(10,3), title='Observations per day', ylabel='Rows')
save_plot('daily_coverage')
''')
md('## 4. 이상 분포와 탐지 기준\n라벨은 평가용입니다. severity/alarm_flag 및 그래프의 정답 이상 이벤트를 탐지 입력에 넣지 않습니다. 아래 임계값 비교는 같은 데이터에 대한 기술 통계이며 일반화 성능 평가가 아닙니다.')
code('''label_counts = sensor.anomaly_label.value_counts(dropna=False).rename_axis('label').reset_index(name='rows')
label_counts['pct'] = label_counts.rows / len(sensor) * 100
display(label_counts)
save_table(label_counts, 'anomaly_distribution')
known = sensor.anomaly_label.notna()
is_anomaly = known & sensor.anomaly_label.ne('NORMAL')
threshold = ((sensor.value > sensor.warn_hi) | (sensor.value < sensor.warn_lo))
display(pd.crosstab(is_anomaly[known], threshold[known], rownames=['Labeled anomaly'], colnames=['Outside warning bounds']))
rates = sensor.assign(is_anomaly=is_anomaly).groupby('sensor_id').agg(rows=('value','size'), anomaly_rows=('is_anomaly','sum'))
rates['anomaly_pct'] = rates.anomaly_rows / rates.rows * 100
display(rates.sort_values('anomaly_pct', ascending=False))
save_table(rates.reset_index(), 'anomaly_by_sensor')
rates.anomaly_pct.sort_values().plot.barh(figsize=(9,7), title='Anomalous observations by sensor', xlabel='Percent of rows')
save_plot('anomaly_by_sensor')
sensor['_label'] = sensor.anomaly_label.fillna('UNKNOWN')
seq = sensor.sort_values(['sensor_id','timestamp']).copy()
seq['new_segment'] = (seq.sensor_id.ne(seq.sensor_id.shift()) | seq._label.ne(seq._label.shift()) |
    seq.timestamp.diff().dt.total_seconds().ne(seq.groupby('sensor_id').timestamp.diff().dt.total_seconds().groupby(seq.sensor_id).transform('median')))
seq['segment'] = seq.new_segment.cumsum()
episodes = seq[seq._label.ne('NORMAL')].groupby(['sensor_id','_label','segment']).agg(start=('timestamp','min'), end=('timestamp','max'), rows=('value','size')).reset_index()
save_table(episodes, 'observed_anomaly_segments')
display(episodes.head(25))
''')
md('## 5. 첫 사례: ST02 온도 SPIKE\n이상 구간 전후 30분을 시각화하고 경고·위험 임계값과 비교합니다.')
code('''responses = tables['human/alarm_response_log.csv'].copy()
responses['event_start_ts'] = pd.to_datetime(responses.event_start_ts)
example = responses.sort_values('event_start_ts').iloc[0]
t0 = example.event_start_ts
window = sensor[(sensor.sensor_id == example.sensor_id) & sensor.timestamp.between(t0-pd.Timedelta('30min'), t0+pd.Timedelta('30min'))]
display(example.to_frame('record'))
fig, ax = plt.subplots(figsize=(11,4))
ax.plot(window.timestamp, window.value, marker='.', label='Observed')
for col in ['warn_hi','crit_hi','warn_lo','crit_lo']:
    ax.plot(window.timestamp, window[col], linestyle='--', alpha=.65, label=col)
an = window[window.anomaly_label.ne('NORMAL')]
ax.scatter(an.timestamp, an.value, color='red', label='Labeled anomaly', zorder=5)
ax.set(title=str(example.sensor_id), ylabel=str(window.unit.iloc[0]))
ax.legend(ncol=3)
save_plot('first_anomaly_window')
save_table(window.drop(columns='_label'), 'first_anomaly_window')
''')
md('## 6. 그래프 연결과 ID 검증\n설비 ID와 nodeId는 서로 다릅니다. 이름 매핑과 관계 방향을 확인합니다. correlates_with는 인과관계를 뜻하지 않습니다.')
code('''nodes = tables['kg_seed/nodes.csv']
edges = tables['kg_seed/edges.csv']
rules = tables['kg_seed/ground_truth.csv']
display(nodes.label.value_counts().rename('nodes').to_frame())
display(edges.type.value_counts().rename('edges').to_frame())
node_ids = set(nodes.nodeId.dropna())
dangling = edges[~edges.fromId.isin(node_ids) | ~edges.toId.isin(node_ids)]
sensor_names = set(sensor.sensor_id)
mapped_names = set(nodes.name.dropna())
graph_checks = {'nodes': len(nodes), 'edges': len(edges), 'duplicate_node_ids': int(nodes.nodeId.duplicated().sum()),
    'duplicate_edges': int(edges.duplicated().sum()), 'dangling_edges': len(dangling),
    'unmapped_sensor_names': sorted(sensor_names - mapped_names),
    'unmapped_station_names': sorted(set(sensor.station_id) - mapped_names)}
print(json.dumps(graph_checks, indent=2, ensure_ascii=False))
enriched = edges.merge(nodes[['nodeId','name','label']], left_on='fromId', right_on='nodeId', how='left').rename(columns={'name':'from_name','label':'from_label'}).drop(columns='nodeId')
enriched = enriched.merge(nodes[['nodeId','name','label']], left_on='toId', right_on='nodeId', how='left').rename(columns={'name':'to_name','label':'to_label'}).drop(columns='nodeId')
save_table(enriched, 'edges_readable')
display(enriched[enriched.type.isin(['feeds_into','correlates_with','resolves'])])
display(rules[rules.station.eq(example.station_id)])
save_table(nodes[nodes.label.isin(['Component','Sensor'])], 'equipment_sensor_catalog')
''')
md('## 7. 대응 이력과 프로젝트 설계\n기록된 조치는 정답 권고안이나 실제 효과의 증명이 아닙니다. 실시간 모사에서는 사건 시점 이후 기록을 검색하지 않습니다.')
code('''display(responses.groupby(['anomaly_type','severity']).agg(events=('response_id','size'), mean_ack_min=('ack_delay_min','mean')))
display(responses.sla_met.value_counts(dropna=False))
display(rules.groupby(['source','class']).size().rename('rules').to_frame())
events = nodes[nodes.label.eq('AnomalyEvent')]
report = {'sensor_rows': len(sensor), 'start': str(sensor.timestamp.min()), 'end': str(sensor.timestamp.max()),
    'stations': int(sensor.station_id.nunique()), 'sensors': int(sensor.sensor_id.nunique()),
    'anomaly_rows': int(is_anomaly.sum()), 'anomaly_pct': float(100*is_anomaly.mean()),
    'graph_anomaly_events': len(events), 'response_records': len(responses), 'rules': len(rules),
    'quality': quality, 'graph': graph_checks}
(OUT/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
z.close()
''')
md('''## 다음 구현 순서
1. `equipment_sensor_catalog.csv`와 `edges_readable.csv`로 설비·센서·공정 그래프를 구성합니다.
2. 첫 이상 사례에 SOP 원문을 연결하고 문서명·페이지·근거 문장을 저장합니다. 규칙 CSV만으로 원문 검증을 대신하지 않습니다.
3. 초기에는 라벨로 이벤트 연결 흐름을 검증하고, 이후 탐지 모델의 예측 이벤트로 교체합니다.
4. 시간 순서로 학습/검증/평가를 분리합니다. 경계에 걸친 사건은 분리하지 않으며, 같은 사건의 인접 행이 양쪽에 들어가지 않게 합니다.
5. 행 단위 점수 외에 사건 탐지율·오탐 수·탐지 지연을 평가합니다. 사건 수가 적으면 성능 수치를 일반화하지 않습니다.
6. GraphRAG는 일반 문서 검색과 동일 질문·동일 LLM 조건으로 비교하고 근거 정확성·조치 일치 여부를 평가합니다.

**범위:** PDF 본문, MQTT JSON 내부, CSI 신호 품질은 이번 EDA에 포함하지 않았습니다. 임계값/라벨 생성 과정과 데이터 출처는 별도 확인이 필요합니다.''')
nb = nbf.v4.new_notebook(cells=cells, metadata={'kernelspec': {'display_name': 'Python (iMAKS .venv)', 'language': 'python', 'name': 'python3'}})
path = ROOT/'notebooks'/'01_imaks_eda.ipynb'
path.parent.mkdir(exist_ok=True)
nbf.write(nb, path)
NotebookClient(nb, timeout=180, kernel_name='python3', resources={'metadata': {'path': str(ROOT)}}).execute()
nbf.write(nb, path)
print(path)

