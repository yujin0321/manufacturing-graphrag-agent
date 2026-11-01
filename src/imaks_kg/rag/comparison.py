"""Closed-book LLM and bounded, provenance-linked v2 GraphRAG runners."""
import argparse
import json
import re
import time
from pathlib import Path
from rdflib import Graph, Namespace, RDF, URIRef
import tiktoken
from . import vector as v

IM = Namespace('https://example.org/imaks/v1#')
KG_REL = 'artifacts/stage6_final_20261016/inputs/kg_build/openai_sol_v2_20261016/graph/candidate.ttl'
POLICY = {'version':'comparison-v1-20261024','graph_hops':2,'max_nodes':24,'max_seed_nodes':6,
          'graph_token_budget':1500,'vector_seed_chunks':8,
          'traverse_predicates':['appliesToSensor','actionTarget','hasSensor','feedsInto'],
          'seed_structure_used':True,'document_retrieval_used':True}


def load_graph():
    path=v.REPO_ROOT/KG_REL
    if v.digest(path.read_bytes())!=v.read(v.LOCK)['hashes'][KG_REL]:
        raise ValueError('Frozen v2 KG changed')
    return Graph().parse(path,format='turtle')


def source_links(g,corpus):
    links={}
    for node in set(g.subjects(IM.hasProvenance,None)):
        found=set()
        for p in g.objects(node,IM.hasProvenance):
            if str(g.value(p,IM.sourceKind))!='document':continue
            table=str(g.value(p,IM.tableId) or '')
            sha=str(g.value(p,IM.fileSha256) or '')
            quote=' '.join(str(g.value(p,IM.sourceQuote) or '').split())
            for c in corpus:
                if c['source_file_sha256']!=sha:continue
                if (table and table==c['table_id']) or (quote and quote in ' '.join(c['text'].split())):
                    found.add(c['chunk_id'])
        links[node]=sorted(found)
    return links


def graph_context(question,hits,corpus,g,cfg):
    links=source_links(g,corpus)
    # Exact identifiers are generic entity linking; no question IDs or answer keys.
    exact=[]
    for node,identifier in g.subject_objects(IM.identifier):
        if (node,RDF.type,IM.Document) in g:continue
        label=str(identifier)
        if re.search(r'(?<![\w-])'+re.escape(label)+r'(?![\w-])',question,re.I):exact.append(node)
    seeds=sorted(set(exact),key=str)
    for hit in hits:
        seeds.extend(n for n in sorted(links,key=str) if hit['chunk_id'] in links[n] and n not in seeds)
    queue=[(n,0) for n in seeds[:POLICY['max_seed_nodes']]]
    seen=set(); ordered=[]; paths=[]
    predicates={IM[x] for x in POLICY['traverse_predicates']}
    while queue and len(ordered)<POLICY['max_nodes']:
        node,depth=queue.pop(0)
        if node in seen:continue
        seen.add(node);ordered.append(node)
        if depth>=POLICY['graph_hops']:continue
        edges=set((node,p,o) for p,o in g.predicate_objects(node) if p in predicates and isinstance(o,URIRef))
        edges.update((s,p,node) for s,p in g.subject_predicates(node) if p in predicates)
        for s,p,o in sorted(edges,key=lambda t:tuple(map(str,t))):
            neighbor=o if s==node else s
            paths.append({'s':str(s),'p':str(p),'o':str(o),'depth':depth+1})
            if neighbor not in seen:queue.append((neighbor,depth+1))
    enc=tiktoken.get_encoding(cfg['context_encoding'])
    count=lambda text:len(enc.encode(text,disallowed_special=()))
    cards=[];included=[];omitted=[]
    for node in ordered:
        card={'kg_node':str(node),'status':'stored_v2_assertion_not_live_measurement',
              'properties':sorted([[str(p),str(o)] for p,o in g.predicate_objects(node)]),
              'provenance':[{'id':str(p),'fields':sorted([[str(k),str(val)] for k,val in g.predicate_objects(p)])} for p in sorted(g.objects(node,IM.hasProvenance),key=str)],
              'source_chunk_ids':links.get(node,[])}
        block='[KG assertion]\n'+json.dumps(card,ensure_ascii=False,sort_keys=True)
        if count('\n\n'.join(cards+[block]))>min(POLICY['graph_token_budget'],cfg['context_token_budget']):
            omitted.append(str(node));continue
        cards.append(block);included.append(node)
    by_id={c['chunk_id']:c for c in corpus};doc_ids=[]
    for node in included:
        for cid in links.get(node,[]):
            if cid not in doc_ids:doc_ids.append(cid)
    for h in hits:
        if h['chunk_id'] not in doc_ids:doc_ids.append(h['chunk_id'])
    selected=[];skipped=[];blocks=list(cards)
    for cid in doc_ids:
        c=by_id[cid]
        block=f"[{cid}] {c['doc_id']} p.{c['page']} | {c.get('section') or ''}\n{c['text']}"
        if count('\n\n'.join(blocks+[block]))>cfg['context_token_budget']:
            skipped.append(cid);continue
        blocks.append(block);selected.append(cid)
    text='\n\n'.join(blocks)
    return {'context':text,'context_tokens':count(text),'selected_ids':selected,
            'graph_nodes':list(map(str,included)),'omitted_graph_nodes':omitted,
            'visited_nodes':list(map(str,ordered)),'traversed_edges':paths,
            'exact_identifier_nodes':list(map(str,exact)),
            'skipped_for_budget':skipped,'policy':POLICY}


def retrieve_graph(question,call=v.api_call):
    corpus,matrix,m=v.load_index(v.DEFAULT_INDEX)
    q,api=v.embed([question],m['config'],v.DEFAULT_INDEX/'query_cache',call)
    hits=v.retrieve(corpus,matrix,q[0],m['config']['top_k'])
    result=graph_context(question,hits,corpus,load_graph(),m['config'])
    result.update(embedding_api=api,ranked_hits=hits,kg_sha256=v.digest((v.REPO_ROOT/KG_REL).read_bytes()))
    return result


def answer(system,question,run_dir,call=v.api_call):
    if system not in {'LLM','GraphRAG'}:raise ValueError('Expected LLM or GraphRAG')
    if not isinstance(question,str) or not question.strip() or len(question.encode())>8000:raise ValueError('Invalid question')
    cfg=v.read(v.CONFIG)
    common=(v.REPO_ROOT/'docs/vector_rag_v1/answer_instructions.txt').read_text(encoding='utf-8')
    run=Path(run_dir);run.mkdir(parents=True,exist_ok=False);started=time.perf_counter()
    v.write(run/'input.json',{'question':question,'system':system,'config':cfg,'policy':POLICY if system=='GraphRAG' else None})
    try:
        # LLM deliberately never opens KG, corpus, vector index or answer keys.
        retrieval=retrieve_graph(question,call) if system=='GraphRAG' else {'context':'','context_tokens':0,'selected_ids':[]}
        v.write(run/'retrieval.json',retrieval)
        payload={'model':cfg['generation_model'],'store':False,'max_completion_tokens':cfg['max_completion_tokens'],
                 'messages':[{'role':'system','content':common},{'role':'user','content':json.dumps({'question':question,'untrusted_reference_documents':retrieval['context']},ensure_ascii=False)}]}
        raw,api=call('chat/completions',payload,run/'api')
        choice=raw['choices'][0];msg=choice['message']
        if choice.get('finish_reason')!='stop' or not msg.get('content') or msg.get('refusal'):raise ValueError('Incomplete generation')
        result={'status':'complete','system':system,'question':question,'answer':msg['content'],
                'requested_model':cfg['generation_model'],'returned_model':raw.get('model'),
                'model_id_differs':raw.get('model')!=cfg['generation_model'],'usage':raw.get('usage',{}),
                'generation_api':api,'seconds':time.perf_counter()-started,'config':cfg,
                'instruction_sha256':v.digest(common.encode()),'selected_ids':retrieval['selected_ids'],
                'context_tokens':retrieval['context_tokens'],'grading_performed':False}
        v.write(run/'answer.json',result);return result
    except Exception as exc:
        v.write(run/'failure.json',{'status':'failed','error_type':type(exc).__name__,'grading_performed':False})
        raise


def main():
    p=argparse.ArgumentParser();p.add_argument('system',choices=['LLM','GraphRAG'])
    p.add_argument('--question',required=True);p.add_argument('--run-dir',required=True,type=Path)
    a=p.parse_args();print(json.dumps(answer(a.system,a.question,a.run_dir),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
