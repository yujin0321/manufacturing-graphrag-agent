"""Validate paired, externally generated answers. Does not run or score an LLM by itself."""
import argparse,json
from pathlib import Path
import pandas as pd
from imaks_assistant import OUT,write_json

def evaluate(path):
    requests=[json.loads(s) for s in (OUT/'llm_requests.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
    request_map={(r['id'],r['mode']):r for r in requests}
    answers=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
    keys=[(a['id'],a['mode']) for a in answers]
    if len(keys)!=len(set(keys)): raise ValueError('Duplicate answer keys')
    if set(keys)!=set(request_map): raise ValueError('Provide exactly one answer for every prepared request in both modes')
    if any(not a.get('model') for a in answers): raise ValueError('Model must be recorded')
    for a in answers:
        if a.get('temperature') is None and not (
            a.get('backend')=='codex_cli' and a.get('temperature_control')=='not_exposed_by_codex_cli'
            and a.get('reasoning_effort')):
            raise ValueError('Temperature missing without explicit backend limitation')
    settings={(a['model'],a.get('temperature'),a.get('backend'),a.get('temperature_control'),a.get('reasoning_effort')) for a in answers}
    if len(settings)!=1: raise ValueError('Both modes must use identical effective model settings')
    rows=[]
    for a in answers:
        request=request_map[(a['id'],a['mode'])]
        if a.get('prompt_sha256')!=request['prompt_sha256']: raise ValueError('System prompt hash mismatch')
        context=json.loads(request['messages'][1]['content'])['context']
        allowed={c['chunk_id'] for c in context}
        cited=a.get('citations',[])
        if not isinstance(cited,list) or any(not isinstance(c,str) for c in cited): raise ValueError('citations must be a string list')
        if not isinstance(a.get('answer'),str) or not a['answer'].strip(): raise ValueError('Nonempty answer required')
        rows.append({'id':a['id'],'mode':a['mode'],'model':a['model'],
                     'citation_id_validity':sum(c in allowed for c in cited)/len(cited) if cited else None,
                     'citation_count':len(cited),'answer':a['answer'],
                     'semantic_grounding_manual':None,'condition_correctness_manual':None,
                     'action_agreement_manual':None})
    result=pd.DataFrame(rows)
    result.to_csv(OUT/'llm_answer_review.csv',index=False,encoding='utf-8-sig')
    write_json(OUT/'llm_answer_review_protocol.json',{'model':answers[0]['model'],
        'automatic_metric':'Citation IDs exist in retrieved context; this does not establish claim support.',
        'manual_review_required':['semantic grounding','action/condition consistency'],
        'temperature':answers[0].get('temperature'),
        'temperature_control':answers[0].get('temperature_control','explicit'),
        'provenance':'Answer-file metadata; for local runs consult llm_outputs logs. Backend model identity is not independently attested.'})
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('answers',type=Path)
    a=p.parse_args(); print(evaluate(a.answers).to_string(index=False))
