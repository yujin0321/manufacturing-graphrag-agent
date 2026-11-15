"""Controlled offline XAI faults/valid controls, not a model accuracy benchmark."""
from collections import Counter
from copy import copy, deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

from rdflib import Graph, URIRef

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from imaks_kg.rag import claim_binding as cb, comparison as c, decision_evidence as d
from imaks_kg.rag import document_claims as dc, evidence_paths as ep, incident_tools, rule_explanations as rx
from imaks_kg.rag import team_runtime as rt, vector as v

OUT = ROOT / 'kg_build/xai_extensions_20261115'


def source_packet(records):
    return {'selected_ids':[row['chunk_id'] for row in records], 'sources':records,
            'context':'\n\n'.join(row['text'] for row in records)}


def main():
    preserved = {path.relative_to(ROOT).as_posix(): v.digest(path.read_bytes())
                 for path in (ROOT/'kg_build/graphrag_live').glob('team_*_20261113_01/answer.json')}
    cases=[]
    def case(group, name, expected, function):
        # Unexpected exceptions fail the run; they are not scored as detection.
        actual=bool(function())
        cases.append({'group':group,'case':name,'expected_allow':expected,'actual_allow':actual,'passed':actual==expected})
    store=rt.store()
    evidence=incident_tools.get_incident_evidence(store,{'incident_id':store.incidents[0]['id']})
    rows,sha=d.observations(evidence['incident']['sensor_id'])
    proof=d.build(evidence,store,rows=rows,input_sha256=sha)
    catalog=cb.build_catalog(evidence,proof,store)
    def grounded(change=None):
        supplied=deepcopy(evidence)
        if change:change(supplied)
        return d.build(supplied,store,rows=rows,input_sha256=sha)['status']=='consistent'
    case('incident_grounding','valid_sealed_observation',True,lambda:grounded())
    case('incident_grounding','altered_trigger_value',False,lambda:grounded(lambda e:e['alarms'][0].update(trigger_value='99999')))
    case('incident_grounding','altered_unit',False,lambda:grounded(lambda e:e['alarms'][0].update(unit='invented-unit')))
    case('incident_grounding','missing_alarm',False,lambda:grounded(lambda e:e['alarms'].pop()))
    case('incident_grounding','missing_document',False,lambda:grounded(lambda e:e['untrusted_reference_documents'].clear()))
    case('incident_grounding','altered_source_text',False,lambda:grounded(lambda e:e['untrusted_reference_documents'][0].update(text='fabricated')))

    observation=next(cl for cl in catalog['claims'] if cl['claim_type']=='observation')
    recommendation=next(cl for cl in catalog['claims'] if cl['claim_type']=='recommendation')
    def path_check(claim, mutation=None):
        target=copy(store)
        target.base=Graph()
        target.overlay=Graph()
        for triple in store.base:target.base.add(triple)
        for triple in store.overlay:target.overlay.add(triple)
        if mutation:mutation(target)
        return ep.build([claim],evidence,proof,target)['claims'][0]['status']=='complete'
    case('graph_paths','valid_sensor_path',True,lambda:path_check(observation))
    case('graph_paths','valid_document_branch',True,lambda:path_check(recommendation))
    event=store.event_node(evidence['incident']['id'])
    sensor=next(store.overlay.subjects(c.IM.triggers,event))
    node=URIRef(recommendation['evidence_refs'][0]['node'])
    def reverse(target):
        target.overlay.remove((sensor,c.IM.triggers,event));target.overlay.add((event,c.IM.triggers,sensor))
    case('graph_paths','reversed_sensor_edge',False,lambda:path_check(observation,reverse))
    case('graph_paths','missing_event_rule',False,lambda:path_check(recommendation,lambda s:s.overlay.remove((event,URIRef(ep.DET+'matchedRule'),node))))
    case('graph_paths','missing_provenance',False,lambda:path_check(recommendation,lambda s:s.base.remove((node,c.IM.hasProvenance,None))))
    case('graph_paths','missing_source_document',False,lambda:path_check(recommendation,lambda s:s.base.remove((node,c.IM.sourceDocument,None))))
    bad=deepcopy(recommendation)
    next(ref for ref in bad['evidence_refs'] if ref['kind']=='document_chunk')['page']+=1
    fields=('incident_id','claim_type','text','evidence_refs','values','validation')
    bad['claim_id']='CLM-'+v.digest(v.encoded({key:bad[key] for key in fields}))[:16]
    case('graph_paths','rehashed_wrong_page',False,lambda:path_check(bad))

    chosen=[next(cl['claim_id'] for cl in cb.selector_view(catalog) if cl['claim_type']==kind)
            for kind in ('observation','condition','recommendation')]
    def incident_select(selection):
        return cb.bind(json.dumps(selection),catalog,'사건 설명')['status']=='bound'
    case('incident_selection','valid_claim_ids',True,lambda:incident_select({'claim_ids':chosen}))
    case('incident_selection','unknown_claim',False,lambda:incident_select({'claim_ids':chosen+['CLM-unknown']}))
    case('incident_selection','duplicate_claim',False,lambda:incident_select({'claim_ids':chosen+chosen[:1]}))
    case('incident_selection','extra_free_prose',False,lambda:incident_select({'claim_ids':chosen,'answer':'실제 조치 완료'}))
    case('incident_selection','missing_observation',False,lambda:incident_select({'claim_ids':chosen[1:]}))

    records=list(dc.canonical_rows().values())
    selected=next(row for row in records if 'MAINT-02' in row['text'])
    doc=dc.build(source_packet([selected]))
    cid=doc['claims'][0]['claim_id']
    def doc_select(selection,cat=doc):
        return dc.bind(json.dumps(selection),cat)['status']=='bound'
    case('document_claims','valid_frozen_excerpt',True,lambda:doc_select({'claim_ids':[cid]}))
    case('document_claims','unknown_excerpt',False,lambda:doc_select({'claim_ids':['DCL-unknown']}))
    case('document_claims','extra_applied_conclusion',False,lambda:doc_select({'claim_ids':[cid],'answer':'고장 해결'}))
    case('document_claims','duplicate_excerpt',False,lambda:doc_select({'claim_ids':[cid,cid]}))
    other=dc.build(source_packet([records[-1]]))['claims'][0]['claim_id']
    case('document_claims','different_retrieval_excerpt',False,lambda:doc_select({'claim_ids':[other]}))
    for label,mutate in [('fabricated_quote',lambda cl:cl.update(text='실제 수리 완료')),
                         ('wrong_page',lambda cl:cl['source'].update(page=-1)),
                         ('wrong_file_hash',lambda cl:cl['source'].update(source_file_sha256='0'*64)),
                         ('wrong_parent',lambda cl:cl['source'].update(parent_chunk_id='wrong'))]:
        changed=deepcopy(doc);claim=changed['claims'][0];mutate(claim)
        claim['claim_id']='DCL-'+v.digest(v.encoded(dc.body(claim)))[:16]
        changed['catalog_sha256']=v.digest(v.encoded(dc.payload(changed)))
        case('document_claims','rehashed_'+label,False,lambda cat=changed:doc_select({'claim_ids':[cat['claims'][0]['claim_id']]},cat))

    # Closure controls include censoring, not just ordinary releases.
    start=datetime(2026,1,1)
    def samples(seconds):
        return [{'timestamp':(start+timedelta(seconds=t)).isoformat(),'value':'5','sensor_id':'S','unit':'A'} for t in seconds]
    data=samples([0,30,60]);alarm={'trigger_at':data[0]['timestamp'],'last_positive_at':data[0]['timestamp']}
    case('closure','valid_rule_release',True,lambda:rx.closure(data,alarm,[True,False,False],clear=2)['state']=='consistent')
    case('closure','wrong_last_positive',False,lambda:rx.closure(data,{**alarm,'last_positive_at':data[1]['timestamp']},[True,False,False],clear=2)['state']=='consistent')
    case('closure','fabricated_early_normal_confirmation',False,lambda:rx.closure(data,{**alarm,'status':'recovered','normal_confirmed_at':data[1]['timestamp'],'closed_at':data[1]['timestamp']},[True,False,False],clear=2)['state']=='consistent')
    gap=samples([0,90]);open_data=samples([0,30])
    case('closure','gap_is_unconfirmed',True,lambda:rx.closure(gap,alarm,[True,True])['closure_kind']=='data_gap_unconfirmed')
    case('closure','data_end_is_not_recovery',True,lambda:rx.closure(open_data,{**alarm,'last_positive_at':open_data[1]['timestamp']},[True,True])['closure_kind']=='open_at_data_end')

    inventory=Counter()
    for row in records:
        cat=dc.build(source_packet([row]),token_budget=12000)
        if not cat['claims'] or cat['truncated']:raise ValueError('Single-row catalog could not be represented')
        inventory['retrieval_rows']+=1
        for claim in cat['claims']:
            if dc.bind(json.dumps({'claim_ids':[claim['claim_id']]}),cat)['status']!='bound':raise ValueError('Canonical document control failed')
            inventory['exact_excerpt_claims']+=1
    after={name:v.digest((ROOT/name).read_bytes()) for name in preserved}
    if after!=preserved:raise ValueError('Original answers changed')
    totals=Counter()
    for item in cases:
        totals['valid_controls' if item['expected_allow'] else 'faults']+=1
        totals['valid_allowed' if item['expected_allow'] and item['actual_allow'] else
               'valid_blocked' if item['expected_allow'] else 'fault_missed' if item['actual_allow'] else 'fault_detected']+=1
    totals.update(cases=len(cases),passed=sum(item['passed'] for item in cases))
    report={'version':'xai-contract-evaluation-v1-20261115','new_api_calls':0,'gold_loaded':False,
            'code_sha256':{module.__name__:v.digest(Path(module.__file__).read_bytes()) for module in (cb,d,dc,ep,rx)},
            'fixed_chunk_file_sha256':v.digest(v.SOURCE.read_bytes()),'fixed_KG_sha256':v.digest((ROOT/c.KG_REL).read_bytes()),
            'scope':'controlled development faults; not QA accuracy, field reliability or held-out generalization',
            'cases':cases,'totals':dict(totals),'document_inventory':dict(inventory),
            'original_answer_hashes_preserved':preserved,'all_passed':all(item['passed'] for item in cases)}
    v.write(OUT/'contract_evaluation.json',report)
    print(json.dumps({'totals':dict(totals),'document_inventory':dict(inventory),'original_answers_preserved':len(preserved)},ensure_ascii=False))
    if not report['all_passed']:raise SystemExit(1)


if __name__=='__main__':main()
