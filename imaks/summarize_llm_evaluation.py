"""Summarize complete LLM generations; never invent missing semantic grades."""
from pathlib import Path
import hashlib
import json
import pandas as pd
from imaks_assistant import ROOT, write_json
from evaluate_llm_answers import evaluate

OUT=ROOT/'llm_outputs'

def main():
    answers=[json.loads(s) for s in (OUT/'answers.jsonl').read_text(encoding='utf-8').splitlines()]
    auto=evaluate(OUT/'answers.jsonl')
    requests=[json.loads(s) for s in (ROOT/'assistant_outputs/llm_requests.jsonl').read_text(encoding='utf-8').splitlines()]
    request_map={(r['id'],r['mode']):r for r in requests}
    gold={q['id']:q for q in json.loads((ROOT/'evaluation_ko.json').read_text(encoding='utf-8'))['cases']}
    audit_path=OUT/'assistant_review.json'
    reviews=json.loads(audit_path.read_text(encoding='utf-8')) if audit_path.exists() else []
    review_map={(r['id'],r['mode']):r for r in reviews}
    if reviews and set(review_map)!={(a['id'],a['mode']) for a in answers}: raise ValueError('Semantic review must cover every answer exactly once')
    rows=[]; template=[]
    for a in answers:
        key=(a['id'],a['mode'])
        context=json.loads(request_map[key]['messages'][1]['content'])['context']
        cited=set(a['citations'])
        available={h['chunk_id'] for h in context}
        cited_context=[h for h in context if h['chunk_id'] in cited]
        source_keys={v for h in cited_context for v in [h['rule_id'],'DOC:'+h['document']]}
        groups=gold[a['id']]['gold']
        answer_hash=hashlib.sha256(a['answer'].encode()).hexdigest()
        row={'id':a['id'],'mode':a['mode'],'answer':a['answer'],
            'valid_citation_count':len(cited&available),'citation_count':len(cited),
            'citation_id_validity':len(cited&available)/len(cited) if cited else None,
            'cited_gold_coverage':sum(bool(source_keys.intersection(g)) for g in groups)/len(groups),
            'duration_sec':a.get('duration_sec'),'answer_sha256':answer_hash,
            'grounding':None,'condition_handling':None,'task_completeness':None,'review_reason':None}
        item={'id':a['id'],'mode':a['mode'],'answer_sha256':answer_hash,
              'grounding':None,'condition_handling':None,'task_completeness':None,'review_reason':None,
              'reviewer':'AI assistant; not independent human review'}
        if key in review_map:
            review=review_map[key]
            if review['answer_sha256']!=answer_hash: raise ValueError('Stale review hash '+str(key))
            for field in ['grounding','condition_handling','task_completeness']:
                if type(review.get(field)) is not int or review[field] not in [0,1,2]: raise ValueError('Missing/invalid semantic grade')
                row[field]=review[field]
            if not review.get('review_reason'): raise ValueError('Review rationale required')
            row['review_reason']=review['review_reason']
        rows.append(row); template.append(item)
    result=pd.DataFrame(rows)
    result.to_csv(OUT/'answer_evaluation.csv',index=False,encoding='utf-8-sig')
    summary=result.groupby('mode')[['citation_id_validity','cited_gold_coverage','grounding','condition_handling','task_completeness']].mean().reset_index()
    summary.to_csv(OUT/'evaluation_summary.csv',index=False,encoding='utf-8-sig')
    write_json(OUT/'review_template.json',template)
    write_json(OUT/'evaluation_status.json',{'generated':len(answers),'semantic_reviewed':len(reviews),
        'reviewer':'AI assistant' if reviews else None,'human_reviewed':False,
        'temperature_control':'not_exposed_by_codex_cli','repeats':1,
        'limitations':['Small developer-authored question set','One sample per condition','AI review, not independent human grading','CLI wrapper differs from direct API role messages']})
    print(summary.to_string(index=False))

if __name__=='__main__': main()
