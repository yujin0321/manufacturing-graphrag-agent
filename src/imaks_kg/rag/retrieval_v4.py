"""GraphRAG v4 source selection: v3 baseline plus typed queries, bounded context."""
from pathlib import Path
import re
import tiktoken
from rdflib import RDF, URIRef
from . import retrieval_v3 as base, comparison as c, linking, vector as v

VERSION='retrieval-v4-20261028'


def typed_candidates(question,rows,graph):
    selected=[];plans=[]
    def add(items):
        for cid in items:
            if cid not in selected:selected.append(cid)
    lower=question.lower()
    index=linking.EntityIndex.build(graph)
    priority=next((p for p in ('CRITICAL','HIGH','MEDIUM','LOW') if linking.find_spans(p,question)),None)
    if priority and re.search(r'정비|maintenance|MAINT',question,re.I):
        mentions=index.link(question)
        named_sensors={m.node for m in mentions if (URIRef(m.node),RDF.type,c.IM.Sensor) in graph}
        named_stations={m.node for m in mentions if (URIRef(m.node),RDF.type,c.IM.Station) in graph}
        if named_stations and not named_sensors:
            named_sensors={str(s) for station in named_stations for s in graph.objects(URIRef(station),c.IM.hasSensor)}
        nodes=[]
        for n in graph.subjects(RDF.type,c.IM.MaintenanceRule):
            if str(graph.value(n,c.IM.priority) or '').upper()!=priority:continue
            if named_sensors and not ({str(s) for s in graph.objects(n,c.IM.appliesToSensor)} & named_sensors):continue
            nodes.append(str(n))
        links=base.provenance_rows(graph,rows)
        ids=sorted({cid for n in nodes for cid in links.get(n,[])})
        # Include document rows whose validated source fields carry the same filter.
        # Seed nodes may not have document provenance; source rows supply their exact wording.
        for row in rows:
            text=row['text']
            if 'Rule ID: MAINT-' not in text or f'Priority: {priority}' not in text:continue
            if named_sensors:
                station_match=re.search(r'Station:\s*([^;\n]+)',text)
                sensor_match=re.search(r'Sensor:\s*([^;\n]+)',text)
                if not station_match or not sensor_match:continue
                target=f'{station_match.group(1).strip()}_{sensor_match.group(1).strip()}'
                if not any(target==str(graph.value(URIRef(s),c.IM.identifier)) for s in named_sensors):continue
            ids.append(row['chunk_id'])
        ids=sorted(set(ids));add(ids)
        plans.append({'type':'maintenance_priority_filter','priority':priority,'kg_matching_nodes':sorted(nodes),'source_ids':ids,'scope':'station/sensor filtered' if named_sensors else 'all maintenance rules'})
    definition_rows=[r for r in rows if 'Detection Criterion:' in r['text'] and 'Ontology Class:' in r['text']]
    wants_definition=bool(re.search(r'정의|탐지\s*기준|이상\s*유형|definition|detection criterion',question,re.I))
    stuck=bool(re.search(r'고착|stuck|연속.{0,12}(?:같|동일)|(?:같|동일).{0,12}연속',question,re.I))
    if wants_definition or stuck:
        types=[t for t in ('SPIKE','DRIFT','STUCK','OUT_OF_RANGE','CORRELATED') if linking.find_spans(t,question)]
        if stuck and not types:types=['STUCK']
        ids=[r['chunk_id'] for r in definition_rows if not types or any(f'Type: {t};' in r['text'] for t in types)]
        add(ids);plans.append({'type':'anomaly_definition_table','types':types or ['all'],'source_ids':ids})
    if re.search(r'역할|role|확인\s*시간|acknowledg',question,re.I) and re.search(r'경보|시간|severity|ack',question,re.I):
        ids=[r['chunk_id'] for r in rows if 'Role:' in r['text'] and 'Max Ack' in r['text']]
        add(ids);plans.append({'type':'role_acknowledgement_table','source_ids':ids,'include_ties':True})
    return selected,plans


def retrieve(question,*,use_dense=False,typed=True,call=v.api_call,dense=None):
    rows=base.row_corpus();graph=c.load_graph();policy=base.load_policy()
    if use_dense and dense is None:dense=base.dense_ranking(question,rows,call=call)
    result=base.build_context('graph_v3',question,rows,dense,graph)
    prefix,plans=typed_candidates(question,rows,graph) if typed else ([],[])
    if not prefix:
        return {**result,'retrieval_version':VERSION,'typed_queries':plans,'coverage_required_ids':[],'coverage_complete':True}
    by_id={r['chunk_id']:r for r in rows}
    # Same source cap/budget as v3. Only typed source ordering changes here.
    expanded,_=base.expand_query(question,graph)
    ranking=base.fused_ranking(expanded,rows,dense,policy)
    ordered=list(dict.fromkeys(prefix+result['selected_ids']+ranking))[:policy['max_source_candidates']]
    enc=tiktoken.get_encoding(policy['context_encoding']);count=lambda text:len(enc.encode(text,disallowed_special=()))
    blocks=[];ids=[];skipped=[]
    for cid in ordered:
        block=base._render(by_id,cid)
        if count('\n\n'.join(blocks+[block]))>policy['context_token_budget']:skipped.append(cid);continue
        blocks.append(block);ids.append(cid)
    cards=[];links=base.provenance_rows(graph,rows);index=linking.EntityIndex.build(graph)
    for key in result.get('visited_entities',[]):
        import json
        block='[KG entity]\n'+json.dumps(linking.merged_card(graph,index.group_of(key),links),ensure_ascii=False,sort_keys=True)
        if count('\n\n'.join(cards+[block]))<=policy['graph']['max_graph_tokens'] and count('\n\n'.join(blocks+cards+[block]))<=policy['context_token_budget']:cards.append(block)
    text='\n\n'.join(blocks+cards)
    return {**result,'context':text,'context_tokens':count(text),'selected_ids':ids,
        'selected_parent_ids':sorted({base.parent_of(cid) for cid in ids}),'skipped_for_budget':skipped,
        'retrieval_version':VERSION,'typed_queries':plans,'coverage_required_ids':prefix,
        'coverage_complete':set(prefix).issubset(ids)}


def source_packet(result):
    rows={r['chunk_id']:r for r in base.row_corpus()}
    return {'context':result['context'],'context_tokens':result['context_tokens'],
        'selected_ids':result['selected_ids'],'sources':[rows[cid] for cid in result['selected_ids']],
        'graph_paths':result.get('traversed_edges',[]),'retrieval_trace':result,
        'retrieval_backend':VERSION,'dense_used':result.get('dense_used',False),
        'coverage_required_ids':result['coverage_required_ids'],'coverage_complete':result['coverage_complete']}


def retrieval_lock(use_dense=False):
    from . import routing_v4
    from . import lexical, chunking
    files=[Path(__file__),Path(routing_v4.__file__),Path(base.__file__),Path(linking.__file__),Path(lexical.__file__),Path(chunking.__file__),Path(v.__file__),Path(c.__file__),base.POLICY_PATH,linking.LEXICON_PATH,v.REPO_ROOT/c.KG_REL,v.SOURCE]
    lock={'backend':VERSION,'dense_requested':use_dense,'files':{str(p.relative_to(v.REPO_ROOT)):v.digest(p.read_bytes()) for p in files}}
    if use_dense and (base.ROW_INDEX/'manifest.json').exists():lock['row_index_manifest_sha256']=v.digest((base.ROW_INDEX/'manifest.json').read_bytes())
    return lock
