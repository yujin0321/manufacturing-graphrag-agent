"""Offline evaluation phase only, after sealing predictions. No detector tuning."""
import csv
from datetime import datetime,timedelta
from imaks_kg.rag import vector as v
from imaks_kg.detection.rules import OUT,INPUT,split


def main():
    seal=v.read(OUT/'complete.json')
    for name,h in seal.items():
        if v.digest((OUT/name).read_bytes())!=h:raise ValueError('Detector output changed')
    profile=v.read(v.REPO_ROOT/'preprocessed/sensors/profile.json')
    rel='evaluation/row_labels.csv'
    if v.digest((v.REPO_ROOT/rel).read_bytes())!=profile['output_sha256'][rel]:raise ValueError('Labels changed')
    def read(path):
        with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
    rows=read(v.REPO_ROOT/INPUT);labels=read(v.REPO_ROOT/rel)
    gold={(r['sensor_id'],r['timestamp']):r['anomaly_label']!='NORMAL' for r in labels}
    observed={(r['sensor_id'],r['timestamp']) for r in rows}
    if len(gold)!=len(labels) or observed!=set(gold):raise ValueError('Label keys mismatch')
    positives=set()
    for e in v.read(OUT/'events.json'):
        if e['kind']!='metadata_threshold':continue
        t=datetime.fromisoformat(e['trigger_at']);end=datetime.fromisoformat(e['last_positive_at'])
        while t<=end:
            positives.add((e['sensor_id'],t.isoformat()));t+=timedelta(seconds=30)
    if not positives<=observed:raise ValueError('Prediction key mismatch')
    metrics={}
    for s in ['train','validation','test']:
        keys=[k for k in observed if split(k[1])==s]
        tp=sum(k in positives and gold[k] for k in keys);fp=sum(k in positives and not gold[k] for k in keys)
        fn=sum(k not in positives and gold[k] for k in keys)
        metrics[s]={'rows':len(keys),'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else 0,
                    'recall':tp/(tp+fn) if tp+fn else 0,'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0}
    out=v.REPO_ROOT/'evaluation/rule_detector_20261026';out.mkdir(exist_ok=False)
    v.write(out/'baseline_row_metrics.json',{'scope':'metadata warning threshold baseline only; not document-rule coverage or event F1',
        'development_retest':True,'labels_sha256':v.digest((v.REPO_ROOT/rel).read_bytes()),
        'predictions_seal_sha256':v.digest((OUT/'complete.json').read_bytes()),'metrics':metrics})
    print(__import__('json').dumps(metrics,indent=2))


if __name__=='__main__':main()
