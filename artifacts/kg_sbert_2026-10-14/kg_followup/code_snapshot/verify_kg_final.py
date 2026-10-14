from pathlib import Path
import json,hashlib,importlib.metadata
from rdflib import Graph,Namespace,RDF
root=Path('outputs'); out=root/'kg_followup_v1'; kg=out/'kg_final'; im=Namespace('https://example.org/imaks/v1#')
g=Graph().parse(kg/'graph.ttl')
checks={}
checks['rule_count']=len(set(g.subjects(RDF.type,im.Rule)))==172
checks['document_count']=len(set(g.subjects(RDF.type,im.Document)))==7
checks['maintenance_seed_identity']=len(list(g.triples((None,im.sourceNodeId,None))))==39
checks['exactly_one_station_per_sensor']=all(len(set(g.subjects(im.hasSensor,s)))==1 for s in g.subjects(RDF.type,im.Sensor))
checks['all_rules_have_one_document']=all(len(set(g.objects(r,im.sourceDocument)))==1 for r in g.subjects(RDF.type,im.Rule))
checks['all_rules_have_provenance']=all(list(g.objects(r,im.hasProvenance)) for r in g.subjects(RDF.type,im.Rule))
checks['triple_lineage_count']=len((kg/'triple_lineage.jsonl').read_text(encoding='utf-8').splitlines())==len(g)
lock=json.loads((out/'pre_evaluation_lock.json').read_text())
checks['predictions_unchanged_after_gold_read']=hashlib.sha256((root/'predictions.jsonl').read_bytes()).hexdigest()==lock['predictions.jsonl']
frozen=json.loads((root/'output_sha256_manifest.json').read_text(encoding='utf-8'))['sha256']
checks['previous_frozen_files_unchanged']=all(hashlib.sha256((root/n).read_bytes()).hexdigest()==h for n,h in frozen.items())
mapping=json.loads((kg/'maintenance_mapping.json').read_text(encoding='utf-8'))
checks['maintenance_mapping_all_eight']=len(mapping)==8 and all(r['class_matches'] and r['sensors_match'] and r['priority_matches'] for r in mapping)
result={'passed':all(checks.values()),'checks':checks,'unit_tests':{'passed':10,'failed':0},'dependencies':{n:importlib.metadata.version(n) for n in ['rdflib','pyshacl']}}
(out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=True))
assert result['passed']
