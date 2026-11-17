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


def make_replay(seed, minutes, warmup_minutes=0):
    if type(minutes) is not int or not 1<=minutes<=240:
        raise ValueError('Replay minutes must be between 1 and 240')
    if type(warmup_minutes) is not int or not 0<=warmup_minutes<=120:raise ValueError('Warmup minutes must be between 0 and 120')
    groups,_,profile=rules.read_inputs()
    cutoff=datetime.fromisoformat(v.read(team_runtime.store().run_dir/'params.json')['config']['train_end'])
    lower=max(cutoff,max(datetime.fromisoformat(rows[0]['timestamp']) for rows in groups.values()))+timedelta(minutes=warmup_minutes)
    upper=min(datetime.fromisoformat(rows[-1]['timestamp']) for rows in groups.values())-timedelta(minutes=minutes)
    slots=int((upper-lower).total_seconds()//30)
    if slots<0:raise ValueError('No common interval after baseline availability')
    start=lower+timedelta(seconds=30*random.Random(seed).randrange(slots+1))
    end=start+timedelta(minutes=minutes)
    context_start=start-timedelta(minutes=warmup_minutes)
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=rules.FIELDS,lineterminator='\n');writer.writeheader()
    count=0
    for sid in sorted(groups):
        for row in groups[sid]:
            if context_start.isoformat()<=row['timestamp']<=end.isoformat():writer.writerow(row);count+=1
    raw=stream.getvalue().encode()
    if count>a.MAX_ROWS or len(raw)>a.MAX_BYTES:raise ValueError('Replay exceeds upload limits; use a shorter duration')
    folder=ROOT/'kg_build/sensor_replay_inputs';folder.mkdir(parents=True,exist_ok=True)
    suffix=f'_warmup{warmup_minutes}m' if warmup_minutes else ''
    path=folder/f'replay_seed{seed}_{minutes}m{suffix}.csv'
    if path.exists() and path.read_bytes()!=raw:raise ValueError('Refusing to replace a different replay file')
    path.write_bytes(raw)
    recipe={'input_kind':'historical_replay','selection':'uniform start over common 30-second grid after baseline availability',
            'seed':seed,'minutes':minutes,'warmup_minutes':warmup_minutes,'context_start':context_start.isoformat(),
            'start':start.isoformat(),'end':end.isoformat(),'analysis_start':start.isoformat(),'analysis_end':end.isoformat(),'sensors':sorted(groups),
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
    replay.add_argument('--warmup-minutes',type=int,default=0)
    analyze=modes.add_parser('analyze');analyze.add_argument('--input',type=Path,required=True)
    analyze.add_argument('--input-kind',choices=a.KINDS,default='uploaded_sensor_csv')
    analyze.add_argument('--analysis-start');analyze.add_argument('--analysis-end')
    export=modes.add_parser('export');export.add_argument('--analysis-id',required=True);export.add_argument('--output',type=Path,required=True)
    restore=modes.add_parser('restore');restore.add_argument('--input',type=Path,required=True)
    args=parser.parse_args()
    if args.mode=='replay':result=make_replay(args.seed,args.minutes,args.warmup_minutes)
    elif args.mode=='export':
        raw=a.AnalysisService().export_bundle(args.analysis_id)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('xb') as stream:stream.write(raw)
        result={'file':str(args.output),'bytes':len(raw),'sha256':v.digest(raw),'private_local_package':True,'new_api_calls':0}
    else:
        from imaks_kg.rag.analysis_archive import MAX_ZIP_BYTES
        limit=MAX_ZIP_BYTES if args.mode=='restore' else a.MAX_BYTES
        if args.input.stat().st_size>limit:raise ValueError('Input exceeds size limit')
        raw=args.input.read_bytes();service=a.AnalysisService()
        if args.mode=='restore':result=service.import_bundle(raw)
        else:result=service.create(raw,args.input_kind,analysis_start=args.analysis_start,analysis_end=args.analysis_end)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
