"""New-question API pipeline using the frozen GraphRAG v2 retrieval policy."""
import argparse
import json
import time
from pathlib import Path
from . import vector as v, graph_v2 as g, comparison as c

LIVE_ROOT = v.REPO_ROOT/'kg_build/graphrag_live'


def answer(question, run_dir, call=v.api_call):
    if not isinstance(question, str) or not question.strip() or len(question.encode()) > 8000:
        raise ValueError('Expected a nonempty question of at most 8000 UTF-8 bytes')
    run = Path(run_dir)
    run.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    v.write(run/'input.json', {'question':question, 'system':'GraphRAG_v2_live'})
    try:
        corpus, matrix, manifest = v.load_index(v.DEFAULT_INDEX)
        graph = c.load_graph()
        cfg = manifest['config']
        common = (v.REPO_ROOT/'docs/vector_rag_v1/answer_instructions.txt').read_text(encoding='utf-8')
        policy = v.read(g.POLICY_PATH)
        v.write(run/'run_lock.json', {
            'generation_config':cfg, 'retrieval_policy':policy,
            'index_manifest_sha256':v.digest(v.encoded(manifest)),
            'kg_sha256':v.digest((v.REPO_ROOT/c.KG_REL).read_bytes()),
            'instruction_sha256':v.digest(common.encode()),
            'code_hashes':{p:v.digest((v.REPO_ROOT/p).read_bytes()) for p in [
                'src/imaks_kg/rag/live.py','src/imaks_kg/rag/graph_v2.py',
                'src/imaks_kg/rag/vector.py','src/imaks_kg/rag/comparison.py']},
            'evaluation_run':False, 'automatic_retries':False})

        def embedding_call(resource, payload, cache):
            # Reuse benchmark caches read-only. New questions use a separate cache.
            try:
                return g.cached_embeddings(resource,payload,v.DEFAULT_INDEX/'query_cache')
            except FileNotFoundError:
                return call(resource,payload,cache)

        query, embedding_api = v.embed([question],cfg,LIVE_ROOT/'query_cache',embedding_call)
        v.write(run/'embedding.json',embedding_api)
        dense = v.retrieve(corpus,matrix,query[0],len(corpus))
        retrieval = g.context(question,corpus,dense,graph,policy)
        retrieval['embedding_api'] = embedding_api
        v.write(run/'retrieval.json',retrieval)
        if not retrieval['selected_ids']:
            raise ValueError('No source chunk fits the retrieval budget')
        payload = {'model':cfg['generation_model'], 'store':False,
                   'max_completion_tokens':cfg['max_completion_tokens'],
                   'messages':[{'role':'system','content':common},
                               {'role':'user','content':json.dumps({'question':question,
                                 'untrusted_reference_documents':retrieval['context']},ensure_ascii=False)}]}
        raw, api = call('chat/completions',payload,run/'api')
        choice=raw['choices'][0];msg=choice['message']
        if choice.get('finish_reason')!='stop' or not msg.get('content') or msg.get('refusal'):
            raise ValueError('Incomplete, empty or refused generation; raw response retained')
        if raw.get('model')!=cfg['generation_model']:
            raise ValueError('Returned model differs; no fallback')
        by_id={r['chunk_id']:r for r in corpus}
        result={'status':'complete','system':'GraphRAG_v2_live','question':question,
                'answer':msg['content'],'requested_model':cfg['generation_model'],
                'returned_model':raw['model'],'usage':raw.get('usage',{}),
                'generation_api':api,'embedding_api':embedding_api,
                'seconds':time.perf_counter()-started,'context_tokens':retrieval['context_tokens'],
                'selected_ids':retrieval['selected_ids'],
                'retrieved_sources':[by_id[cid] for cid in retrieval['selected_ids']],
                'source_note':'Retrieved sources are not a claim that every source was cited or verified.',
                'warnings':['정적 문서 기반 답변이며 실제 설비 상태를 확인하지 않습니다.',
                            '검색 근거의 충분성·문서 충돌을 자동 판정한 결과가 아닙니다.'],
                'uncovered_explicit_documents':retrieval['uncovered_explicit_documents'],
                'grading_performed':False}
        v.write(run/'answer.json',result)
        return result
    except Exception as exc:
        # Do not log exception strings, which may contain network credentials.
        v.write(run/'failure.json',{'status':'failed','error_type':type(exc).__name__,
                                  'automatic_retry':False,'seconds':time.perf_counter()-started})
        raise


def main():
    p=argparse.ArgumentParser(description='Paid API: new question -> embedding -> GraphRAG -> answer')
    p.add_argument('--question',required=True)
    p.add_argument('--run-dir',required=True,type=Path)
    a=p.parse_args();result=answer(a.question,a.run_dir)
    print(json.dumps({'answer':result['answer'],'run_dir':str(a.run_dir.resolve()),
                      'usage':result['usage'],'embedding_api':result['embedding_api']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
