"""Small, auditable dense Vector RAG. No local model or vector DB required."""
import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import tiktoken
from imaks_kg.settings import REPO_ROOT

# Small tokenizer vocabularies, not model weights; keep cache inside workspace.
os.environ.setdefault('TIKTOKEN_CACHE_DIR', str(REPO_ROOT / 'kg_build/tokenizer_cache'))

CONFIG = REPO_ROOT / 'docs/vector_rag_v1/config.json'
LOCK = REPO_ROOT / 'docs/benchmark_yewon_v2_20261023/scoring_lock_v1.json'
SOURCE = REPO_ROOT / 'preprocessed/documents/chunks.jsonl'
DEFAULT_INDEX = REPO_ROOT / 'kg_build/vector_rag_v1'
DOCS = {'SOP-001','SOP-002','SOP-003','SOP-004','DS-ELEC-3300','DS-MECH-4400','DS-THERM-2200'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_bytes(encoded(obj)+b'\n')
    tmp.replace(path)


def source_records():
    # Deliberately no directory scan, benchmark loader or evaluation import.
    lock = read(LOCK)
    expected = lock['hashes']['preprocessed/documents/chunks.jsonl']
    raw = SOURCE.read_bytes()
    if digest(raw) != expected:
        raise ValueError('Frozen source changed')
    records = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    if {r['doc_id'] for r in records} != DOCS:
        raise ValueError('Unexpected document allowlist')
    if len({r['chunk_id'] for r in records}) != len(records):
        raise ValueError('Duplicate chunk IDs')
    for r in records:
        if not r['text'].strip() or digest(r['text'].encode()) != r['text_sha256']:
            raise ValueError('Invalid source text/hash')
    return records, expected


def embedding_text(r):
    return f"{r['doc_id']} | {r.get('section') or ''}\n{r['text']}"


def api_call(resource, payload, cache):
    """Fixed official host, no retries, resumable raw responses, no key logging."""
    if resource not in {'embeddings', 'chat/completions'}:
        raise ValueError('Unsupported API resource')
    cache = Path(cache)
    key = digest(encoded({'resource':resource,'payload':payload}))
    raw_path = cache / (key+'.response.json')
    if raw_path.exists():
        return read(raw_path), {'cache_hit':True,'request_sha256':key,'seconds':0}
    token = os.environ.get('OPENAI_API_KEY')
    if not token:
        raise ValueError('Set OPENAI_API_KEY in the local environment; never paste it into chat')
    cache.mkdir(parents=True, exist_ok=True)
    attempt = cache / (key+'.attempt.json')
    # A transport failure can still have incurred cost. Never silently resend it.
    with attempt.open('x', encoding='utf-8') as f:
        json.dump({'started_at':datetime.now(timezone.utc).isoformat(),'resource':resource}, f)
    write(cache/(key+'.request.json'), payload)
    req = Request('https://api.openai.com/v1/'+resource, data=encoded(payload),
                  headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    started = time.perf_counter()
    try:
        with urlopen(req, timeout=180) as response:
            raw = json.load(response)
    except HTTPError as exc:
        write(cache/(key+'.error.json'), {'http_status':exc.code,'retry':False})
        raise RuntimeError(f'OpenAI HTTP {exc.code}; no retry. Inspect account/model access and attempt log.') from None
    except (URLError, TimeoutError):
        write(cache/(key+'.error.json'), {'transport_error':True,'retry':False})
        raise RuntimeError('API transport failed; unresolved attempt retained, no automatic retry') from None
    write(raw_path, raw)
    return raw, {'cache_hit':False,'request_sha256':key,'seconds':time.perf_counter()-started}


def normalized(values, rows, dimensions):
    matrix = np.asarray(values, dtype=np.float32)
    if matrix.shape != (rows, dimensions) or not np.isfinite(matrix).all():
        raise ValueError('Invalid embedding shape/nonfinite vector')
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError('Zero embedding')
    return matrix / norms


def embed(texts, config, cache, call=api_call):
    enc = tiktoken.get_encoding('cl100k_base')
    counts = [len(enc.encode(t, disallowed_special=())) for t in texts]
    if not texts or max(counts) > 8191 or sum(counts) > 250000:
        raise ValueError('Embedding input exceeds bounded request size')
    payload = {'model':config['embedding_model'],'input':texts,
               'dimensions':config['dimensions'],'encoding_format':'float'}
    raw, transport = call('embeddings', payload, cache)
    data = sorted(raw['data'], key=lambda d:d['index'])
    if [d['index'] for d in data] != list(range(len(texts))):
        raise ValueError('Missing/duplicate embedding response indices')
    if raw.get('model') != config['embedding_model']:
        raise ValueError('Unexpected embedding model; no fallback')
    return normalized([d['embedding'] for d in data],len(texts),config['dimensions']), {
        **transport,'usage':raw.get('usage',{}),'returned_model':raw.get('model'),'input_tokens_local':sum(counts)}


def prepare(index=DEFAULT_INDEX):
    index=Path(index); config=read(CONFIG); records, source_sha=source_records()
    corpus=[{k:r.get(k) for k in ['chunk_id','doc_id','page','section','table_id','kind','text','text_sha256','source_file_sha256']} for r in records]
    plan={'source_sha256':source_sha,'config':config,'corpus_sha256':digest(encoded(corpus)),
          'instruction_sha256':digest((REPO_ROOT/'docs/vector_rag_v1/answer_instructions.txt').read_bytes()),
          'chunks':len(corpus),'documents':sorted(DOCS),'embedding_tokens':sum(len(tiktoken.get_encoding('cl100k_base').encode(embedding_text(r),disallowed_special=())) for r in corpus),
          'dense_float32_bytes':len(corpus)*config['dimensions']*4,
          'source_only':True,'evaluation_answers_loaded':False}
    if (index/'plan.json').exists() and read(index/'plan.json') != plan:
        raise ValueError('Changed corpus/config; use a new index directory')
    write(index/'corpus.json',corpus); write(index/'plan.json',plan)
    return plan


def build(index=DEFAULT_INDEX):
    index=Path(index);plan=prepare(index)
    if (index/'index_manifest.json').exists():
        load_index(index)
        return read(index/'index_manifest.json')
    corpus=read(index/'corpus.json')
    vectors,api=embed([embedding_text(r) for r in corpus],plan['config'],index/'api_cache')
    np.save(index/'vectors.npy', vectors, allow_pickle=False)
    manifest={**plan,'vectors_sha256':digest((index/'vectors.npy').read_bytes()),
              'built_at':datetime.now(timezone.utc).isoformat(),'api':api,
              'ranking':'normalized cosine descending, ties by chunk_id; no keyword reranking'}
    write(index/'index_manifest.json',manifest)
    return manifest


def load_index(index):
    index=Path(index);m=read(index/'index_manifest.json');corpus=read(index/'corpus.json')
    _,source_sha=source_records()
    if source_sha != m['source_sha256'] or m['config'] != read(CONFIG):
        raise ValueError('Index no longer matches fixed source/config')
    if m['instruction_sha256'] != digest((REPO_ROOT/'docs/vector_rag_v1/answer_instructions.txt').read_bytes()):
        raise ValueError('Answer instructions changed; use a new version')
    if digest(encoded(corpus)) != m['corpus_sha256'] or digest((index/'vectors.npy').read_bytes()) != m['vectors_sha256']:
        raise ValueError('Index artifact integrity failure')
    vectors=np.load(index/'vectors.npy',allow_pickle=False)
    vectors=normalized(vectors,len(corpus),m['config']['dimensions'])
    return corpus,vectors,m


def retrieve(corpus,vectors,query_vector,k):
    q=normalized([query_vector],1,vectors.shape[1])[0]
    scores=vectors@q
    order=sorted(range(len(corpus)),key=lambda i:(-float(scores[i]),corpus[i]['chunk_id']))[:k]
    return [dict(corpus[i],score=float(scores[i])) for i in order]


def context(hits,config):
    enc=tiktoken.get_encoding(config['context_encoding'])
    selected=[];blocks=[];skipped=[]
    for hit in hits:
        block=f"[{hit['chunk_id']}] {hit['doc_id']} p.{hit['page']} | {hit.get('section') or ''}\n{hit['text']}"
        proposed='\n\n'.join(blocks+[block])
        if len(enc.encode(proposed,disallowed_special=()))>config['context_token_budget']:
            skipped.append(hit['chunk_id']);continue
        blocks.append(block);selected.append(hit)
    text='\n\n'.join(blocks)
    return text,selected,skipped,len(enc.encode(text,disallowed_special=()))


def answer(question,index=DEFAULT_INDEX,run_dir=None,call=api_call):
    if not isinstance(question,str) or not question.strip() or len(question.encode())>8000:
        raise ValueError('Expected a nonempty, bounded question')
    index=Path(index);corpus,vectors,m=load_index(index);cfg=m['config']
    if run_dir is None:raise ValueError('A fresh explicit run directory is required')
    run_dir=Path(run_dir);run_dir.mkdir(parents=True,exist_ok=False)
    write(run_dir/'input.json',{'question':question,'config':cfg,'index_manifest_sha256':digest(encoded(m))})
    started=time.perf_counter()
    try:
        q,embedding_api=embed([question],cfg,index/'query_cache',call)
        hits=retrieve(corpus,vectors,q[0],cfg['top_k'])
        text,selected,skipped,tokens=context(hits,cfg)
        if not selected:raise ValueError('No complete evidence chunk fits the budget')
        retrieval={'ranked_hits':hits,'selected_ids':[r['chunk_id'] for r in selected],
                   'skipped_for_budget':skipped,'context':text,'context_tokens':tokens,
                   'context_encoding':cfg['context_encoding'],'embedding_api':embedding_api}
        write(run_dir/'retrieval.json',retrieval)
        common=(REPO_ROOT/'docs/vector_rag_v1/answer_instructions.txt').read_text(encoding='utf-8')
        payload={'model':cfg['generation_model'],'store':False,'max_completion_tokens':cfg['max_completion_tokens'],
                 'messages':[{'role':'system','content':common},{'role':'user','content':json.dumps({'question':question,'untrusted_reference_documents':text},ensure_ascii=False)}]}
        raw,api=call('chat/completions',payload,run_dir/'api')
        choice=raw['choices'][0];message=choice['message']
        if choice.get('finish_reason')!='stop' or not message.get('content') or message.get('refusal'):
            raise ValueError('Incomplete/empty/refused generation; raw response retained')
        result={'status':'complete','system':'VectorRAG','question':question,'answer':message['content'],
                'requested_model':cfg['generation_model'],'returned_model':raw.get('model'),
                'model_id_differs':raw.get('model')!=cfg['generation_model'],
                'usage':raw.get('usage',{}),'generation_api':api,'seconds':time.perf_counter()-started,
                'selected_ids':retrieval['selected_ids'],'context_tokens':tokens,
                'instruction_sha256':digest(common.encode()),'config':cfg,
                'grading_performed':False}
        write(run_dir/'answer.json',result)
        return result
    except Exception as exc:
        write(run_dir/'failure.json',{'status':'failed','error_type':type(exc).__name__,
                                     'seconds':time.perf_counter()-started,'grading_performed':False})
        raise


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','build','inspect','ask'])
    p.add_argument('--index',type=Path,default=DEFAULT_INDEX)
    p.add_argument('--question');p.add_argument('--run-dir',type=Path)
    a=p.parse_args()
    if a.action=='prepare': result=prepare(a.index)
    elif a.action=='build':result=build(a.index)
    elif a.action=='inspect':_,_,result=load_index(a.index)
    else:result=answer(a.question,a.index,a.run_dir)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
