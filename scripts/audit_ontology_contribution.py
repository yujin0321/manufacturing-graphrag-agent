"""Read-only ontology/KG contribution audit; no API or gold-label access."""
from collections import Counter
from pathlib import Path
import json
from rdflib import Graph, RDF, OWL, URIRef
from pyshacl import validate
from imaks_kg.common.raw_io import raw_csv_rows, raw_sha256
from imaks_kg.rag import vector as v, comparison as c


def main():
    root=v.REPO_ROOT; im=c.IM; g=c.load_graph()
    ontology=Graph().parse(root/'ontology_v1/ontology.ttl')
    shapes=Graph().parse(root/'ontology_v1/shapes.ttl')
    _,nodes=raw_csv_rows(root/'imaks_data/kg_seed/nodes.csv')
    _,edges=raw_csv_rows(root/'imaks_data/kg_seed/edges.csv')
    short=lambda x:str(x).split('#')[-1]
    classes=Counter(short(t) for s,t in g.subject_objects(RDF.type))
    relations=Counter(short(p) for s,p,o in g if p!=RDF.type and isinstance(o,URIRef))
    declared={short(n) for n in ontology.subjects(RDF.type,OWL.ObjectProperty)}
    rules=set().union(*(set(g.subjects(RDF.type,im[k])) for k in ['OperationalRule','ThresholdRule','MaintenanceRule','AccessRule']))
    def describe(n):
        return {'iri':str(n),'identifier':[str(x) for x in g.objects(n,im.identifier)],
            'sensors':[str(x) for x in g.objects(n,im.appliesToSensor)],
            'documents':[str(x) for x in g.objects(n,im.sourceDocument)],
            'provenance':[str(x) for x in g.objects(n,im.hasProvenance)],
            'conditions':[str(x) for x in g.objects(n,im.conditionText)],
            'actions':[str(x) for x in g.objects(n,im.responseText)],
            'targets':[str(x) for x in g.objects(n,im.actionTarget)]}
    samples={}
    for fragment in ['RULE-ST01-01','MAINT-05','RULE-ST02-02','RULE-ST04-03']:
        samples[fragment]=[describe(n) for n in sorted(rules,key=str) if any(fragment in str(i) for i in g.objects(n,im.identifier))]
    sensor=next(n for n in g.subjects(im.identifier,None) if str(g.value(n,im.identifier))=='ST01_FILLING_FLW')
    samples['sensor_membership']={'sensor':str(sensor),'stations':[str(s) for s in g.subjects(im.hasSensor,sensor)]}
    ok,_,report=validate(g,shacl_graph=shapes,ont_graph=ontology,inference='none')
    result={'scope':'current original Yewon v2; excludes later reviewed relation graph and detection overlay',
      'raw_node_count':len(nodes),'raw_edge_rows':len(edges),'raw_classes':dict(Counter(n['label'] for n in nodes)),
      'raw_edge_types':dict(Counter(e['type'] for e in edges)),
      'v2_triples':len(g),'v2_classes':dict(sorted(classes.items())),'v2_object_edges':dict(sorted(relations.items())),
      'declared_object_properties_not_instantiated':sorted(declared-set(relations)),
      'rule_nodes':len(rules),'rules_with_document':sum(bool(list(g.objects(n,im.sourceDocument))) for n in rules),
      'rules_with_provenance':sum(bool(list(g.objects(n,im.hasProvenance))) for n in rules),
      'rules_with_condition_text':sum(bool(list(g.objects(n,im.conditionText))) for n in rules),
      'shacl_conforms':bool(ok),'samples':samples,
      'hashes':{p:v.digest((root/p).read_bytes()) for p in [c.KG_REL,'ontology_v1/ontology.ttl','ontology_v1/shapes.ttl']},
      'raw_hashes':{name:raw_sha256(root/'imaks_data/kg_seed'/name) for name in ['nodes.csv','edges.csv']}}
    out=root/'evaluation/ontology_contribution_20261027';out.mkdir(parents=True,exist_ok=True)
    v.write(out/'audit.json',result);(out/'shacl.txt').write_text(report,encoding='utf-8')
    print(json.dumps({k:val for k,val in result.items() if k not in ['samples','hashes','raw_hashes']},ensure_ascii=False,indent=2))
    print(json.dumps(samples,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
