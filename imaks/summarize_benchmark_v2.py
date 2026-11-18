"""Pair-aware metrics and case-cluster bootstrap; no fabricated missing LLM results."""
import hashlib,json
import numpy as np
import pandas as pd
from prepare_benchmark_v2 import ROOT,OUT,MODES,dump
import matplotlib.pyplot as plt

def bootstrap_difference(frame,value,method,baseline='hybrid',n=5000):
    # Average repeats within a question FIRST, then resample questions (not answer rows).
    paired=frame.groupby(['case_id','mode'])[value].mean().unstack('mode')
    paired=paired[[baseline,method]].dropna()
    difference=(paired[method]-paired[baseline]).to_numpy()
    if not len(difference):return {'n_questions':0,'mean_difference':None,'ci_low':None,'ci_high':None}
    rng=np.random.default_rng(20260923)
    boot=difference[rng.integers(0,len(difference),size=(n,len(difference)))].mean(axis=1)
    return {'n_questions':len(difference),'mean_difference':float(difference.mean()),
            'ci_low':float(np.quantile(boot,.025)),'ci_high':float(np.quantile(boot,.975))}

def main():
    definition=json.loads((ROOT/'benchmark_v2.json').read_text(encoding='utf-8'))
    cases={c['id']:c for c in definition['cases']}
    retrieval=pd.read_csv(OUT/'retrieval_metrics.csv').rename(columns={'id':'case_id'})
    retrieval.groupby(['type','mode'])[['evidence_recall','all_evidence_found','context_tokens']].mean().reset_index().to_csv(OUT/'retrieval_by_type.csv',index=False,encoding='utf-8-sig')
    heat=retrieval.pivot_table(index='type',columns='mode',values='evidence_recall').reindex(columns=MODES)
    fig,ax=plt.subplots(figsize=(9,4))
    im=ax.imshow(heat.values,vmin=0,vmax=1,cmap='Blues',aspect='auto')
    ax.set_xticks(range(len(heat.columns)),heat.columns)
    ax.set_yticks(range(len(heat.index)),heat.index)
    for y in range(len(heat.index)):
        for x in range(len(heat.columns)):
            ax.text(x,y,f'{100*heat.iloc[y,x]:.1f}%',ha='center',va='center',color='white' if heat.iloc[y,x]>.65 else 'black')
    ax.set_title('Required evidence recall by question type (3 cases per type)')
    fig.colorbar(im,ax=ax);fig.tight_layout();fig.savefig(OUT/'retrieval_by_type.png',dpi=150);plt.close(fig)
    comparisons=[]
    for mode in MODES[1:]:comparisons.append({'metric':'evidence_recall','method':mode,**bootstrap_difference(retrieval,'evidence_recall',mode)})
    gp=OUT/'generation/all_answers.jsonl';jp=OUT/'judge/all_answers.jsonl'
    if not gp.exists():
        dump(OUT/'completion.json',{'generation':0,'judged':0,'expected_generation':90,'expected_judge':15,'status':'retrieval_only'})
        pd.DataFrame(comparisons).to_csv(OUT/'paired_bootstrap.csv',index=False);return
    answers=[json.loads(s) for s in gp.read_text(encoding='utf-8').splitlines()]
    contexts={(p['id'],p['mode']):p['context'] for p in json.loads((OUT/'prepared_contexts.json').read_text(encoding='utf-8'))}
    requests={(r['id']+'_r'+str(r['repeat']),r['mode']):r for r in [json.loads(s) for s in (OUT/'generation_requests.jsonl').read_text(encoding='utf-8').splitlines()]}
    reviews={};judge_answers=[]
    if jp.exists():
        judge_answers=[json.loads(s) for s in jp.read_text(encoding='utf-8').splitlines()]
        mappings={(r['case_id'],r['answer_id']):r for r in json.loads((OUT/'judge_private_mapping.json').read_text(encoding='utf-8'))}
        for j in judge_answers:
            if len(j['reviews'])!=6 or len({r['answer_id'] for r in j['reviews']})!=6:raise ValueError('Judge must grade six distinct responses')
            for r in j['reviews']:
                mapping=mappings[(j['id'],r['answer_id'])]
                for metric in ['grounding','condition_handling','completeness']:
                    if type(r[metric]) is not int or r[metric] not in [0,1,2]:raise ValueError('Invalid judge score')
                reviews[(mapping['generation_id'],mapping['mode'])]={**r,**mapping}
    rows=[];detail=[];seen=set()
    for a in answers:
        key=(a['id'],a['mode'])
        if key not in requests or key in seen:raise ValueError('Unexpected/duplicate answer')
        seen.add(key);case_id,repeat=a['id'].rsplit('_r',1)
        if a['prompt_sha256']!=requests[key]['prompt_sha256']:raise ValueError('Prompt mismatch')
        context=contexts[(case_id,a['mode'])]
        sources=context['graph_paths']+context['sources'];allowed={s['source_id'] for s in sources}
        cited=set(a['citations']);usage=a.get('usage') or {}
        r=reviews.get(key)
        if r and r['answer_sha256']!=hashlib.sha256(a['answer'].encode()).hexdigest():raise ValueError('Review no longer matches answer')
        row={'case_id':case_id,'type':cases[case_id]['type'],'mode':a['mode'],'repeat':int(repeat),
            'citation_count':len(cited),'invalid_citation_count':len(cited-allowed),
            'citation_id_validity':len(cited&allowed)/len(cited) if cited else None,
            'grounding':r['grounding'] if r else None,'condition_handling':r['condition_handling'] if r else None,
            'completeness':r['completeness'] if r else None,
            'input_tokens':usage.get('input_tokens'),'output_tokens':usage.get('output_tokens'),
            'duration_sec':a['duration_sec'],'answer':a['answer'],'review_rationale':r['rationale'] if r else None}
        row['mean_quality']=sum(row[k] for k in ['grounding','condition_handling','completeness'])/3 if r else None
        rows.append(row)
        detail.append({'case_id':case_id,'type':cases[case_id]['type'],'mode':a['mode'],'repeat':int(repeat),
            'question':cases[case_id]['question'],'expected':cases[case_id]['expected'],'condition':cases[case_id]['condition'],
            'answer':a,'provided_context':context,'AI_review':r})
    df=pd.DataFrame(rows);df.to_csv(OUT/'answer_metrics.csv',index=False,encoding='utf-8-sig')
    metrics=['citation_id_validity','grounding','condition_handling','completeness','mean_quality','duration_sec','input_tokens','output_tokens']
    df.groupby('mode')[metrics].mean().reset_index().to_csv(OUT/'answer_summary.csv',index=False,encoding='utf-8-sig')
    if len(reviews)==len(answers):
        fig,ax=plt.subplots(figsize=(10,4))
        df.groupby('mode')[['grounding','condition_handling','completeness']].mean().reindex(MODES).plot.bar(ax=ax,ylim=(0,2.2),rot=0)
        ax.set_title('Blinded AI review (0-2); not independent human validation')
        fig.tight_layout();fig.savefig(OUT/'answer_quality.png',dpi=150);plt.close(fig)
    df.groupby(['type','mode'])[metrics[:5]].mean().reset_index().to_csv(OUT/'answer_by_type.csv',index=False,encoding='utf-8-sig')
    for mode in MODES[1:]:
        for metric in ['grounding','condition_handling','completeness','mean_quality']:
            if df[metric].notna().any():comparisons.append({'metric':metric,'method':mode,**bootstrap_difference(df,metric,mode)})
    pd.DataFrame(comparisons).to_csv(OUT/'paired_bootstrap.csv',index=False,encoding='utf-8-sig')
    stability=df.groupby(['case_id','mode'])[['grounding','condition_handling','completeness']].agg(lambda x:x.max()-x.min()).reset_index()
    stability.to_csv(OUT/'repeat_score_range.csv',index=False,encoding='utf-8-sig')
    dump(OUT/'answer_review_detail.json',detail)
    total_usage={field:int(df[field].fillna(0).sum())+sum((j.get('usage') or {}).get(field,0) for j in judge_answers) for field in ['input_tokens','output_tokens']}
    dump(OUT/'completion.json',{'generation':len(answers),'judged':len(judge_answers),'graded_answers':len(reviews),
        'expected_generation':len(cases)*3*definition['config']['repeats'],'expected_judge':len(cases),
        'status':'complete' if len(answers)==90 and len(reviews)==90 else 'partial',
        'total_reported_token_usage_including_judge':total_usage,
        'reviewer':'same-model AI judge with method/repeat names hidden; not independent human validation',
        'inference_limit':'Small same-corpus author-written cases; CI resamples question IDs, not external plants; overlap between questions remains.',
        'temperature':'uncontrolled backend default; native temperature not exposed by CLI'})
    print(df.groupby('mode')[metrics].mean().to_string())

if __name__=='__main__':main()
