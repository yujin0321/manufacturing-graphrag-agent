"""Reproducible iMAKS inspection; run from any directory. No model training."""
from pathlib import Path
import hashlib
import json
import re
import zipfile
import importlib.metadata
import pandas as pd
import pdfplumber

ROOT = Path(__file__).resolve().parent
RAW = ROOT / 'data/raw'
OUT = ROOT / 'data/processed'
EVAL = ROOT / 'data/evaluation'
REPORT = ROOT / 'reports'

def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

def save(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding='utf-8-sig')

def prepare():
    for p in [RAW, OUT, EVAL, REPORT]:
        p.mkdir(parents=True, exist_ok=True)
    archive = ROOT / 'data/source/iMAKS_dataset.zip'
    if not archive.exists():
        raise FileNotFoundError('Download https://zenodo.org/records/20075430/files/iMAKS_dataset.zip to data/source/')
    digest = hashlib.md5(archive.read_bytes()).hexdigest()
    assert digest == '1670c2d42e9495b9b06a79b867fc5d15', 'Source version/checksum changed; review before proceeding'
    with zipfile.ZipFile(archive) as z:
        inventory = []
        for info in z.infolist():
            if info.is_dir():
                continue
            selected = info.filename.startswith(('sensors/', 'kg_seed/', 'rules/', 'datasheets/')) and not info.filename.endswith('.DS_Store')
            inventory.append({'path': info.filename, 'bytes': info.file_size, 'selected': selected})
            if selected:
                dst = (RAW / info.filename).resolve()
                if not dst.is_relative_to(RAW.resolve()):
                    raise ValueError('Unsafe archive path')
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(z.read(info))
    save(pd.DataFrame(inventory), REPORT / 'archive_inventory.csv')
    dump(REPORT / 'source_manifest.json', {'record': 'https://zenodo.org/records/20075430', 'download_date': '2026-10-05', 'md5': digest,
         'files': {str(p.relative_to(RAW)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(RAW.rglob('*')) if p.is_file()}})
    frames = {p.relative_to(RAW).as_posix(): pd.read_csv(p, low_memory=False) for p in sorted(RAW.rglob('*.csv'))}
    descriptions = {'timestamp':'측정 시각; 시간대 정보 없음', 'sensor_id':'센서 식별자; KG Sensor.name과 연결',
        'station_id':'스테이션 식별자; KG Component.name과 연결', 'value':'원래 단위의 측정값',
        'unit':'측정 단위', 'nodeId':'KG 내부 노드 키', 'fromId':'관계 시작 노드 키', 'toId':'관계 끝 노드 키',
        'anomaly_label':'정답 이상 유형; 입력 금지', 'severity':'정답/규칙 심각도; 파일 맥락에 따라 해석',
        'alarm_flag':'사전 계산된 경보; 탐지 입력 제외', 'quality':'측정 품질 메타데이터; 기본 입력 제외',
        'ruleId':'규칙 식별자; 문서 명시 여부와 별개', 'name':'노드 이름; label별 의미가 다름',
        'label':'KG 노드 클래스', 'type':'KG 관계/유형; 파일별 의미 확인', 'source':'규칙 출처 문서 ID',
        'ruleRef':'기존 KG의 규칙 참조; 기본 입력 제외',
        'day':'원본 시뮬레이션 일차; 실제 timestamp와 교차 확인', 'shift':'근무 교대', 'batch_id':'배치 식별자',
        'zone':'구역명', 'sensor_type':'측정 유형 코드', 'nominal':'원본 기준 측정값',
        'warn_hi':'경고 상한', 'warn_lo':'경고 하한', 'crit_hi':'위험 상한', 'crit_lo':'위험 하한',
        'class':'규칙 클래스', 'station':'규칙 대상 스테이션', 'sensor':'규칙 대상 센서',
        'sensorType':'측정 유형 코드', 'condition':'규칙 발동 조건', 'action':'규칙 대응 행동',
        'critHi':'위험 상한', 'critLo':'위험 하한', 'warnHi':'경고 상한', 'warnLo':'경고 하한',
        'anomalyType':'정답 이상 유형; 입력 제외', 'causedBy':'정답 원인 연결; 입력 제외',
        'csiSubject':'CSI 대상 식별자; 이번 범위 제외', 'dept':'부서; 이번 범위 제외',
        'description':'설명', 'durationMin':'이벤트 지속시간(분)', 'durationSec':'이벤트 지속시간(초)',
        'startTs':'이벤트 시작 시각', 'endTs':'이벤트 종료 시각; 주석은 종료 표본 포함',
        'eventId':'이벤트 식별자', 'gtId':'정답 이상 이벤트 식별자', 'line':'생산라인',
        'magnitude':'합성 이상 크기; 입력 제외', 'nominalValue':'센서 기준 측정값',
        'personId':'인물 식별자; 이번 범위 제외', 'priority':'점검 우선순위', 'role':'역할; 이번 범위 제외',
        'sourceRule':'정답 이벤트에 연결된 규칙; 입력 제외', 'stationType':'스테이션 유형'}
    dictionary=[]
    for filename, df in frames.items():
        for col in df:
            dictionary.append({'file': filename, 'rows':len(df), 'column':col, 'dtype':str(df[col].dtype),
                'missing':int(df[col].isna().sum()), 'unique':int(df[col].nunique()),
                'example':str(df[col].dropna().iloc[0]) if df[col].notna().any() else '',
                'meaning':descriptions.get(col, '원본 필드 유지; ontology_v1.md 및 원문과 함께 해석')})
    save(pd.DataFrame(dictionary), ROOT / 'data_dictionary.csv')
    raw=frames['sensors/timeseries_raw.csv']
    ann=frames['sensors/timeseries_annotated.csv']
    nodes=frames['kg_seed/nodes.csv']
    edges=frames['kg_seed/edges.csv']
    gt=frames['kg_seed/ground_truth.csv']
    factory=frames['kg_seed/nodes_factory.csv']
    factory_join=factory.merge(nodes[['nodeId','label','name']],on='nodeId',how='left',suffixes=('_factory','_seed'),validate='one_to_one')
    factory_conflicts=factory_join[factory_join.label_factory.ne(factory_join.label_seed)|factory_join.name_factory.ne(factory_join.name_seed)]
    save(factory_conflicts,REPORT/'nodes_factory_conflicts.csv')
    key=['timestamp','sensor_id']
    assert not raw.duplicated(key).any(), 'Resolve duplicate keys explicitly'
    assert not ann.duplicated(key).any(), 'Resolve annotation duplicate keys explicitly'
    assert raw[raw.columns].equals(ann[raw.columns]), 'Raw and annotated common fields differ'
    parsed=pd.to_datetime(raw.timestamp, errors='coerce')
    numeric=pd.to_numeric(raw.value, errors='coerce')
    assert parsed.notna().all() and numeric.notna().all(), 'Review invalid core values'
    sensor_nodes=nodes[nodes.label.eq('Sensor')]
    station_nodes=nodes[nodes.label.eq('Component')]
    checks=[]
    for sid, block in raw.assign(parsed=parsed).groupby('sensor_id'):
        times=block.parsed.sort_values()
        delta=times.diff().dt.total_seconds().dropna()
        gaps=delta[delta.ne(30)]
        checks.append({'sensor_id':sid, 'rows':len(block), 'start':times.min(), 'end':times.max(),
            'missing_cells':int(block.isna().sum().sum()), 'duplicate_keys':int(block.duplicated(key).sum()),
            'original_time_sorted':bool(block.parsed.is_monotonic_increasing),
            'non_30_second_intervals':len(gaps), 'other_intervals_seconds':json.dumps(gaps.value_counts().to_dict()),
            'units':','.join(block.unit.unique()), 'station_count':block.station_id.nunique(),
            'kg_sensor_match':sid in set(sensor_nodes.name), 'min_value':block.value.min(), 'max_value':block.value.max()})
    save(pd.DataFrame(checks), REPORT/'sensor_checks.csv')
    core=['timestamp','sensor_id','station_id','sensor_type','value','unit']
    clean=raw[core].copy()
    clean.timestamp=parsed.dt.strftime('%Y-%m-%dT%H:%M:%S')
    clean=clean.sort_values(['sensor_id','timestamp'],kind='stable').reset_index(drop=True)
    save(clean,OUT/'timeseries_input.csv')
    save(clean[clean.station_id.str.startswith(('ST01_','ST02_','ST03_','ST04_'))],OUT/'timeseries_production.csv')
    save(ann[key+['anomaly_label','severity','alarm_flag']],EVAL/'point_labels.csv')
    save(gt,EVAL/'ground_truth_rules.csv')
    # Whitelist static classes AND fields. Maintenance nodes may encode gold answers.
    static=nodes[nodes.label.isin(['System','Zone','Component','Sensor'])][['nodeId','label','name','stationType','sensorType','unit','zone']].copy()
    ids=set(static.nodeId)
    static_edges=edges[edges.fromId.isin(ids)&edges.toId.isin(ids)&edges.type.isin(['contains','part_of','monitors','feeds_into'])][['fromId','toId','type']].copy()
    save(static,OUT/'static_nodes.csv'); save(static_edges,OUT/'static_edges.csv')
    rejected=edges[~edges.index.isin(static_edges.index)]
    save(rejected,EVAL/'excluded_seed_edges.csv')
    save(nodes[~nodes.nodeId.isin(ids)],EVAL/'excluded_seed_nodes.csv')
    sensor_map=raw[['sensor_id','station_id','sensor_type','unit']].drop_duplicates()
    save(sensor_map,OUT/'sensor_metadata.csv')
    mapping=nodes.set_index('nodeId')
    events=[]
    covered=pd.Series(False,index=ann.index)
    for _, ev in nodes[nodes.label.eq('AnomalyEvent')].iterrows():
        connected=edges[(edges.fromId.eq(ev.nodeId)&edges.toId.isin(set(sensor_nodes.nodeId))) | (edges.toId.eq(ev.nodeId)&edges.fromId.isin(set(sensor_nodes.nodeId)))]
        sensors=set(connected.fromId)|set(connected.toId)
        sensors &= set(sensor_nodes.nodeId)
        for sensor in sorted(sensors):
            sid=mapping.loc[sensor,'name']
            mask=ann.sensor_id.eq(sid)&parsed.ge(pd.Timestamp(ev.startTs))&parsed.le(pd.Timestamp(ev.endTs))
            covered |= mask
            events.append({'event_id':ev.gtId,'sensor_id':sid,'start':ev.startTs,'end_inclusive':ev.endTs,
                'anomaly_type':ev.anomalyType,'rows_in_interval':int(mask.sum()),
                'matching_label_rows':int((mask&ann.anomaly_label.eq(ev.anomalyType)).sum()),
                'split_proposal':'development' if int(ev.gtId.split('-')[1])<=9 else 'test',
                'production_scope':sid.startswith(('ST01_','ST02_','ST03_','ST04_'))})
    event_df=pd.DataFrame(events)
    save(event_df,EVAL/'events.csv')
    # Metadata comparison does not copy gold thresholds into detection inputs.
    mismatches=[]
    fields={'sensor_type':'sensorType','unit':'unit','nominal':'nominalValue','warn_hi':'warnHi','crit_hi':'critHi','warn_lo':'warnLo','crit_lo':'critLo'}
    for sid, block in raw.groupby('sensor_id'):
        ns=sensor_nodes[sensor_nodes.name.eq(sid)]
        for col,ncol in fields.items():
            values=block[col].drop_duplicates().tolist()
            if len(ns)!=1 or len(values)!=1 or values[0]!=ns.iloc[0][ncol]:
                mismatches.append({'sensor_id':sid,'field':col,'timeseries':values,'kg':ns[ncol].tolist()})
    dump(REPORT/'metadata_mismatches.json',mismatches)
    summary={'rows':len(raw),'sensors':raw.sensor_id.nunique(),'stations':raw.station_id.nunique(),
        'time_start':str(parsed.min()),'time_end':str(parsed.max()),'dates':sorted(parsed.dt.strftime('%Y-%m-%d').unique()),
        'missing_raw_cells':int(raw.isna().sum().sum()),'duplicate_keys':int(raw.duplicated(key).sum()),
        'invalid_timestamp':int(parsed.isna().sum()),'invalid_value':int(numeric.isna().sum()),
        'raw_annotation_values_identical':True,'node_count':len(nodes),'edge_count':len(edges),
        'duplicate_node_ids':int(nodes.nodeId.duplicated().sum()),'duplicate_edge_rows':int(edges.duplicated().sum()),
        'nodes_factory_conflicts':len(factory_conflicts),
        'dangling_edges':int((~edges.fromId.isin(nodes.nodeId)|~edges.toId.isin(nodes.nodeId)).sum()),
        'unknown_sensors':sorted(set(raw.sensor_id)-set(sensor_nodes.name)),
        'unknown_stations':sorted(set(raw.station_id)-set(station_nodes.name)),
        'metadata_mismatches':len(mismatches),'label_counts':ann.anomaly_label.value_counts().to_dict(),
        'node_labels':nodes.label.value_counts().to_dict(),'edge_types':edges.type.value_counts().to_dict(),
        'rules':len(gt),'rules_by_class':gt['class'].value_counts().to_dict(),
        'events':int(nodes.label.eq('AnomalyEvent').sum()),'events_with_sensor_links':len(event_df),
        'static_nodes':len(static),'static_edges':len(static_edges),
        'production_rows':int(raw.station_id.str.startswith(('ST01_','ST02_','ST03_','ST04_')).sum()),
        'production_events':int(event_df.production_scope.sum()),
        'anomaly_rows_outside_event_intervals':int((~covered&ann.anomaly_label.ne('NORMAL')).sum()),
        'event_interval_rows':int(covered.sum()),
        'event_label_mismatches':event_df[event_df.rows_in_interval.ne(event_df.matching_label_rows)].to_dict('records')}
    dump(REPORT/'data_quality.json',summary)
    pages=[]
    for pdf in sorted(RAW.rglob('*.pdf')):
        with pdfplumber.open(pdf) as doc:
            header=doc.pages[0].extract_text() or ''
            doc_match=re.search(r'Document:\s*([^|\s]+)',header)
            doc_id=doc_match.group(1) if doc_match else pdf.stem
            for number,page in enumerate(doc.pages,1):
                text=page.extract_text(layout=False) or ''
                pages.append({'document_id':doc_id,'source_file':pdf.relative_to(RAW).as_posix(),
                    'page':number,'text':text,'layout_text':page.extract_text(layout=True),
                    'tables':page.extract_tables(),'method':'pdfplumber; extracted content is not a validated knowledge claim'})
    dump(OUT/'documents.json',pages)
    dump(ROOT/'document_sample.json',[p for p in pages if p['source_file'].endswith('SOP_003_MaintenanceRules.pdf')])
    save(pd.DataFrame([{'file':p['source_file'],'page':p['page'],'chars':len(p['text']),'tables':len(p['tables'])} for p in pages]),REPORT/'document_checks.csv')
    dump(REPORT/'environment.json',{m:importlib.metadata.version(m) for m in ['pandas','pypdf','pdfplumber','pyshacl','rdflib','nbformat','nbclient','ipykernel']})
    return summary

if __name__=='__main__':
    print(json.dumps(prepare(),ensure_ascii=True,indent=2))
