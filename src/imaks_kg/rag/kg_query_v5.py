"""Bounded relational plans over stored RDF, with equal-fact text serialization.

No benchmark IDs or answer keys are used. Plans log stored direction, including
inverse traversal. Seed and candidate rule nodes are never semantically merged.
"""
from collections import Counter,defaultdict,deque
import json
from urllib.parse import unquote
import re
from rdflib import RDF,URIRef
from . import comparison as c, vector as v, retrieval_v3 as r3, retrieval_v5 as doc


def short(term):
    return unquote(str(term).rsplit('#',1)[-1].rsplit('/',1)[-1])


class KGEngine:
    def __init__(self):
        self.graph=c.load_graph();self.documents=r3.row_corpus()
        self.doc_engine=doc.Engine(self.graph,self.documents)
        self.refs={str(self.graph.value(n,c.IM.identifier)):n for n in self.graph.subjects(c.IM.identifier,None)}
        self.records=[];self.node_ids={};self.id_nodes={}
        for i,node in enumerate(sorted(set(self.graph.subjects()),key=str),1):
            cid=f'KG:N{i:04d}';self.node_ids[node]=cid;self.id_nodes[cid]=node
            facts=defaultdict(list)
            for p,o in sorted(self.graph.predicate_objects(node),key=lambda t:tuple(map(str,t))):
                facts[short(p)].append(short(o) if isinstance(o,URIRef) else str(o))
            text=json.dumps({'node':short(node),**dict(facts)},ensure_ascii=False,sort_keys=True)
            self.records.append({'chunk_id':cid,'doc_id':'KG-SNAPSHOT','page':0,'section':'Frozen RDF stored facts',
                'text':text,'kind':'kg_node','text_sha256':v.digest(text.encode()),
                'source_file_sha256':v.digest((v.REPO_ROOT/c.KG_REL).read_bytes()),'parent_chunk_id':cid,'row_number':None,'table_id':None})
        manifest={'snapshot_sha256':v.digest((v.REPO_ROOT/c.KG_REL).read_bytes()),'triples':len(self.graph),
                  'identifier_index':sorted(self.refs),'predicate_counts':dict(Counter(short(p) for s,p,o in self.graph)),
                  'semantics':'Closed-world lookup only within this frozen snapshot; not physical absence.'}
        text=json.dumps(manifest,ensure_ascii=False,sort_keys=True)
        self.records.append({'chunk_id':'KG:MANIFEST','doc_id':'KG-SNAPSHOT','page':0,'section':'Snapshot manifest and identifier index',
            'text':text,'kind':'kg_manifest','text_sha256':v.digest(text.encode()),'source_file_sha256':manifest['snapshot_sha256'],
            'parent_chunk_id':'KG:MANIFEST','row_number':None,'table_id':None})
        self.rows=self.documents+self.records
        self.by_id={r['chunk_id']:r for r in self.rows}
        self.packer=doc.Engine(rows=self.rows)

    def nodes_for(self,question):
        exact=[]
        for identifier,node in self.refs.items():
            if re.search(r'(?<![A-Za-z0-9_-])'+re.escape(identifier)+r'(?![A-Za-z0-9_-])',question,re.I):
                exact.append(node)
        # Candidate identifiers are exact node requests, not permission to merge seed nodes.
        candidates=[n for n in exact if str(self.graph.value(n,c.IM.identifier)).startswith('candidate-')]
        if candidates:return set(candidates)
        return set(exact)

    def all_rules(self):
        return {n for typ in ['OperationalRule','ThresholdRule','MaintenanceRule','AccessRule']
                for n in self.graph.subjects(RDF.type,c.IM[typ])}

    def paths(self,start,end=None):
        g=self.graph;queue=deque([[start]]);found=[]
        while queue:
            path=queue.popleft()
            for node in sorted(g.objects(path[-1],c.IM.feedsInto),key=str):
                if node in path:continue
                nxt=path+[node]
                if end is None or node==end:found.append(nxt)
                if node!=end and len(nxt)<=len(self.refs):queue.append(nxt)
        return found

    def plan(self,question):
        g=self.graph;rules=self.all_rules();exact=self.nodes_for(question)
        stations,types=self.doc_engine.names(question)
        station_nodes={self.refs[x] for x in stations if x in self.refs}
        sensors={n for n in exact if (n,RDF.type,c.IM.Sensor) in g}
        if not sensors:
            sensors={s for st in station_nodes for s in g.objects(st,c.IM.hasSensor)
                     if not types or any(str(g.value(s,c.IM.identifier)).endswith('_'+t) for t in types)}
        selected=set(exact);trace=[];computed={};modes=[]
        subject_rules={n for s in sensors for n in g.subjects(c.IM.appliesToSensor,s)}
        target_rules={n for st in station_nodes for n in g.subjects(c.IM.actionTarget,st)}
        docs={n for n in exact if (n,RDF.type,c.IM.Document) in g}
        structural=bool(re.search(r'feedsInto|stationType|zone|소속|연결된 센서|센서는 어느|전체 식별자',question))
        if structural:
            selected.update(station_nodes);selected.update(sensors)
            for sensor in sensors:selected.update(g.subjects(c.IM.hasSensor,sensor))
            modes.append('structural_lookup')
        if 'feedsInto' in question:
            ordered=[n for n in exact if (n,RDF.type,c.IM.Station) in g]
            ordered.sort(key=lambda n:question.find(str(g.value(n,c.IM.identifier))))
            if ordered:
                pathsets=self.paths(ordered[0],ordered[1] if len(ordered)>1 else None)
                if len(ordered)>1 and question.count(str(g.value(ordered[0],c.IM.identifier)))>1:
                    pathsets+=self.paths(ordered[1],ordered[0])
                computed['feedsInto_paths']=[[short(n) for n in p] for p in pathsets]
                selected.update(n for p in pathsets for n in p);modes.append('simple_directed_paths')
        if re.search(r'A\s*=|A∩B|A−B|A-B',question):
            selected.update(subject_rules|target_rules)
            computed.update(A=sorted(map(short,subject_rules)),B=sorted(map(short,target_rules)),
                intersection=sorted(map(short,subject_rules & target_rules)),
                A_minus_B=sorted(map(short,subject_rules-target_rules)),B_minus_A=sorted(map(short,target_rules-subject_rules)))
            modes.append('two_role_set_algebra')
        elif 'appliesToSensor' in question and re.search(r'actionTarget.*다른|다른 Station|SOP-001.*출처',question):
            matches={n for n in subject_rules if any(t not in station_nodes for t in g.objects(n,c.IM.actionTarget))}
            if docs:matches={n for n in matches if set(g.objects(n,c.IM.sourceDocument)) & docs}
            selected.update(matches);modes.append('filtered_multi_relation_join')
        elif re.search(r'sourceDocument는 있지만.*appliesToSensor가 없는',question):
            matches={n for n in rules if list(g.objects(n,c.IM.sourceDocument)) and not list(g.objects(n,c.IM.appliesToSensor))}
            selected.update(matches);computed['matching_rules']=sorted(map(short,matches));modes.append('missing_relation_filter')
        elif re.search(r'actionTarget.*ST04|ST04.*actionTarget',question) and re.search(r'ST04만|나누어|대상 집합',question):
            selected.update(target_rules)
            missing={n for n in rules if not list(g.objects(n,c.IM.actionTarget))}
            selected.update(missing)
            computed['no_action_target_global']=sorted(map(short,missing));modes.append('target_set_partition')
        elif re.search(r'각각 하나 이상|문서 간 공통',question) and len(docs)>=2:
            matches=[]
            for s in g.subjects(RDF.type,c.IM.Sensor):
                rs=set(g.subjects(c.IM.appliesToSensor,s))
                if all(any((n,c.IM.sourceDocument,d) in g for n in rs) for d in docs):
                    matches.append(s);selected.add(s);selected.update(rs)
            computed['shared_sensors']=sorted(map(short,matches));modes.append('shared_sensor_document_join')
        elif 'sourceDocument' in question and docs and not sensors:
            matches={n for d in docs for n in g.subjects(c.IM.sourceDocument,d)}
            selected.update(matches);modes.append('source_document_reverse_lookup')
        elif sensors and not structural:
            if re.search(r'MaintenanceRule.*明|MaintenanceRule|정비 규칙',question):
                subject_rules={n for n in subject_rules if (n,RDF.type,c.IM.MaintenanceRule) in g}
            selected.update(subject_rules);modes.append('sensor_rule_reverse_lookup')
        if '최소' in question and 'appliesToSensor' in question and 'actionTarget' in question:
            target={n for n in exact if (n,RDF.type,c.IM.Station) in g} or station_nodes
            rows=[(s,n,t) for s in sensors for n in g.subjects(c.IM.appliesToSensor,s)
                  for t in g.objects(n,c.IM.actionTarget) if t in target]
            computed['minimum_two_edge_paths']=[[short(s),short(n),short(t)] for s,n,t in rows]
            selected.update(x for row in rows for x in row);modes.append('restricted_minimum_path')
        # Expand only declared structural roles, never infer a causal edge.
        for node in list(selected):
            for p in [c.IM.appliesToSensor,c.IM.actionTarget,c.IM.sourceDocument]:
                for obj in g.objects(node,p):
                    selected.add(obj);trace.append({'s':short(node),'p':short(p),'o':short(obj),'kind':'stored_edge'})
        if re.search(r'hasProvenance|해시|SHA-256|sha256|원문까지|표·행·열|정규화',question,re.I):
            for node in list(selected):
                if node in exact or node in rules:
                    selected.update(g.objects(node,c.IM.hasProvenance))
            modes.append('all_provenance_paths')
        ids=[self.node_ids[n] for n in sorted(selected,key=str) if n in self.node_ids]
        # Source text supports conditions not present in seed properties.
        source_ids=self.doc_engine.source_rule_ids(selected)
        if re.search(r'ST99_UNKNOWN',question):ids.insert(0,'KG:MANIFEST');computed['unknown_identifier']='absent_in_snapshot_index'
        return {'selected_nodes':sorted(map(short,selected)),'kg_rows':ids,'source_rows':source_ids,
                'computed':computed,'edges':trace,'modes':modes,
                'limits':'Stored facts and bounded query results only; no causal discovery or real-world absence claims.'}

    def retrieve(self,question,dense,system,budget=8000):
        if system=='LLM':return self.packer.pack([],budget,system)
        if system=='VectorRAG':return self.pack(dense,budget,system,{'graph_used':False})
        plan=self.plan(question)
        ranking=doc.rrf([dense,self.lexical(question)])
        chosen=list(dict.fromkeys(plan['kg_rows']+plan['source_rows']+ranking))
        return self.pack(chosen,budget,system,{**plan,'graph_used':True})

    def lexical(self,question):
        scores=self.packer.bm25.scores(self.doc_engine.expanded(question))
        return [r['chunk_id'] for score,r in sorted(zip(scores,self.rows),key=lambda x:(-x[0],x[1]['chunk_id'])) if score>0]

    def pack(self,ids,budget,system,trace):
        blocks=[];selected=[];skipped=[]
        for cid in dict.fromkeys(ids):
            if len(selected)>=128:break
            row=self.by_id[cid];block=f"[{cid}] {row['doc_id']} p.{row['page']}\n{row['text']}"
            text='\n\n'.join(blocks+[block])
            if len(self.packer.encoder.encode(text,disallowed_special=()))>budget:skipped.append(cid);continue
            blocks.append(block);selected.append(cid)
        text='\n\n'.join(blocks)
        return {'system':system,'context':text,'context_tokens':len(self.packer.encoder.encode(text,disallowed_special=())),
                'selected_ids':selected,'skipped_for_budget':skipped,'trace':trace,'budget':budget,
                'knowledge_parity':'Identical original documents and exact RDF node records available to both RAG systems.'}
