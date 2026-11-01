"""Offline scoped experiment: broad text links / explicit parser / RDF overlay.

No model calls, graph replacement or label reads. Scope: SOP-001 rule bodies.
"""
import json
import re
from pathlib import Path
from rdflib import Graph, Namespace, URIRef, Literal, RDF, OWL, RDFS
from pyshacl import validate
from imaks_kg.rag import vector as v, comparison as c, graph_v2 as gv

EX=Namespace('https://example.org/imaks/explicit-reference-experiment/v1#')
OUT=v.REPO_ROOT/'kg_build/explicit_reference_20261027'
SHAPES='''@prefix ex: <https://example.org/imaks/explicit-reference-experiment/v1#> .
@prefix im: <https://example.org/imaks/v1#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:ClaimShape a sh:NodeShape ; sh:targetClass ex:ReferenceClaim ;
 sh:property [ sh:path ex:subject ; sh:minCount 1 ; sh:maxCount 1 ; sh:class im:Rule ] ;
 sh:property [ sh:path ex:object ; sh:minCount 1 ; sh:maxCount 1 ; sh:class im:Rule ] ;
 sh:property [ sh:path ex:sourceChunk ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:string ] ;
 sh:property [ sh:path ex:quote ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:string ] ;
 sh:property [ sh:path ex:chunkSha256 ; sh:minCount 1 ; sh:maxCount 1 ; sh:pattern "^[0-9a-f]{64}$" ] ;
 sh:sparql [ sh:message "Claim must have its matching direct edge and cannot reference itself" ;
 sh:select """PREFIX ex: <https://example.org/imaks/explicit-reference-experiment/v1#>
 SELECT $this WHERE { $this ex:subject ?s ; ex:object ?o .
 FILTER (?s = ?o || NOT EXISTS { ?s ex:requiresRuleCheck ?o }) }""" ] .
ex:EdgeShape a sh:NodeShape ; sh:targetSubjectsOf ex:requiresRuleCheck ;
 sh:class im:Rule ;
 sh:property [ sh:path ex:requiresRuleCheck ; sh:class im:Rule ] ;
 sh:sparql [ sh:message "Every edge requires a provenance claim" ;
 sh:select """PREFIX ex: <https://example.org/imaks/explicit-reference-experiment/v1#>
 SELECT $this WHERE { $this ex:requiresRuleCheck ?o .
 FILTER NOT EXISTS { ?claim a ex:ReferenceClaim ; ex:subject $this ; ex:object ?o } }""" ] .
'''


def main():
 OUT.mkdir(parents=True,exist_ok=False)
 base=c.load_graph();sources,_=v.source_records();corpus={r['chunk_id']:r for r in sources}
 ontology=Graph().parse(v.REPO_ROOT/'ontology_v1/ontology.ttl')
 links=c.source_links(base,sources)
 node_by_rule={}
 for n in base.subjects(c.IM.identifier,None):
  ident=str(base.value(n,c.IM.identifier))
  if ident.startswith('candidate-SOP-001::RULE-'):
   node_by_rule[ident.split('::')[-1]]=n
 # Predeclared narrow extraction grammar, not generic imperative understanding.
 pattern=re.compile(r'\b(?:verify|check)\s+(RULE-[A-Z0-9]+-\d+)\b',re.I)
 scoped=[r for r in sources if r['doc_id']=='SOP-001' and r['kind']=='rule']
 extracted=[]
 for r in scoped:
  match=re.match(r'(RULE-[A-Z0-9]+-\d+):',r['text'])
  if not match:raise ValueError('Unknown rule heading')
  src=match[1]
  for dst in pattern.findall(r['text']):
   dst=dst.upper()
   if src not in node_by_rule or dst not in node_by_rule:raise ValueError('Unresolved rule')
   extracted.append({'source_rule':src,'target_rule':dst,'s':str(node_by_rule[src]),'o':str(node_by_rule[dst]),
                     'chunk_id':r['chunk_id'],'quote':r['text'],'chunk_sha256':r['text_sha256']})
 # Explicitly reviewed source assertion; narrow single-case oracle, not unseen gold.
 reviewed={('RULE-ST04-03','RULE-ST02-04')}
 assert {(r['source_rule'],r['target_rule']) for r in extracted}==reviewed
 schema=Graph();schema.add((EX.requiresRuleCheck,RDF.type,OWL.ObjectProperty))
 schema.add((EX.requiresRuleCheck,RDFS.domain,c.IM.Rule));schema.add((EX.requiresRuleCheck,RDFS.range,c.IM.Rule))
 schema.add((EX.requiresRuleCheck,RDFS.comment,Literal('Source rule explicitly instructs verification of target rule; not causality, execution or bidirectional equivalence.')))
 schema.add((EX.ReferenceClaim,RDF.type,OWL.Class))
 for p in [EX.subject,EX.object]:schema.add((p,RDF.type,OWL.ObjectProperty))
 for p in [EX.sourceChunk,EX.quote,EX.chunkSha256]:schema.add((p,RDF.type,OWL.DatatypeProperty))
 overlay=Graph();overlay.bind('ex',EX)
 for i,r in enumerate(extracted):
  s,o=URIRef(r['s']),URIRef(r['o']);claim=EX['claim'+str(i+1)]
  overlay.add((s,EX.requiresRuleCheck,o));overlay.add((claim,RDF.type,EX.ReferenceClaim))
  for p,value in [(EX.subject,s),(EX.object,o),(EX.sourceChunk,Literal(r['chunk_id'])),(EX.quote,Literal(r['quote'])),(EX.chunkSha256,Literal(r['chunk_sha256']))]:overlay.add((claim,p,value))
 shapes=Graph().parse(data=SHAPES,format='turtle')
 def structural(g):
  ok,_,report=validate(base+g,shacl_graph=shapes,ont_graph=ontology+schema,inference='none')
  return bool(ok),report
 def evidence_valid(g):
  claims=list(g.subjects(RDF.type,EX.ReferenceClaim))
  pairs=[]
  for claim in claims:
   vals={k:list(g.objects(claim,EX[k])) for k in ['subject','object','sourceChunk','quote','chunkSha256']}
   if any(len(x)!=1 for x in vals.values()):return False
   vals={k:x[0] for k,x in vals.items()};row=corpus.get(str(vals['sourceChunk']))
   if not row or str(vals['quote'])!=row['text'] or str(vals['chunkSha256'])!=row['text_sha256']:return False
   if not any(str(vals['subject'])==r['s'] and str(vals['object'])==r['o'] and str(vals['sourceChunk'])==r['chunk_id'] for r in extracted):return False
   pairs.append((vals['subject'],vals['object']))
  return set(pairs)==set(g.subject_objects(EX.requiresRuleCheck)) and bool(pairs)
 ok,report=structural(overlay);assert ok and evidence_valid(overlay)
 (OUT/'shacl.txt').write_text(report,encoding='utf-8')
 overlay.serialize(OUT/'candidate_overlay.ttl',format='turtle');schema.serialize(OUT/'candidate_ontology.ttl',format='turtle')
 (OUT/'candidate_shapes.ttl').write_text(SHAPES,encoding='utf-8')
 v.write(OUT/'reference_manifest.json',extracted)
 # Arm A duplicates the existing graph_v2 text-reference matching expression,
 # scoped to these rule nodes; no ranking, graph traversal cap or generation here.
 broad=[]
 for rid,node in sorted(node_by_rule.items()):
  texts=[str(x) for p in [c.IM.conditionText,c.IM.responseText] for x in base.objects(node,p)]
  texts += [corpus[cid]['text'] for cid in links.get(node,[])]
  text='\n'.join(texts)
  for target,other in sorted(node_by_rule.items()):
   if other!=node and any(a.startswith(('RULE-','MAINT-')) and gv.matches(a,text) for a in gv.aliases(base,other)):
    broad.append((rid,target))
 precise=[(r['source_rule'],r['target_rule']) for r in extracted]
 id_by_node={n:rid for rid,n in node_by_rule.items()}
 rdf=[(id_by_node[s],id_by_node[o]) for s,o in overlay.subject_objects(EX.requiresRuleCheck)]
 queries={}
 for name,pairs in [('A_existing_text_reference',broad),('B_explicit_text_parser',precise),('C_RDF_candidate',rdf)]:
  queries[name]={'pairs':[list(x) for x in sorted(pairs)],
     'forward_ST04_03':sorted(o for s,o in pairs if s=='RULE-ST04-03'),
     'reverse_ST02_04':sorted(s for s,o in pairs if o=='RULE-ST02-04')}
 assert set(precise)==set(rdf)
 # Live RDF query, not only Python pair lookup.
 forward=list(overlay.query('SELECT ?target WHERE { ?source <'+str(EX.requiresRuleCheck)+'> ?target }',initBindings={'source':node_by_rule['RULE-ST04-03']}))
 reverse=list(overlay.query('SELECT ?source WHERE { ?source <'+str(EX.requiresRuleCheck)+'> ?target }',initBindings={'target':node_by_rule['RULE-ST02-04']}))
 assert [x[0] for x in forward]==[node_by_rule['RULE-ST02-04']]
 assert [x[0] for x in reverse]==[node_by_rule['RULE-ST04-03']]
 # Controlled faults: SHACL checks structure, source audit checks meaning.
 claim=EX.claim1;s=node_by_rule['RULE-ST04-03'];o=node_by_rule['RULE-ST02-04']
 def copy():return Graph()+overlay
 mutations={}
 bad=copy();bad.remove((claim,EX.quote,None));mutations['missing_quote']=bad
 bad=copy();bad.remove((s,EX.requiresRuleCheck,o));bad.add((o,EX.requiresRuleCheck,s));bad.set((claim,EX.subject,o));bad.set((claim,EX.object,s));mutations['reversed_with_matching_claim']=bad
 bad=copy();bad.set((claim,EX.chunkSha256,Literal('0'*64)));mutations['wrong_source_hash']=bad
 bad=copy();bad.set((claim,EX.quote,Literal('Invented source directive')));mutations['fabricated_quote']=bad
 bad=copy();bad.remove((s,EX.requiresRuleCheck,o));sensor=next(base.subjects(RDF.type,c.IM.Sensor));bad.add((s,EX.requiresRuleCheck,sensor));bad.set((claim,EX.object,sensor));mutations['sensor_as_target']=bad
 bad=copy();bad.remove((s,EX.requiresRuleCheck,o));bad.add((s,EX.requiresRuleCheck,s));bad.set((claim,EX.object,s));mutations['self_reference']=bad
 bad=copy();bad.add((o,EX.requiresRuleCheck,s));mutations['edge_without_claim']=bad
 fault_results={name:{'shacl_conforms':structural(g)[0],'evidence_valid':evidence_valid(g)} for name,g in mutations.items()}
 assert all(not (r['shacl_conforms'] and r['evidence_valid']) for r in fault_results.values())
 # Parser controls show why gains cannot be attributed to RDF alone.
 samples={'explicit':'verify RULE-ST02-04','cooccurrence':'RULE-ST02-04 and RULE-ST04-03 are listed here',
          'unsupported_paraphrase':'consult the guidance in RULE-ST02-04'}
 parser_controls={k:pattern.findall(t) for k,t in samples.items()}
 summary={'scope':'SOP-001 rule bodies; source-reviewed single explicit directive, development experiment',
   'rules_in_scope':len(scoped),'base_triples':len(base),'overlay_triples':len(overlay),'explicit_edges':len(rdf),
   'queries':queries,'valid_overlay_shacl':ok,'valid_overlay_evidence':True,'fault_tests':fault_results,
   'parser_controls':parser_controls,'answer_generation_calls':0,'api_calls':0,
   'RDF_accuracy_improvement_over_precise_parser':False,
   'hashes':{p:v.digest((v.REPO_ROOT/p).read_bytes()) for p in [c.KG_REL,'src/imaks_kg/rag/graph_v2.py','ontology_v1/ontology.ttl','ontology_v1/shapes.ttl']},
   'source_sha256':v.digest(v.SOURCE.read_bytes()),'script_sha256':v.digest(Path(__file__).read_bytes())}
 v.write(OUT/'summary.json',summary)
 v.write(OUT/'complete.json',{p.name:v.digest(p.read_bytes()) for p in OUT.iterdir() if p.is_file()})
 print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
