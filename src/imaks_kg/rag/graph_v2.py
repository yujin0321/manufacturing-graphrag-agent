"""Separate retrieval-only experiment. No answer keys or generation API."""
import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from rdflib import RDF, URIRef
import tiktoken
from . import vector as v, comparison as c

POLICY_PATH=v.REPO_ROOT/'docs/graphrag_v2/retrieval_policy.json'


def matches(identifier,text):
    # ASCII identifier boundaries permit Korean particles but reject longer IDs.
    return bool(re.search(r'(?<![A-Za-z0-9_-])'+re.escape(identifier)+r'(?![A-Za-z0-9_-])',text,re.I))


def aliases(g,node):
    result=set()
    for value in g.objects(node,c.IM.identifier):
        label=str(value);result.add(label)
        if '::' in label:result.add(label.rsplit('::',1)[1])
    return sorted(result)


def tokens(text):
    return re.findall(r'[a-z0-9]+(?:[-_][a-z0-9]+)*|[가-힣]+',text.lower())


def fused_ranking(question,corpus,dense,policy):
    query=set(tokens(question));sets=[set(tokens(v.embedding_text(r))) for r in corpus]
    df=Counter(t for ts in sets for t in ts)
    lexical={r['chunk_id']:sum(math.log(1+len(corpus)/(1+df[t])) for t in query & ts) for r,ts in zip(corpus,sets)}
    lex_order=sorted(lexical,key=lambda cid:(-lexical[cid],cid))
    lex_rank={cid:i+1 for i,cid in enumerate(lex_order)}
    dense_rank={r['chunk_id']:i+1 for i,r in enumerate(dense)}
    assert set(dense_rank)==set(lexical),'Full dense ranking required'
    k=policy['rrf_constant']
    scores={cid:1/(k+dense_rank[cid])+(1/(k+lex_rank[cid]) if lexical[cid]>0 else 0) for cid in lexical}
    return sorted(scores,key=lambda cid:(-scores[cid],cid)),scores


def context(question,corpus,dense,g,policy=None):
    policy=policy or v.read(POLICY_PATH)
    links=c.source_links(g,corpus);by_id={r['chunk_id']:r for r in corpus}
    ranked,scores=fused_ranking(question,corpus,dense,policy)
    docs=sorted({r['doc_id'] for r in corpus if matches(r['doc_id'],question)})
    nodes=sorted(set(g.subjects(c.IM.identifier,None)),key=str)
    exact=[n for n in nodes if (n,RDF.type,c.IM.Document) not in g and any(matches(a,question) for a in aliases(g,n))]
    seeds=list(exact)
    for cid in ranked[:8]:
        seeds.extend(n for n in sorted(links,key=str) if cid in links[n] and n not in seeds)
    queue=[(n,0) for n in seeds[:policy['max_seed_nodes']]];seen=set();visited=[];edges=[]
    allowed={c.IM[x] for x in policy['traverse_predicates']}
    while queue and len(visited)<policy['max_graph_nodes']:
        node,depth=queue.pop(0)
        if node in seen:continue
        seen.add(node);visited.append(node)
        if depth>=policy['graph_hops']:continue
        adjacent=set((node,p,o) for p,o in g.predicate_objects(node) if p in allowed and isinstance(o,URIRef))
        adjacent.update((s,p,node) for s,p in g.subject_predicates(node) if p in allowed)
        for s,p,o in sorted(adjacent,key=lambda t:tuple(map(str,t))):
            nxt=o if s==node else s;edges.append({'kind':'stored_edge','s':str(s),'p':str(p),'o':str(o),'depth':depth+1});queue.append((nxt,depth+1))
        # References in original text are retrieval links, never asserted RDF edges.
        texts=[str(x) for pred in [c.IM.conditionText,c.IM.responseText] for x in g.objects(node,pred)]
        texts += [by_id[cid]['text'] for cid in links.get(node,[])]
        reftext='\n'.join(texts)
        for other in nodes:
            if other==node or (other,RDF.type,c.IM.Document) in g:continue
            if any(a.startswith(('RULE-','MAINT-')) and matches(a,reftext) for a in aliases(g,other)):
                edges.append({'kind':'text_reference_not_new_fact','s':str(node),'o':str(other),'depth':depth+1});queue.append((other,depth+1))
    candidates=[];reasons={}
    def add(cid,why):
        if cid not in candidates:candidates.append(cid)
        reasons.setdefault(cid,[]).append(why)
    # Exact entity provenance is selected independently of graph-card token cost.
    for node in exact:
        for cid in links.get(node,[]):add(cid,'exact_identifier_provenance')
    doc_lists={doc:[cid for cid in ranked if by_id[cid]['doc_id']==doc] for doc in docs}
    for i in range(policy['per_explicit_document']):
        for doc,items in doc_lists.items():
            if i<len(items):add(items[i],'explicit_document_coverage')
    for node in visited:
        for cid in links.get(node,[]):add(cid,'graph_provenance')
    for cid in ranked:add(cid,'fused_retrieval')
    excluded=candidates[policy['max_source_candidates']:];candidates=candidates[:policy['max_source_candidates']]
    enc=tiktoken.get_encoding(policy['context_encoding']);count=lambda s:len(enc.encode(s,disallowed_special=()))
    blocks=[];selected=[];skipped=[]
    for cid in candidates:
        r=by_id[cid];block=f"[{cid}] {r['doc_id']} p.{r['page']} | {r.get('section') or ''}\n{r['text']}"
        if count('\n\n'.join(blocks+[block]))>policy['context_token_budget']:skipped.append(cid);continue
        blocks.append(block);selected.append(cid)
    # Compact cards retain original properties; full provenance is logged separately.
    cards=[];card_nodes=[];omitted=[]
    for node in visited:
        card={'node':str(node),'status':'stored_v2_assertion_not_live_measurement',
              'properties':sorted([[str(p).rsplit('#',1)[-1],str(o)] for p,o in g.predicate_objects(node) if p!=c.IM.hasProvenance]),
              'provenance_ids':sorted(map(str,g.objects(node,c.IM.hasProvenance))), 'source_chunks':links.get(node,[])}
        block='[KG assertion]\n'+json.dumps(card,ensure_ascii=False,sort_keys=True)
        if count('\n\n'.join(cards+[block]))>policy['max_graph_tokens'] or count('\n\n'.join(blocks+cards+[block]))>policy['context_token_budget']:
            omitted.append(str(node));continue
        cards.append(block);card_nodes.append(str(node))
    text='\n\n'.join(blocks+cards)
    return {'context':text,'context_tokens':count(text),'selected_ids':selected,'policy':policy,
            'explicit_documents':docs,'uncovered_explicit_documents':[d for d in docs if not any(by_id[cid]['doc_id']==d for cid in selected)],
            'exact_identifier_nodes':list(map(str,exact)),'visited_nodes':list(map(str,visited)),
            'traversed_edges':edges,'graph_nodes':card_nodes,'omitted_graph_nodes':omitted,
            'source_candidate_reasons':reasons,'skipped_for_budget':skipped,'excluded_by_candidate_cap':excluded,
            'fused_scores':scores,'source_links':{str(n):links.get(n,[]) for n in visited},
            'provenance':{str(p):sorted([[str(k),str(val)] for k,val in g.predicate_objects(p)]) for n in visited for p in g.objects(n,c.IM.hasProvenance)}}


def cached_embeddings(resource,payload,cache):
    if resource!='embeddings':raise ValueError('Retrieval only')
    key=v.digest(v.encoded({'resource':resource,'payload':payload}));path=Path(cache)/(key+'.response.json')
    if not path.is_file():raise FileNotFoundError('Question embedding cache missing; no API request made')
    return v.read(path),{'cache_hit':True,'request_sha256':key,'seconds':0}


def retrieve(question):
    if not isinstance(question,str) or not question.strip() or len(question.encode())>8000:raise ValueError('Invalid question')
    corpus,matrix,m=v.load_index(v.DEFAULT_INDEX)
    query,api=v.embed([question],m['config'],v.DEFAULT_INDEX/'query_cache',cached_embeddings)
    dense=v.retrieve(corpus,matrix,query[0],len(corpus))
    result=context(question,corpus,dense,c.load_graph())
    result.update(embedding_api=api,kg_sha256=v.digest((v.REPO_ROOT/c.KG_REL).read_bytes()),policy_sha256=v.digest(POLICY_PATH.read_bytes()))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--question',required=True);p.add_argument('--run-dir',required=True,type=Path);a=p.parse_args()
    result=retrieve(a.question);a.run_dir.mkdir(parents=True,exist_ok=False)
    v.write(a.run_dir/'retrieval.json',result)
    print(json.dumps({'selected_ids':result['selected_ids'],'context_tokens':result['context_tokens'],'uncovered_documents':result['uncovered_explicit_documents']},ensure_ascii=False,indent=2))
