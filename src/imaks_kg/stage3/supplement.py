"""Deterministic SOP-002 knowledge supplement; never reads evaluation references.

This is not LLM output and must never be folded into the frozen LLM score.
Station context comes from document headings and explicit continuation metadata.
"""
from decimal import Decimal
import re

from .common import DOCS, OUT, catalog, read_jsonl, write_json, write_jsonl
from .extract import validate_rules


def supplement():
    chunks = {c['table_id']: c for c in read_jsonl(DOCS/'chunks.jsonl') if c['doc_id']=='SOP-002' and c['kind']=='table'}
    pages = {p['page']: p['text_normalized'] for p in read_jsonl(DOCS/'pages.jsonl') if p['doc_id']=='SOP-002'}
    tables = sorted([t for t in read_jsonl(DOCS/'tables.jsonl') if t['doc_id']=='SOP-002'], key=lambda t:(t['page'],t['bbox'][1]))
    headings = {page:list(re.finditer(r'(?m)^([A-Z0-9_]+) Thresholds\s*$', text)) for page,text in pages.items()}
    ids = catalog()
    station_by_table, rows, mapping = {}, [], []
    for t in tables:
        c=chunks[t['table_id']]
        cells=t['rows_normalized']
        if cells[0][0]=='Type':
            for ri,row in enumerate(cells[1:],1):
                evidence=[]
                for ci in (0,1,2,3):
                    evidence.append({'supports':['condition'], 'chunk_id':c['chunk_id'], 'source_quote':row[ci],
                                     'table_id':t['table_id'], 'table_row':ri, 'table_col':ci})
                rows.append({'prediction_id':'baseline:SOP-002:type:'+row[0], 'doc_id':'SOP-002', 'class':'ThresholdRule',
                             'condition':row[0]+': '+row[1]+'; detection criterion: '+row[2], 'action':'',
                             'severity':'', 'sensors':[], 'action_targets':[], 'printed_rule_id':None,
                             'ontology_target':row[3], 'evidence':evidence, 'extraction_method':'deterministic_source_table'})
            continue
        if t.get('continued_from'):
            station=station_by_table.get(t['continued_from'])
            data_rows=list(enumerate(cells))
        else:
            prior=[h for h in headings[t['page']] if h.start()<=c['char_start']]
            station=prior[-1].group(1) if prior else None
            if cells[0][0]!='Sensor':
                raise ValueError('Unknown threshold table header')
            data_rows=list(enumerate(cells[1:],1))
        if station not in ids['stations']:
            raise ValueError('Cannot derive Station from document: '+t['table_id'])
        station_by_table[t['table_id']]=station
        for ri,row in data_rows:
            sensor=station+'_'+row[0]
            if sensor not in ids['sensors'] or len(row)!=8:
                raise ValueError('Unknown sensor/row layout: '+sensor)
            numeric={'critLo':row[2], 'warnLo':row[3], 'nominal':row[4].split('±')[0].strip(), 'warnHi':row[5], 'critHi':row[6]}
            values=[Decimal(numeric[k]) for k in ('critLo','warnLo','nominal','warnHi','critHi')]
            if values!=sorted(values) or len(set(values))!=5:
                raise ValueError('Invalid threshold ordering: '+sensor)
            evidence=[]
            for ci,text in enumerate(row):
                if text:
                    evidence.append({'supports':['action'] if ci==7 else ['condition','sensors'],
                                     'chunk_id':c['chunk_id'], 'source_quote':text,
                                     'table_id':t['table_id'], 'table_row':ri, 'table_col':ci})
            record={'prediction_id':'baseline:SOP-002:'+sensor, 'doc_id':'SOP-002', 'class':'ThresholdRule',
                    'condition':sensor+': '+', '.join(k+'='+numeric[k] for k in ('critLo','warnLo','nominal','warnHi','critHi'))+' '+row[1],
                    'action':row[7], 'severity':'CRITICAL', 'sensors':[sensor], 'action_targets':[],
                    'printed_rule_id':None, 'unit':row[1], 'numeric':numeric, 'evidence':evidence,
                    'extraction_method':'deterministic_source_table'}
            rows.append(record)
            mapping.append({'sensor':sensor,'station':station,'table_id':t['table_id'],'row':ri,'continued_from':t.get('continued_from')})
    validate_rules(rows)
    write_jsonl(OUT/'sop002_source_supplement.jsonl',rows)
    write_json(OUT/'sop002_source_supplement_summary.json',{'method':'deterministic_source_table', 'not_llm_predictions':True,
        'rules':len(rows), 'threshold_sensor_rows':len(mapping), 'anomaly_definition_rows':len(rows)-len(mapping),
        'source':'SOP-002 only; catalog IDs for verification', 'ground_truth_read':False, 'mapping':mapping})
    print('Source supplement:',len(rows),'rules, sensor rows:',len(mapping))


if __name__=='__main__':
    supplement()
