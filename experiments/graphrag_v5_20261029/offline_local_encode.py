"""Strictly offline local embedding worker; no API key or model download."""
import os
from pathlib import Path
import hashlib
import json
import socket
import sys

os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['TOKENIZERS_PARALLELISM']='false'
os.environ.pop('OPENAI_API_KEY',None)
network_attempts=[]
def denied(*args,**kwargs):
    network_attempts.append('blocked');raise RuntimeError('Network is disabled for this experiment')
socket.create_connection=denied
socket.socket.connect=denied

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent.parent
OUT=ROOT/'runs/offline_budget_v1'

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(4)
    setup=json.loads((OUT/'public_inputs.json').read_text(encoding='utf-8'))
    model_path=Path(setup['local_model_path'])
    model=SentenceTransformer(str(model_path),local_files_only=True,device='cpu')
    maximum=min(200,model.max_seq_length-model.tokenizer.num_special_tokens_to_add(pair=False))
    print(json.dumps({'stage':'local_encoder_ready','path':str(model_path),'max_tokens':maximum},ensure_ascii=False),flush=True)
    records=setup['embedding_records'];segments=[];owners=[]
    for i,record in enumerate(records):
        ids=model.tokenizer.encode(record['embedding_text'],add_special_tokens=False,truncation=False)
        if not ids:raise ValueError('Empty local embedding text')
        start=0
        while start<len(ids):
            end=min(start+maximum,len(ids));text=model.tokenizer.decode(ids[start:end],skip_special_tokens=False)
            while len(model.tokenizer.encode(text,add_special_tokens=False))>maximum:
                end-=1;text=model.tokenizer.decode(ids[start:end],skip_special_tokens=False)
            segments.append(text);owners.append((i,end-start));start=end
    matrix=model.encode(segments,batch_size=16,normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
    pooled=np.zeros((len(records),matrix.shape[1]),dtype=np.float32)
    weights=np.zeros(len(records),dtype=np.float32)
    for embedding,(owner,weight) in zip(matrix,owners):pooled[owner]+=embedding*weight;weights[owner]+=weight
    pooled/=weights[:,None];pooled/=np.linalg.norm(pooled,axis=1,keepdims=True)
    if not np.isfinite(pooled).all():raise ValueError('Nonfinite local embedding')
    np.save(OUT/'local_embeddings.npy',pooled,allow_pickle=False)
    manifest={'encoder_path':str(model_path),'encoder_name':'jhgan/ko-sroberta-multitask',
        'dimension':int(pooled.shape[1]),'segments':len(segments),'records':len(records),
        'record_ids':[r['id'] for r in records],'embedding_sha256':digest(OUT/'local_embeddings.npy'),
        'public_inputs_sha256':digest(OUT/'public_inputs.json'),
        'model_file_sha256':{p.relative_to(model_path).as_posix():digest(p) for p in model_path.rglob('*') if p.is_file()},
        'network_attempts':len(network_attempts),'new_api_calls':0,
        'query_expansion':'Public station/sensor aliases shared by every retrieval system',
        'long_text_policy':'Token windows <=200; length-weighted normalized pooling; no silent truncation',
        'limit':'Different encoder from historical API runs; report separately. English/Korean alignment is not independently validated.'}
    (OUT/'local_embedding_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ['model_file_sha256','record_ids']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
