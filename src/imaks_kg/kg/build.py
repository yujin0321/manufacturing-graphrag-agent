"""Convert the agreed seed subset and provenance-rich rule candidates to RDF/Neo4j."""
import argparse
import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from pyshacl import validate
from rdflib import Graph, Namespace, Literal, RDF, RDFS, XSD, URIRef

from imaks_kg.common.io_utils import read_csv_rows, write_json, write_jsonl, write_text, write_csv
from imaks_kg.common.provenance import sha256_file
from imaks_kg.common.raw_io import raw_csv_rows, raw_sha256
from imaks_kg.kg.documents import OUT, sources, units, read_jsonl, validate_records
from imaks_kg.settings import REPO_ROOT

IM=Namespace('https://example.org/imaks/v1#')
ID=Namespace('https://example.org/imaks/id/')


def iri(name): return ID[quote(str(name),safe='-_')]


class Builder:
    def __init__(self):
        self.g=Graph(); self.g.bind('im',IM); self.g.bind('inst',ID)
        self.evidence={}
        self.ontology=Graph().parse(REPO_ROOT/'ontology_v1/ontology.ttl')

    def add(self,s,p,o,evidence):
        self.g.add((s,p,o))
        key=(s.n3(),p.n3(),o.n3())
        self.evidence.setdefault(key,set()).add(evidence)

    def props(self,s,props,evidence):
        for k,v in props.items():
            if v is None or v=='': continue
            dtype=self.ontology.value(IM[k],RDFS.range) or XSD.string
            # Turtle renders integral decimals with '.0'. Use the same lexical
            # form before recording evidence, so saved triples match the ledger.
            if dtype==XSD.decimal:
                v=format(Decimal(str(v)),'f')
                if '.' not in v: v+='.0'
            self.add(s,IM[k],Literal(v) if dtype==XSD.string else Literal(v,datatype=dtype),evidence)

    def provenance(self,name,props):
        node=iri('prov-'+name)
        self.add(node,RDF.type,IM.Provenance,str(node))
        self.props(node,props,str(node))
        return node

    def entity(self,name,kind,props,prov):
        node=iri(name)
        self.add(node,RDF.type,IM[kind],str(prov))
        self.props(node,dict(identifier=name,**props),str(prov))
        self.add(node,IM.hasProvenance,prov,str(prov))
        return node

    def check(self,graph,shapes,output):
        ok,_,report=validate(graph,shacl_graph=Graph().parse(shapes),ont_graph=self.ontology,inference='none')
        write_text(output,report)
        if not ok: raise ValueError('SHACL failure: '+str(output))


def export(graph,folder):
    """Parameter JSON plus idempotent Cypher; no DB connection is made here."""
    typed=sorted(set(graph.subjects(RDF.type,None)),key=str)
    nodes=[]; relations=[]
    for s in typed:
        labels=sorted(str(x).split('#')[-1] for x in graph.objects(s,RDF.type))
        props={}
        for p in sorted(set(graph.predicates(s)),key=str):
            values=[o.toPython() for o in graph.objects(s,p) if isinstance(o,Literal)]
            if values: props[str(p).split('#')[-1]]=values[0] if len(values)==1 else values
        props=json.loads(json.dumps(props,default=lambda v:float(v) if isinstance(v,Decimal) else str(v)))
        nodes.append(dict(iri=str(s),labels=labels,properties=props))
        for p,o in graph.predicate_objects(s):
            if p!=RDF.type and isinstance(o,URIRef):
                relations.append(dict(source=str(s),target=str(o),type=str(p).split('#')[-1]))
    relations.sort(key=lambda r:(r['source'],r['type'],r['target']))
    write_json(folder/'neo4j_parameters.json',dict(nodes=nodes,relationships=relations))
    lines=['// Load neo4j_parameters.json as parameters; run in a dedicated database.',
           'CREATE CONSTRAINT imaks_entity_iri IF NOT EXISTS FOR (n:ImaksEntity) REQUIRE n.iri IS UNIQUE;']
    for kind in sorted({k for n in nodes for k in n['labels']}):
        lines.append(f"UNWIND $nodes AS row WITH row WHERE '{kind}' IN row.labels "
                     f"MERGE (n:ImaksEntity {{iri:row.iri}}) SET n:{kind} SET n += row.properties;")
    for kind in sorted({r['type'] for r in relations}):
        lines.append(f"UNWIND $relationships AS row WITH row WHERE row.type='{kind}' "
                     f"MATCH (a:ImaksEntity {{iri:row.source}}), (b:ImaksEntity {{iri:row.target}}) MERGE (a)-[:{kind}]->(b);")
    write_text(folder/'import.cypher','\n'.join(lines)+'\n')
    return Counter(k for n in nodes for k in n['labels']),Counter(r['type'] for r in relations)


def build(predictions, output=None):
    records=validate_records(read_jsonl(predictions)) if predictions else []
    b=Builder(); manifest,chunks,tables=sources()
    source_units={u['unit_id']:u for u in units()}
    nodepath=REPO_ROOT/'imaks_data/kg_seed/nodes.csv'; edgepath=nodepath.with_name('edges.csv')
    _,ns=raw_csv_rows(nodepath); _,es=raw_csv_rows(edgepath)
    byid={n['nodeId']:n for n in ns}; mapped={}; exclusions=Counter(); mapping=[]
    for n in ns:
        kind={'Component':'Station','Sensor':'Sensor'}.get(n['label'])
        if not kind:
            exclusions[n['label']]+=1; continue
        prov=b.provenance(n['nodeId'],dict(sourceKind='seedCsv',fileName='imaks_data/kg_seed/nodes.csv',
                            sourceRowId=n['nodeId'],fileSha256=raw_sha256(nodepath)))
        props={k:n[k] for k in (['stationType','zone'] if kind=='Station' else ['sensorType','unit'])}
        props['sourceNodeId']=n['nodeId']
        mapped[n['nodeId']]=b.entity(n['name'],kind,props,prov)
        mapping.append([n['nodeId'],n['label'],n['name'],kind])
    edge_audit=[]
    for i,e in enumerate(es,2):
        a,z=byid[e['fromId']],byid[e['toId']]; triple=None
        if e['type']=='monitors' and {a['label'],z['label']}=={'Component','Sensor'}:
            station,sensor=(a,z) if a['label']=='Component' else (z,a)
            triple=(mapped[station['nodeId']],IM.hasSensor,mapped[sensor['nodeId']])
        elif e['type']=='feeds_into' and a['nodeId'] in mapped and z['nodeId'] in mapped:
            triple=(mapped[a['nodeId']],IM.feedsInto,mapped[z['nodeId']])
        if triple:
            prov=b.provenance('edge-'+str(i),dict(sourceKind='seedCsv',fileName='imaks_data/kg_seed/edges.csv',
                               sourceRowId=f'line:{i}',fileSha256=raw_sha256(edgepath)))
            b.add(*triple,str(prov))
        edge_audit.append(dict(line=i,type=e['type'],disposition='converted' if triple else 'excluded_from_structure'))
    folder=output or OUT/('baseline' if predictions and 'baseline' in predictions.name else 'llm' if predictions else 'seed')
    b.check(b.g,REPO_ROOT/'ontology_v1/shapes.ttl',folder/'structure_shacl.txt')
    b.check(b.g,REPO_ROOT/'guards/leakage_shapes.ttl',folder/'structure_leakage.txt')
    write_text(folder/'structure.ttl',b.g.serialize(format='turtle'))
    for d in manifest:
        node=iri(d['doc_id']); ev=d['file']+'#sha256='+d['file_sha256']
        b.add(node,RDF.type,IM.Document,ev)
        title=next(c['text'].splitlines()[0] for c in chunks if c['doc_id']==d['doc_id'])
        b.props(node,dict(identifier=d['doc_id'],title=title,sourcePath=d['file'],
                         sourceSha256=d['file_sha256'],pageCount=int(d['pages'])),ev)
    # Seed maintenance must get real document evidence to satisfy S8, not a made-up source.
    maint_units={u['cells']['Rule ID']:u for u in source_units.values() if u['cells'] and 'Rule ID' in u['cells']}
    maint_mapping=[]
    for n in ns:
        if n['label']!='Maintenance': continue
        ident=n['ruleId']; u=maint_units[ident]
        prov=b.provenance(n['nodeId'],dict(sourceKind='seedCsv',fileName='imaks_data/kg_seed/nodes.csv',
                            sourceRowId=n['nodeId'],fileSha256=raw_sha256(nodepath)))
        # Use a separate seed identity to preserve source wording alongside model output.
        node=b.entity(ident,'MaintenanceRule',dict(sourceNodeId=n['nodeId'],responseText=n['action'],
                          priority=n['priority'],extractionMethod='seedCsv'),prov)
        add_document_evidence(b,node,u)
        mapped[n['nodeId']]=node
        maint_mapping.append(dict(ruleId=ident,sourceNodeId=n['nodeId'],seedAction=n['action'],
                         documentAction=u['cells']['Action'],unit_id=u['unit_id']))
    for i,e in enumerate(es,2):
        a,z=byid[e['fromId']],byid[e['toId']]
        if {a['label'],z['label']}=={'Sensor','Maintenance'} and e['type'] in {'triggers','resolves'}:
            rule,sensor=(a,z) if a['label']=='Maintenance' else (z,a)
            prov=b.provenance('edge-'+str(i),dict(sourceKind='seedCsv',fileName='imaks_data/kg_seed/edges.csv',
                               sourceRowId=f'line:{i}',fileSha256=raw_sha256(edgepath)))
            b.add(mapped[rule['nodeId']],IM.appliesToSensor,mapped[sensor['nodeId']],str(prov))
            edge_audit[i-2]['disposition']='merged_appliesToSensor'
    for r in records:
        u=source_units[r['unit_id']]
        # Candidate graph keeps seed and extraction variants distinct and auditable.
        name='candidate-'+r['identifier']; node=iri(name)
        prov=add_document_evidence(b,node,u,r['sourceQuote'])
        b.add(node,RDF.type,IM[r['ruleClass']],str(prov))
        props={k:r.get(k) for k in ('conditionText','responseText','ruleSeverity','priority','extractionMethod')}
        props['identifier']=name
        props.update({k:Decimal(str(v)) for k,v in r.get('numeric',{}).items()})
        b.props(node,props,str(prov))
        for field,pred in [('sensorIds',IM.appliesToSensor),('actionTargets',IM.actionTarget)]:
            for value in r.get(field,[]): b.add(node,pred,iri(value),str(prov))
    b.check(b.g,REPO_ROOT/'ontology_v1/shapes.ttl',folder/'candidate_shacl.txt')
    write_text(folder/'candidate.ttl',b.g.serialize(format='turtle'))
    provenance=[dict(subject=s,predicate=p,object=o,evidence=sorted(v)) for (s,p,o),v in sorted(b.evidence.items())]
    if len(provenance)!=len(b.g): raise ValueError('A triple is missing provenance')
    write_jsonl(folder/'triple_provenance.jsonl',provenance)
    labels,relations=export(b.g,folder)
    summary=dict(profile='candidate_not_human_approved',nodes_by_class=dict(labels),relations_by_type=dict(relations),
        rdf_triples=len(b.g),triples_with_evidence=len(provenance),raw_nodes=len(ns),raw_edges=len(es),
        excluded_structure_nodes=dict(exclusions),prediction_count=len(records),
        shapes_sha256=sha256_file(REPO_ROOT/'ontology_v1/shapes.ttl'),
        ontology_sha256=sha256_file(REPO_ROOT/'ontology_v1/ontology.ttl'),
        predictions_sha256=sha256_file(predictions) if predictions else None,
        input_sha256={str(p.relative_to(REPO_ROOT)):raw_sha256(p) for p in (nodepath,edgepath)},
        human_review_complete=False,neo4j_loaded=False)
    write_json(folder/'summary.json',summary)
    write_jsonl(folder/'edge_audit.jsonl',edge_audit)
    write_json(folder/'maintenance_mapping.json',maint_mapping)
    write_csv(folder/'node_mapping.csv',['sourceNodeId','sourceClass','identifier','targetClass'],mapping)
    write_jsonl(folder/'review_queue.jsonl',[dict(identifier=r['identifier'],unit_id=r['unit_id'],
              first_reviewer='',second_reviewer='',decision='pending',notes='') for r in records])
    print(json.dumps(summary,ensure_ascii=False,indent=2))


def add_document_evidence(b,node,u,source_quote=None):
    quote_text=source_quote or u['text']
    props=dict(sourceKind='document',page=u['page'],textSha256=hashlib.sha256(quote_text.encode()).hexdigest(),
               fileSha256=u['source_file_sha256'],sourceQuote=source_quote or u['text'])
    if u['table_id']:
        props.update(tableId=u['table_id'],rowIndex=u['row_index'],colIndex=1,bbox=json.dumps(u['bbox']))
    else: props.update(charStart=u['char_start'],charEnd=u['char_end'])
    key=hashlib.sha256((str(node)+u['unit_id']).encode()).hexdigest()[:20]
    prov=b.provenance(key,props)
    b.add(node,IM.hasProvenance,prov,str(prov)); b.add(node,IM.sourceDocument,iri(u['doc_id']),str(prov))
    return prov


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--predictions',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args();build(a.predictions,a.output)
