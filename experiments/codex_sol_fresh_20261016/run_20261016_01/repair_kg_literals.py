"""Preserve first KG/report; align enum literals with supplied SHACL lexical representation."""
import pathlib,sys,json,hashlib,collections
O=pathlib.Path(__file__).resolve().parent;sys.path.insert(0,str(O/'vendor'))
from rdflib import Graph,Namespace,Literal,RDF,URIRef
from pyshacl import validate
I=O.parent/'input';IM=Namespace('https://example.org/imaks/v1#')
for n in ['kg.candidate.v2.ttl','shacl.v2.report.ttl','shacl.v2.report.txt','kg_repair.json']:assert not (O/n).exists(),n
g=Graph().parse(O/'kg.candidate.ttl',format='turtle');changes=collections.Counter()
for prop in ['stationType','sensorType','sourceKind']:
    for s,p,v in list(g.triples((None,IM[prop],None))):
        if isinstance(v,Literal) and v.datatype:
            g.remove((s,p,v));g.add((s,p,Literal(str(v))));changes[prop]+=1
g.serialize(O/'kg.candidate.v2.ttl',format='turtle')
# Validate the saved graph, not just the in-memory construction.
saved=Graph().parse(O/'kg.candidate.v2.ttl',format='turtle')
ok,report,txt=validate(saved,shacl_graph=Graph().parse(I/'shapes.ttl',format='turtle'),ont_graph=Graph().parse(I/'ontology.ttl',format='turtle'),inference='none',advanced=True,abort_on_first=False,allow_infos=False,allow_warnings=False)
report.serialize(O/'shacl.v2.report.ttl',format='turtle');(O/'shacl.v2.report.txt').write_text(txt,encoding='utf-8')
out=dict(reason='First pySHACL run matched enum values by RDF term identity: explicitly xsd:string literals differed from simple literals in supplied sh:in lists. Re-render those three enum predicates as simple literals. Ontology/shapes and original predictions unchanged.',changes=dict(changes),conforms=bool(ok),validation_results=len(list(report.subjects(RDF.type,URIRef('http://www.w3.org/ns/shacl#ValidationResult')))),triples=len(saved),candidate_sha256=hashlib.sha256((O/'kg.candidate.v2.ttl').read_bytes()).hexdigest(),previous_candidate_preserved=True,source_semantics_changed=False)
(O/'kg_repair.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(out,ensure_ascii=False))
