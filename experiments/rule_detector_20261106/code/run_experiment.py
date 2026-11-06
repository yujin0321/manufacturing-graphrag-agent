"""All three runs finish and are sealed before a separate evaluator reads labels."""
from pathlib import Path
import argparse,json
import detector as d
from prepare import upstream

def run(root):
    root=Path(root);lock=d.read(root/'protocol_lock.json')
    for name,h in lock['inputs'].items():assert d.digest(root/'inputs'/name)==h
    for name,h in lock['rules'].items():assert d.digest(root/name)==h
    for name,h in lock['code'].items():assert d.digest(root/'code'/name)==h
    groups,missing=d.read_observations(root/'inputs/observations.csv')
    old=upstream(root/'inputs/upstream_kg_rules.py');rs=d.read(root/'rules_baseline.json')['rules']
    out=root/'runs/baseline_v2';out.mkdir(parents=True,exist_ok=False);events=[]
    for r in rs:
        clean=[{k:x[k] for k in d.FIELDS} for x in groups[r['sensor_id']]]
        events.extend(old['scan'](clean,r))
    d.write(out/'events.json',events);d.write(out/'summary.json',{'events':len(events),'rules':74,'gold_loaded':False,'scanner':'byte-preserved upstream AST function; unmodified logic'})
    d.write(out/'seal.json',{p.name:d.digest(p) for p in out.glob('*.json')})
    d.run(root/'inputs/observations.csv',root/'rules_baseline.json',root/'runs/two_point_only')
    d.run(root/'inputs/observations.csv',root/'rules_improved.json',root/'runs/improved')
    d.write(root/'generation_complete.json',{'gold_loaded':False,'runs':{n:d.digest(root/'runs'/n/'seal.json') for n in ['baseline_v2','two_point_only','improved']}})
    print(json.dumps({n:d.read(root/'runs'/n/'summary.json')['events'] for n in ['baseline_v2','two_point_only','improved']}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);run(p.parse_args().root)
