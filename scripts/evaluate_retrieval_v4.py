"""V4 retrieval ablation: only dense, then only typed candidate selection changes."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'scripts'))
from imaks_kg.rag import vector as v, comparison as c, retrieval_v3 as r3, retrieval_v4 as r4
from evaluate_agent_v3_quality import load_key_environment,questions,BENCH
PROFILES=('bm25_v3','hybrid_v3','hybrid_typed_v4')


def generate(out):
 load_key_environment();out.mkdir(parents=True,exist_ok=False)
 if not (r3.ROW_INDEX/'manifest.json').exists():
  r3.build_row_index()
 rows=r3.row_corpus();graph=c.load_graph()
 for q in questions():
  dense=r3.dense_ranking(q['question'],rows)
  for profile in PROFILES:
   if profile=='hybrid_typed_v4':result=r4.retrieve(q['question'],use_dense=True,dense=dense)
   else:result=r3.build_context('graph_v3',q['question'],rows,dense if profile=='hybrid_v3' else None,graph)
   v.write(out/profile/(q['id']+'.json'),result)
  print(q['id']+' retrieved all ablations',flush=True)
 files={str(p.relative_to(out)):v.digest(p.read_bytes()) for p in out.rglob('*.json')}
 v.write(out/'seal.json',{'profiles':PROFILES,'files':files,'private_loaded':False,'row_index_manifest_sha256':v.digest((r3.ROW_INDEX/'manifest.json').read_bytes()),
  'code':r4.retrieval_lock(True),'one_factor_steps':['bm25_v3 -> hybrid_v3: dense only','hybrid_v3 -> hybrid_typed_v4: typed candidates only']})
 print('Retrieval ablation sealed',flush=True)


def grade(out):
 seal=v.read(out/'seal.json')
 for name,digest in seal['files'].items():
  if v.digest((out/name).read_bytes())!=digest:raise ValueError('Seal mismatch')
 keypath=ROOT/'evaluation/benchmark_graph_v3_20261028/answer_key_PRIVATE.json'
 lock=v.read(BENCH/'lock.json')
 if v.digest(keypath.read_bytes())!=lock['hashes'][keypath.relative_to(ROOT).as_posix()]:raise ValueError('Answer key changed')
 key=v.read(keypath)['questions'];report={}
 for profile in PROFILES:
  found=needed=complete=0;perq={};tokens=[]
  for item in key:
   result=v.read(out/profile/(item['id']+'.json'));selected=set(result['selected_ids'])
   hits=[cid for cid in item['evidence'] if cid in selected]
   found+=len(hits);needed+=len(item['evidence']);complete+=len(hits)==len(item['evidence']);tokens.append(result['context_tokens'])
   perq[item['id']]={'found':len(hits),'needed':len(item['evidence']),'missing':sorted(set(item['evidence'])-set(hits))}
  report[profile]={'found':found,'needed':needed,'recall':found/needed,'complete_questions':complete,'mean_context_tokens':sum(tokens)/len(tokens),'per_question':perq}
 v.write(out/'grade_summary.json',report)
 print(json.dumps({k:{p:x for p,x in r.items() if p!='per_question'} for k,r in report.items()},ensure_ascii=False,indent=2))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['retrieve','grade']);p.add_argument('--out',required=True,type=Path)
 a=p.parse_args();(generate if a.action=='retrieve' else grade)(a.out)
