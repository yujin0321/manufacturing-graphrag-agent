"""Make a labelled historical replay CSV, or analyze an input locally without LLM calls."""
import argparse
import csv
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import random
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from imaks_kg.detection import rules
from imaks_kg.rag import sensor_analysis as a, team_runtime, vector as v


def make_replay(seed, minutes):
    if type(minutes) is not int or not 1<=minutes<=240:
        raise ValueError('Replay minutes must be between 1 and 240')
    groups,_,profile=rules.read_inputs()
    cutoff=datetime.fromisoformat(v.read(team_runtime.store().run_dir/'params.json')['config']['train_end'])
    lower=max(cutoff,max(datetime.fromisoformat(rows[0]['timestamp']) for rows in groups.values()))
    upper=min(datetime.fromisoformat(rows[-1]['timestamp']) for rows in groups.values())-timedelta(minutes=minutes)
    slots=int((upper-lower).total_seconds()//30)
    if slots<0:raise ValueError('No common interval after baseline availability')
    start=lower+timedelta(seconds=30*random.Random(seed).randrange(slots+1))
    end=start+timedelta(minutes=minutes)
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=rules.FIELDS,lineterminator='\n');writer.writeheader()
    count=0
    for sid in sorted(groups):
        for row in groups[sid]:
            if start.isoformat()<=row['timestamp']<=end.isoformat():writer.writerow(row);count+=1
    raw=stream.getvalue().encode()
    if count>a.MAX_ROWS or len(raw)>a.MAX_BYTES:raise ValueError('Replay exceeds upload limits; use a shorter duration')
    folder=ROOT/'kg_build/sensor_replay_inputs';folder.mkdir(parents=True,exist_ok=True)
    path=folder/f'replay_seed{seed}_{minutes}m.csv'
    if path.exists() and path.read_bytes()!=raw:raise ValueError('Refusing to replace a different replay file')
    path.write_bytes(raw)
    recipe={'input_kind':'historical_replay','selection':'uniform start over common 30-second grid after baseline availability',
            'seed':seed,'minutes':minutes,'start':start.isoformat(),'end':end.isoformat(),'sensors':sorted(groups),
            'rows':count,'source_file':rules.INPUT,'source_sha256':profile['output_sha256'][rules.INPUT],
            'csv_file':path.relative_to(ROOT).as_posix(),'csv_sha256':v.digest(raw),
            'gold_loaded':False,'event_results_used_to_choose_window':False,'new_api_calls':0,
            'scope':'historical replay, not a held-out accuracy evaluation; may contain no detected incident'}
    v.write(path.with_suffix('.json'),recipe)
    return recipe


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_subparsers(dest='mode',required=True)
    replay=modes.add_parser('replay');replay.add_argument('--seed',type=int,default=20261115);replay.add_argument('--minutes',type=int,default=120)
    analyze=modes.add_parser('analyze');analyze.add_argument('--input',type=Path,required=True)
    analyze.add_argument('--input-kind',choices=a.KINDS,default='uploaded_sensor_csv')
    args=parser.parse_args()
    if args.mode=='replay':result=make_replay(args.seed,args.minutes)
    else:result=a.AnalysisService().create(args.input.read_bytes(),args.input_kind)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
