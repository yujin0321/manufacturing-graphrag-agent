"""Matched B/C retrieval: shared document selection, optional graph expansion."""
import re
import tiktoken
from . import graph_v2 as g,vector as v


def select(question,corpus,dense,graph_trace=None):
    policy=v.read(g.POLICY_PATH);ranked,_=g.fused_ranking(question,corpus,dense,policy)
    by_id={r['chunk_id']:r for r in corpus};docs=sorted({r['doc_id'] for r in corpus if g.matches(r['doc_id'],question)})
    # Build identifier vocabulary from raw documents, never from the KG or gold.
    vocabulary={t for r in corpus for t in re.findall(r'[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)+',r['text'])}
    ids=sorted(t for t in vocabulary if t not in {r['doc_id'] for r in corpus} and g.matches(t,question))
    prefix=[];reasons={}
    def add(target,cid,reason):
        if cid not in target:target.append(cid)
        reasons.setdefault(cid,[]).append(reason)
    for cid in ranked:
        if any(g.matches(t,by_id[cid]['text']) for t in ids):add(prefix,cid,'shared_literal_identifier')
    for i in range(policy['per_explicit_document']):
        for doc in docs:
            hits=[cid for cid in ranked if by_id[cid]['doc_id']==doc]
            if i<len(hits):add(prefix,hits[i],'shared_document_coverage')
    candidates=list(prefix);graph_added=[]
    if graph_trace is not None:
        for node in graph_trace['visited_nodes']:
            for cid in graph_trace['source_links'].get(node,[]):
                if cid not in candidates:graph_added.append(cid)
                add(candidates,cid,'graph_visited_node_provenance')
    for cid in ranked:add(candidates,cid,'shared_fused_retrieval')
    bounded=candidates[:policy['max_source_candidates']]
    hits=[by_id[cid] for cid in bounded]
    text,selected,skipped,n=v.context(hits,policy)
    assert len(tiktoken.get_encoding(policy['context_encoding']).encode(text,disallowed_special=()))==n
    return {'context':text,'context_tokens':n,'selected_ids':[r['chunk_id'] for r in selected],
            'shared_prefix':prefix,'shared_ranked_ids':ranked,'literal_identifiers':ids,'explicit_documents':docs,
            'candidate_ids':bounded,'graph_added_before_cap':graph_added,'reasons':reasons,
            'skipped_for_budget':skipped,'graph_cards':0,'policy':policy,
            'variant':'B_no_graph' if graph_trace is None else 'C_graph_expansion'}
