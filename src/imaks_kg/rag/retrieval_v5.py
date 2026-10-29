"""Evidence-first, intent-scoped graph retrieval; no benchmark or answer access.

The graph chooses source rows. Only original source text enters the generator,
so extracted/seed assertions cannot silently become additional answer knowledge.
"""
from __future__ import annotations
from collections import defaultdict, deque
import hashlib
import json
import re
from pathlib import Path
from rdflib import RDF, URIRef
import tiktoken
from . import vector as v, comparison as c, retrieval_v3 as r3, linking
from .lexical import BM25, rrf

VERSION = 'graph-v5-evidence-plans-20261029'
POLICY = {'context_tokens':4000, 'max_rows':24, 'reference_hops':2,
          'rrf_constant':60, 'encoding':'o200k_base', 'source_only_generation':True}


def norm(text):
    return ' '.join(str(text).split())


def validated_provenance(graph, rows):
    """Match source hash, quote hash and exact row content, not table ID alone."""
    links = defaultdict(set)
    audit = []
    for node, prov in graph.subject_objects(c.IM.hasProvenance):
        if str(graph.value(prov, c.IM.sourceKind)) != 'document':
            continue
        quote = str(graph.value(prov, c.IM.sourceQuote) or '')
        sha = str(graph.value(prov, c.IM.fileSha256) or '')
        text_sha = str(graph.value(prov, c.IM.textSha256) or '')
        valid_hash = bool(quote) and hashlib.sha256(quote.encode()).hexdigest() == text_sha
        matches = [r['chunk_id'] for r in rows if valid_hash
                   and r['source_file_sha256'] == sha and norm(quote) in norm(r['text'])]
        links[str(node)].update(matches)
        audit.append({'node':str(node), 'provenance':str(prov),
                      'quote_hash_valid':valid_hash, 'matched_rows':matches})
    return {n:sorted(ids) for n,ids in links.items()}, audit


class Engine:
    def __init__(self, graph=None, rows=None):
        self.rows = rows if rows is not None else r3.row_corpus()
        self.by_id = {r['chunk_id']:r for r in self.rows}
        self.lexicon = v.read(v.REPO_ROOT/'docs/graphrag_v3/lexicon.json')
        self.bm25 = BM25([v.embedding_text(r) for r in self.rows])
        self.encoder = tiktoken.get_encoding(POLICY['encoding'])
        self.graph = graph
        self.links, self.audit = ({}, []) if graph is None else validated_provenance(graph, self.rows)
        self.index = None if graph is None else linking.EntityIndex.build(graph)
        self.public_stations = set(self.lexicon['stations'])
        # A public name dictionary shared by both baselines; no rule values.
        self.public_types = set(self.lexicon['sensor_types'])

    def names(self, question):
        stations = []
        for name, aliases in self.lexicon['stations'].items():
            if any(linking.find_spans(a,question) for a in [name,name.split('_')[0],*aliases]):
                stations.append(name)
        types = []
        for typ,aliases in self.lexicon['sensor_types'].items():
            if any(linking.find_spans(a,question) for a in [typ,*aliases]):types.append(typ)
        return stations, types

    def expanded(self, question):
        stations, types = self.names(question)
        terms = stations + types + [f'{s}_{t}' for s in stations for t in types]
        return question+'\n'+' '.join(terms)

    def common_table_rows(self, question):
        """Source-only table filters shared by HybridRAG and GraphRAG."""
        out=[]
        if re.search(r'이상\s*유형|탐지\s*기준|definition|detection criterion',question,re.I):
            out += [r['chunk_id'] for r in self.rows if 'Detection Criterion:' in r['text']]
        if re.search(r'역할|확인\s*시간|acknowledg',question,re.I):
            out += [r['chunk_id'] for r in self.rows if 'Max Ack' in r['text']]
        return out

    def source_rule_ids(self, nodes):
        return sorted({cid for n in nodes for cid in self.links.get(str(n),[])})

    def plan(self, question):
        if self.graph is None:raise ValueError('Graph plans require a graph')
        g=self.graph; stations,types=self.names(question)
        mentions=self.index.link(question)
        sensors={URIRef(m.node) for m in mentions if (URIRef(m.node),RDF.type,c.IM.Sensor) in g}
        station_nodes={URIRef(m.node) for m in mentions if (URIRef(m.node),RDF.type,c.IM.Station) in g}
        if not sensors:
            sensors={s for st in station_nodes for s in g.objects(st,c.IM.hasSensor)
                     if not types or any(str(g.value(s,c.IM.sensorType) or '')==t or
                                        str(g.value(s,c.IM.identifier)).endswith('_'+t) for t in types)}
        direct_rules={URIRef(m.node) for m in mentions
                      if any((URIRef(m.node),RDF.type,c.IM[t]) in g for t in
                             ['OperationalRule','ThresholdRule','MaintenanceRule','AccessRule'])}
        edges=[]
        for sensor in sorted(sensors,key=str):
            for rule in g.subjects(c.IM.appliesToSensor,sensor):
                direct_rules.add(rule)
                edges.append({'s':str(rule),'p':'appliesToSensor','o':str(sensor),'kind':'stored_edge'})
        priority=next((p for p in ['CRITICAL','HIGH','MEDIUM','LOW']
                       if linking.find_spans(p,question)),None)
        aggregate=bool(priority and re.search(r'정비|maintenance',question,re.I))
        if aggregate:
            matches={n for n in g.subjects(RDF.type,c.IM.MaintenanceRule)
                     if str(g.value(n,c.IM.priority) or '').upper()==priority
                     and (not sensors or set(g.objects(n,c.IM.appliesToSensor)) & sensors)}
            # Seed and extracted nodes stay distinct; canonical ID is a retrieval bridge.
            for n in list(matches):
                matches.update(URIRef(m) for m in self.index.group_of(str(n)))
            direct_rules=matches
        ids=self.source_rule_ids(direct_rules)
        # Exact source membership is a secondary index: some source rows were
        # never extracted, so a KG-only union must not claim corpus completeness.
        membership=[]
        for row in self.rows:
            text=row['text']; section=str(row.get('section') or '')
            named=any(s in text or s in section or
                      re.search(r'(?<![A-Z0-9])'+s.split('_')[0]+r'(?![A-Z0-9])',text)
                      for s in stations)
            typed=not types or any(re.search(r'(?<![A-Z0-9])'+t+r'(?![A-Z0-9])',text) for t in types)
            if named and typed:membership.append(row['chunk_id'])
            if aggregate and 'Rule ID: MAINT-' in text and f'Priority: {priority}' in text:
                if not stations or named:membership.append(row['chunk_id'])
        if aggregate:
            ids=[cid for cid in dict.fromkeys(ids+membership)
                 if f'Priority: {priority}' in self.by_id[cid]['text']]
        else:
            ids=list(dict.fromkeys(ids+membership))
        # Prefer literal rule anchors before their companions, without changing
        # thresholds or resolving source conflicts in the retriever.
        exact = [cid for cid in ids if any(linking.find_spans(rid,question)
                    for rid in re.findall(r'(?:RULE-[A-Z0-9-]+|MAINT-\d+)',self.by_id[cid]['text']))]
        ids=list(dict.fromkeys(exact+ids))
        refs=[]; queue=deque((cid,0) for cid in ids); seen=set(ids)
        while queue:
            cid,depth=queue.popleft()
            if depth>=POLICY['reference_hops']:continue
            for rid in re.findall(r'(?:RULE-[A-Z0-9-]+|MAINT-\d+)',self.by_id[cid]['text']):
                candidates=[r['chunk_id'] for r in self.rows
                            if r['text'].startswith(rid+':') or f'Rule ID: {rid};' in r['text']]
                for other in candidates:
                    if other in seen:continue
                    seen.add(other);refs.append(other);queue.append((other,depth+1))
                    edges.append({'s':cid,'p':'explicit_source_reference','o':other,
                                  'kind':'source_text_reference_not_causal_edge'})
        # Multi-document comparison: include the matching datasheet, but never
        # turn it into an assertion of the model actually installed.
        compare=bool(re.search(r'사양|데이터시트|datasheet|정격|모델|설치',question,re.I))
        companions=[]
        if compare:
            target={'TMP':'DS-THERM-2200','CUR':'DS-ELEC-3300','PRS':'DS-MECH-4400'}
            docs={target[t] for t in types if t in target}
            companions=[r['chunk_id'] for r in self.rows if r['doc_id'] in docs]
        # Document facets get round-robin coverage before ranking fills gaps.
        groups=defaultdict(list)
        for cid in list(dict.fromkeys(ids+refs+companions)):
            groups[self.by_id[cid]['doc_id']].append(cid)
        balanced=[]
        while any(groups.values()):
            for doc in sorted(groups):
                if groups[doc]:balanced.append(groups[doc].pop(0))
        return {'stations':stations,'sensor_types':types,'sensors':sorted(map(str,sensors)),
                'direct_rules':sorted(map(str,direct_rules)),'graph_rows':balanced,
                'reference_rows':refs,'source_membership_rows':membership,
                'edges':edges,'aggregate_priority':priority if aggregate else None,
                'coverage_scope':'validated graph joins plus explicit source membership; not inferred causality'}

    def pack(self, ordered, budget, system, trace=None):
        blocks=[];selected=[];skipped=[]
        for cid in dict.fromkeys(ordered):
            if len(selected)>=POLICY['max_rows']:break
            row=self.by_id[cid]
            block=f"[{cid}] {row['doc_id']} p.{row['page']} | {row.get('section') or ''}\n{row['text']}"
            if len(self.encoder.encode('\n\n'.join(blocks+[block]),disallowed_special=()))>budget:
                skipped.append(cid);continue
            blocks.append(block);selected.append(cid)
        text='\n\n'.join(blocks)
        return {'system':system,'version':VERSION,'context':text,
                'context_tokens':len(self.encoder.encode(text,disallowed_special=())),
                'budget':budget,'selected_ids':selected,'skipped_for_budget':skipped,
                'source_only':True,'trace':trace or {}}

    def retrieve(self, question, dense, system='GraphRAG', budget=4000):
        if system=='LLM':return self.pack([],budget,system)
        if dense is None:raise ValueError('Dense ranking required; no silent fallback')
        if system=='VectorRAG':return self.pack(dense,budget,system,{'graph_used':False,'ranking':'dense_only'})
        if system not in {'HybridRAG','GraphRAG'}:raise ValueError('Unknown system')
        expanded=self.expanded(question)
        scores=self.bm25.scores(expanded)
        lexical=[r['chunk_id'] for score,r in sorted(zip(scores,self.rows),key=lambda x:(-x[0],x[1]['chunk_id'])) if score>0]
        fused=rrf([dense,lexical],POLICY['rrf_constant'])
        prefix=r3.shared_prefix(question,self.rows,fused,r3.load_policy())
        common=self.common_table_rows(question)
        if system=='HybridRAG':
            return self.pack(prefix+common+fused,budget,system,
                             {'graph_used':False,'shared_name_expansion':expanded})
        plan=self.plan(question)
        # Relevance rank within document/facet groups prevents lexicographic rule
        # IDs from consuming context intended for the observed sensor condition.
        rank={cid:i for i,cid in enumerate(fused)}
        groups=defaultdict(list)
        for cid in plan['graph_rows']:groups[self.by_id[cid]['doc_id']].append(cid)
        for values in groups.values():values.sort(key=lambda cid:rank.get(cid,9999))
        graph_rows=[]
        while any(groups.values()):
            for doc in sorted(groups):
                if groups[doc]:graph_rows.append(groups[doc].pop(0))
        result=self.pack(prefix+common+graph_rows+fused,budget,system,
                         {**plan,'graph_used':True,'shared_name_expansion':expanded})
        result['graph_coverage_selected']=sorted(set(plan['graph_rows']) & set(result['selected_ids']))
        result['graph_coverage_omitted']=sorted(set(plan['graph_rows'])-set(result['selected_ids']))
        return result


def dense_order(question, rows, cache):
    """Read the existing row index, query using a workspace-local API cache."""
    import numpy as np
    manifest=v.read(r3.ROW_INDEX/'manifest.json')
    if manifest['row_ids'] != [r['chunk_id'] for r in rows] or manifest['corpus_sha256']!=v.digest(v.encoded(rows)):
        raise ValueError('Row index corpus mismatch')
    path=r3.ROW_INDEX/'vectors.npy'
    if v.digest(path.read_bytes())!=manifest['vectors_sha256']:raise ValueError('Vector hash mismatch')
    matrix=v.normalized(np.load(path,allow_pickle=False),len(rows),manifest['config']['dimensions'])
    query,usage=v.embed([question],manifest['config'],Path(cache))
    return [r['chunk_id'] for r in v.retrieve(rows,matrix,query[0],len(rows))],usage
