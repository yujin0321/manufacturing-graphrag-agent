"""Replay from the supplied frozen inputs into a new folder. No API calls."""
import argparse,shutil,subprocess,sys
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--labels',help='Original timeseries_annotated.csv; evaluator only')
    a=p.parse_args();source=Path(__file__).resolve().parent;out=Path(a.output).resolve()
    if out.exists():raise ValueError('Use a new output folder; never overwrite the published run')
    out.mkdir(parents=True)
    for folder in ['code','inputs']:shutil.copytree(source/folder,out/folder,ignore=shutil.ignore_patterns('__pycache__'))
    for name in ['rules_baseline.json','rules_improved.json','protocol_lock.json','source_audit.json']:
        shutil.copy2(source/name,out/name)
    subprocess.run([sys.executable,str(out/'code/run_experiment.py'),'--root',str(out)],check=True)
    if a.labels:subprocess.run([sys.executable,str(out/'code/evaluate.py'),'--root',str(out),'--labels',str(Path(a.labels).resolve())],check=True)
    else:print('Predictions reproduced. Labels were not opened; evaluation requires --labels.')

if __name__=='__main__':main()
