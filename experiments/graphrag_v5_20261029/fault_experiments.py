"""ADD-07/08: independent copies only; never change the frozen KG."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent.parent
sys.path.insert(0,str(REPO/'src'))
from rdflib import Graph,URIRef,Literal
from pyshacl import validate
from imaks_kg.rag import comparison as c,vector as v,retrieval_v5 as r5,retrieval_v3 as r3

def main():
    out=ROOT/'reports/fault_injection';out.mkdir(parents=True,exist_ok=False)
    original=c.load_graph();source=v.REPO_ROOT/c.KG_REL;before=v.digest(source.read_bytes())
    baseline=Graph();baseline+=original
    node=next(n for n,o in original.subject_objects(c.IM.identifier) if str(o)=='candidate-SOP-001::RULE-ST02-02')
    shapes=Graph().parse(ROOT/'ontology_v1/shapes.ttl');ont=Graph().parse(ROOT/'ontology_v1/ontology.ttl')
    def inspect(graph):
        ok,_,report=validate(graph,shacl_graph=shapes,ont_graph=ont,inference='none')
        links,audit=r5.validated_provenance(graph,r3.row_corpus())
        return {'shacl_conforms':bool(ok),'shacl_report':report,
                'action_targets':sorted(map(str,graph.objects(node,c.IM.actionTarget))),
                'source_documents':sorted(map(str,graph.objects(node,c.IM.sourceDocument))),
                'provenance':sorted(map(str,graph.objects(node,c.IM.hasProvenance))),
                'validated_rows':links.get(str(node),[]),
                'node_provenance_audit':[x for x in audit if x['node']==str(node)]}
    reports={'baseline':inspect(baseline)}
    removed=Graph();removed+=original;removed.remove((node,c.IM.sourceDocument,None))
    reports['ADD-07']=inspect(removed)
    badtarget=Graph();badtarget+=original
    sensor=next(original.objects(node,c.IM.appliesToSensor));badtarget.add((node,c.IM.actionTarget,sensor))
    reports['ADD-08-type']=inspect(badtarget)
    badhash=Graph();badhash+=original
    prov=next(original.objects(node,c.IM.hasProvenance));quote=str(original.value(prov,c.IM.sourceQuote))
    existing=str(original.value(prov,c.IM.textSha256));replacement=('0' if existing[0]!='0' else '1')+existing[1:]
    badhash.set((prov,c.IM.textSha256,Literal(replacement)))
    reports['ADD-08-hash']=inspect(badhash)
    reports['preservation']={'original_sha256_before':before,'original_sha256_after':v.digest(source.read_bytes()),
        'unchanged':before==v.digest(source.read_bytes()),'new_experimental_discovery':False,
        'scope':'Repeatable validation of existing documented failure modes; not an LLM QA score.'}
    v.write(out/'results.json',reports)
    print(json.dumps({k:{a:b for a,b in val.items() if a in ['shacl_conforms','validated_rows','unchanged']}
                      for k,val in reports.items()},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
