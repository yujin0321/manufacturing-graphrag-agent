"""Pre-benchmark source-backed relation candidates; no gold, no causal promotion."""
import json
import hashlib
from collections import Counter
from pathlib import Path
from urllib.parse import quote
from rdflib import Graph,Namespace,RDF,RDFS,OWL,XSD,Literal,URIRef
from pyshacl import validate
from imaks_kg.kg.documents import units,read_jsonl
from imaks_kg.kg.build import iri
from imaks_kg.common.provenance import sha256_file
from imaks_kg.common.io_utils import write_json
from imaks_kg.common.raw_io import raw_csv_rows
from imaks_kg.settings import REPO_ROOT

IM=Namespace('https://example.org/imaks/v1#')
RC=Namespace('https://example.org/imaks/relation-review/v1#')
OUT=REPO_ROOT/'kg_build/pre_benchmark_relations_20261016'
SCHEMA=REPO_ROOT/'ontology_relation_review'
BASE=REPO_ROOT/'kg_build/openai_sol_v2_20261016/graph/candidate.ttl'
PRED=REPO_ROOT/'kg_build/openai_sol_v2_20261016/llm_predictions.jsonl'

# These are assistant-authored interpretations of source units, not a fresh API extraction.
SPECS=[
 ('REL-01','documentedAssociation','ST02_SEALING_CUR','ST04_PACKAGING_SPD','Current drift / speed reduction; shared electrical coupling. Direction in the claim does not prove causality.', ['SOP-001:p1:RULE-ST02-04','SOP-003:p1:table2:row2']),
 ('REL-02','requiresMonitoring','ST02_SEALING_CUR','ST04_PACKAGING_SPD','ST02 current WARNING: monitor ST04 speed.', ['SOP-001:p1:RULE-ST02-04']),
 ('REL-03','requiresRuleCheck','SOP-001::RULE-ST04-03','SOP-001::RULE-ST02-04','ST04 speed <1.00 m/s without operator command: verify referenced rule.', ['SOP-001:p2:RULE-ST04-03']),
 ('REL-04','requiresShutdown','ST02_SEALING_TMP','ST02_SEALING','Temperature >210°C: emergency stop.', ['SOP-001:p1:RULE-ST02-02']),
 ('REL-05','requiresShutdown','ST02_SEALING_TMP','ST03_LABELLING','Temperature >210°C: emergency stop.', ['SOP-001:p1:RULE-ST02-02']),
 ('REL-06','requiresShutdown','ST02_SEALING_TMP','ST04_PACKAGING','Temperature >210°C: emergency stop.', ['SOP-001:p1:RULE-ST02-02']),
 ('REL-07','documentedThermalEffect','ST02_SEALING','ST04_PACKAGING','Thermal fault at sealing: documented downstream speed reduction; not an empirically validated causal link.', ['SOP-001:p1:table1:row3']),
]

def schema():
    SCHEMA.mkdir(exist_ok=True)
    ontology='''@prefix rc: <https://example.org/imaks/relation-review/v1#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
rc: a owl:Ontology; owl:versionInfo "0.1.0-candidate" .
rc:RelationCandidate a owl:Class; rdfs:comment "Reified conditional source claim. Does not assert a direct operational or causal edge." .
'''
    for name in ['subject','object','relationType','supportedByRule','evidence']:
        ontology+=f'rc:{name} a owl:ObjectProperty .\n'
    for name in ['conditionText','reviewStatus','evidenceMode','novelty','sourceQuote','sourceUnit','sourceFileSha256','page']:
        ontology+=f'rc:{name} a owl:DatatypeProperty .\n'
    meanings={'documentedAssociation':'Document reports association; ordering follows source wording, not causal proof.',
        'requiresMonitoring':'Subject condition requires monitoring the object sensor.',
        'requiresRuleCheck':'Source rule directs checking target rule.',
        'requiresShutdown':'Subject sensor condition requires stopping target station.',
        'documentedThermalEffect':'Source describes a thermal fault effect; empirical causality is not validated.'}
    for name,meaning in meanings.items():ontology+=f'rc:{name} a owl:NamedIndividual; rdfs:comment "{meaning}" .\n'
    shapes='''@prefix rc: <https://example.org/imaks/relation-review/v1#> .
@prefix im: <https://example.org/imaks/v1#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
rc:CandidateShape a sh:NodeShape; sh:targetClass rc:RelationCandidate;
 sh:property [ sh:path rc:subject; sh:minCount 1; sh:maxCount 1; sh:nodeKind sh:IRI ];
 sh:property [ sh:path rc:object; sh:minCount 1; sh:maxCount 1; sh:nodeKind sh:IRI ];
 sh:property [ sh:path rc:relationType; sh:minCount 1; sh:maxCount 1; sh:in (rc:documentedAssociation rc:requiresMonitoring rc:requiresRuleCheck rc:requiresShutdown rc:documentedThermalEffect) ];
 sh:property [ sh:path rc:conditionText; sh:minCount 1; sh:maxCount 1; sh:datatype xsd:string; sh:minLength 1 ];
 sh:property [ sh:path rc:reviewStatus; sh:minCount 1; sh:maxCount 1; sh:in ("pending") ];
 sh:property [ sh:path rc:evidenceMode; sh:minCount 1; sh:maxCount 1; sh:in ("document_explicit") ];
 sh:property [ sh:path rc:evidence; sh:minCount 1; sh:node rc:EvidenceShape ];
 sh:property [ sh:path im:causallyAffects; sh:maxCount 0 ].
rc:EvidenceShape a sh:NodeShape;
 sh:property [ sh:path rc:sourceQuote; sh:minCount 1; sh:datatype xsd:string; sh:minLength 1 ];
 sh:property [ sh:path rc:sourceUnit; sh:minCount 1; sh:datatype xsd:string ];
 sh:property [ sh:path rc:sourceFileSha256; sh:minCount 1; sh:pattern "^[a-f0-9]{64}$" ];
 sh:property [ sh:path rc:page; sh:minCount 1; sh:datatype xsd:integer; sh:minInclusive 1 ].
'''
    (SCHEMA/'ontology.ttl').write_text(ontology,encoding='utf-8')
    branches=[]
    for kind,st,ot in [('documentedAssociation','Sensor','Sensor'),('requiresMonitoring','Sensor','Sensor'),
                       ('requiresShutdown','Sensor','Station'),('documentedThermalEffect','Station','Station')]:
        branches.append(f'[ sh:property [ sh:path rc:relationType; sh:hasValue rc:{kind} ]; sh:property [ sh:path rc:subject; sh:class im:{st} ]; sh:property [ sh:path rc:object; sh:class im:{ot} ] ]')
    rule='sh:or ( [ sh:class im:OperationalRule ] [ sh:class im:ThresholdRule ] [ sh:class im:MaintenanceRule ] [ sh:class im:AccessRule ] )'
    branches.append(f'[ sh:property [ sh:path rc:relationType; sh:hasValue rc:requiresRuleCheck ]; sh:property [ sh:path rc:subject; {rule} ]; sh:property [ sh:path rc:object; {rule} ] ]')
    shapes+='\nrc:CandidateShape sh:or ( '+' '.join(branches)+' ) .\n'
    (SCHEMA/'shapes.ttl').write_text(shapes,encoding='utf-8')

def endpoint(base,name):
    if '::' in name:return iri('candidate-'+name)
    return iri(name)

def check_endpoints(base,kind,s,o):
    types={'documentedAssociation':(IM.Sensor,IM.Sensor),'requiresMonitoring':(IM.Sensor,IM.Sensor),
           'requiresShutdown':(IM.Sensor,IM.Station),'documentedThermalEffect':(IM.Station,IM.Station)}
    if kind=='requiresRuleCheck':
        allowed={IM.OperationalRule,IM.ThresholdRule,IM.MaintenanceRule,IM.AccessRule}
        if not set(base.objects(s,RDF.type))&allowed or not set(base.objects(o,RDF.type))&allowed:raise ValueError('Rule endpoint missing')
    else:
        a,b=types[kind]
        if (s,RDF.type,a) not in base or (o,RDF.type,b) not in base:raise ValueError('Endpoint type mismatch')

def run():
    OUT.mkdir(parents=True,exist_ok=True);schema()
    frozen=sha256_file(PRED)
    base=Graph().parse(BASE);seed=Graph().parse(BASE.parent/'structure.ttl')
    us=units();source={u['unit_id']:u for u in us};pred=read_jsonl(PRED)
    _,rawnodes=raw_csv_rows(REPO_ROOT/'imaks_data/kg_seed/nodes.csv')
    safe_names={n['nodeId']:n['name'] for n in rawnodes if n['label'] in {'Sensor','Component'}}
    _,rawedges=raw_csv_rows(REPO_ROOT/'imaks_data/kg_seed/edges.csv')
    structural_edges=[dict(subject=safe_names[e['fromId']],object=safe_names[e['toId']],relation=e['type'],rule_ref=e['ruleRef'])
        for e in rawedges if e['fromId'] in safe_names and e['toId'] in safe_names]
    write_json(OUT/'raw_seed_structural_audit.json',structural_edges)
    write_json(OUT/'protocol_lock.json',dict(predictions_sha256=frozen,base_graph_sha256=sha256_file(BASE),
        scope='Pre-stage-7 relation review only; no benchmarks, QA, agents, new time-series search or gold input',
        method='assistant-authored source interpretation of frozen LLM rules plus source tables',
        novelty='Relative to seed and structured v2 graph, not new scientific causal discovery',
        specs_sha256=hashlib.sha256(json.dumps(SPECS,ensure_ascii=False).encode()).hexdigest()))
    graph=Graph();graph.bind('rc',RC);graph.bind('im',IM)
    records=[];ledger=[]
    for rid,kind,sname,oname,condition,unitids in SPECS:
        s=endpoint(base,sname);o=endpoint(base,oname);check_endpoints(base,kind,s,o)
        existing=[e for e in structural_edges if kind=='documentedAssociation' and e['relation']=='correlates_with'
                  and {e['subject'],e['object']}=={sname,oname}]
        novelty='existing_seed_relation_evidence_enrichment' if existing else 'new_structured_relation_not_new_document_fact'
        node=RC[rid];graph.add((node,RDF.type,RC.RelationCandidate))
        for p,v in [(RC.subject,s),(RC.object,o),(RC.relationType,RC[kind]),
                    (RC.conditionText,Literal(condition)),(RC.reviewStatus,Literal('pending')),
                    (RC.evidenceMode,Literal('document_explicit')),
                    (RC.novelty,Literal(novelty))]:graph.add((node,p,v))
        evidence=[];ruleids=[]
        for uid in unitids:
            u=source[uid];ev=RC['evidence-'+hashlib.sha256(uid.encode()).hexdigest()[:16]]
            graph.add((node,RC.evidence,ev))
            for p,v in [(RC.sourceUnit,Literal(uid)),(RC.sourceQuote,Literal(u['text'])),
                (RC.sourceFileSha256,Literal(u['source_file_sha256'])),(RC.page,Literal(u['page'],datatype=XSD.integer))]:graph.add((ev,p,v))
            evidence.append(u)
            for r in pred:
                if r['unit_id']==uid:
                    graph.add((node,RC.supportedByRule,endpoint(base,r['identifier'])));ruleids.append(r['identifier'])
        records.append(dict(identifier=rid,relation_type=kind,subject=sname,object=oname,condition=condition,
            evidence=evidence,supported_by_rules=ruleids,status='pending',
            seed_same_pair_predicates=sorted(str(p) for p in seed.predicates(s,o)),
            base_same_pair_predicates=sorted(str(p) for p in base.predicates(s,o)),
            novelty=novelty,raw_seed_semantic_matches=existing,
            confidence=None,empirical_causality_validated=False))
    # All new triples have an explicit candidate/unit evidence sidecar; retain full location metadata there.
    for t in graph:
        owners=[r['identifier'] for r in records if t[0]==RC[r['identifier']] or
                any(t[0]==RC['evidence-'+hashlib.sha256(e['unit_id'].encode()).hexdigest()[:16]] for e in r['evidence'])]
        if not owners:raise ValueError('Missing evidence owner')
        ledger.append(dict(triple=[x.n3() for x in t],candidate_ids=owners))
    combined=base+graph
    conforms,_,report=validate(combined,shacl_graph=Graph().parse(SCHEMA/'shapes.ttl'),inference='none')
    if not conforms:raise ValueError(report)
    graph.serialize(OUT/'relation_candidates.ttl',format='turtle')
    combined.serialize(OUT/'candidate_kg.ttl',format='turtle')
    Graph().serialize(OUT/'approved_relations.ttl',format='turtle')
    write_json(OUT/'candidates.json',records);write_json(OUT/'triple_evidence.json',ledger)
    write_json(OUT/'human_review.json',[dict(identifier=r['identifier'],candidate_graph_sha256=sha256_file(OUT/'relation_candidates.ttl'),
        first_reviewer='',second_reviewer='',decision='pending',notes='') for r in records])
    (OUT/'relation_shacl.txt').write_text(report,encoding='utf-8')
    excluded=[dict(subject='ST01/ST02/ST03 production chain',reason='Three feedsInto links already in seed; not new'),
        dict(subject='Server overheating → SCADA latency / apparent STUCK',reason='Non-Station target; retain existing rule text, no invented Station or causal edge'),
        dict(subject='Warehouse temperature → QC HOLD',reason='Quality target outside current ontology scope; retain rule text'),
        dict(subject='Shared HVAC dependencies',reason='HVAC asset identity and whether equipment is shared are unknown; no new shared-cause link'),
        dict(subject='RND humidity ↔ warehouse temperature',reason='Prior time-series observation was post-hoc and dominated by a single jump; not independently validated')]
    write_json(OUT/'deferred_and_existing.json',excluded)
    excluded.append(dict(subject='ST02 current / ST04 speed association',reason='Original seed correlates_with exists; REL-01 is evidence enrichment, excluded from new count'))
    write_json(OUT/'deferred_and_existing.json',excluded)
    # Screening coverage describes the deterministic cross-entity/reference filter, not exhaustive semantic recall.
    screening=[]
    for u in us:
        used=[r['identifier'] for r in records if u['unit_id'] in {e['unit_id'] for e in r['evidence']}]
        screening.append(dict(unit_id=u['unit_id'],selected_candidates=used,
            scope='inventoried source units; unselected units are not proof of absence of relations'))
    write_json(OUT/'source_inventory.json',screening)
    summary=dict(candidates=len(records),document_explicit=len(records),validated_new_causal_relations=0,
        existing_seed_relation_enrichments=sum(bool(r['raw_seed_semantic_matches']) for r in records),
        new_structured_candidates=sum(not r['raw_seed_semantic_matches'] for r in records),
        human_approved=0,relation_triples=len(graph),combined_triples=len(combined),
        new_relation_types=sorted({r['relation_type'] for r in records}),
        source_units_used=len({e['unit_id'] for r in records for e in r['evidence']}),
        source_units_in_inventory=len(us),relation_shacl_conforms=bool(conforms),
        evidence_coverage=len(ledger)/len(graph),rule_F1_unchanged=.861878453038674,
        benchmark_stage_started=False,api_calls=0,predictions_sha256=frozen)
    write_json(OUT/'summary.json',summary)
    assert frozen==sha256_file(PRED)
    assert not list(graph.triples((None,IM.causallyAffects,None)))
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':run()
