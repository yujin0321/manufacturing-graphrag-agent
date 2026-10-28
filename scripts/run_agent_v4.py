"""Run Agent v4.1 using a local .env key without printing secrets."""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from imaks_kg.rag import agent_v4_1 as agent_v4, retrieval_v4_1 as retrieval_v4, vector as v


def load_local_key():
    if os.environ.get('OPENAI_API_KEY'):return
    path=ROOT/'.env'
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.strip().startswith('OPENAI_API_KEY='):
                os.environ['OPENAI_API_KEY']=line.split('=',1)[1].strip().strip('\"\'')
                break
    if not os.environ.get('OPENAI_API_KEY'):raise ValueError('Set OPENAI_API_KEY in the local .env or process environment; never paste it in chat')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question',required=True);parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--dense',action='store_true',help='Use the prebuilt row index; query embeddings may incur cost')
    parser.add_argument('--retrieve-only',action='store_true',help='Free BM25 document retrieval without generation')
    args=parser.parse_args()
    if args.retrieve_only:
        if args.dense:parser.error('--retrieve-only is BM25-only')
        args.run_dir.mkdir(parents=True,exist_ok=False)
        result=retrieval_v4.source_packet(retrieval_v4.retrieve(args.question));v.write(args.run_dir/'retrieval.json',result)
        print(json.dumps({'selected_ids':result['selected_ids'],'context_tokens':result['context_tokens']},ensure_ascii=False))
    else:
        load_local_key()
        result=agent_v4.answer(args.question,args.run_dir,use_dense=args.dense)
        print(json.dumps({'status':result['status'],'answer':result['answer']},ensure_ascii=False))
