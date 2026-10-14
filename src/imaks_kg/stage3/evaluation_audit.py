"""Post-hoc evaluation diagnostics; never changes frozen predictions or primary scores."""
import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from .common import OUT, REPO_ROOT, digest, read_csv, read_jsonl, write_json


def audit(run, evaluation):
    from huggingface_hub import snapshot_download
    from sentence_transformers import SentenceTransformer
    primary=json.loads(evaluation.read_text(encoding='utf8'))
    predictions=read_jsonl(run/'predictions.jsonl')
    pred=[p for p in predictions if p['doc_id'].startswith('SOP-')]
    gt=read_csv(REPO_ROOT/'imaks_data/kg_seed/ground_truth.csv')
    snapshot=snapshot_download(primary['protocol']['embedding_model'],revision=primary['protocol']['resolved_revision'],
                               allow_patterns=['*.json','*.safetensors','vocab.txt','tokenizer.*','*.txt'])
    model=SentenceTransformer(snapshot,device='cpu',trust_remote_code=False)
    text=lambda r:'Condition: '+r['condition']+'\nAction: '+r['action']
    texts=[text(r) for r in pred+gt]
    lengths=[len(model.tokenizer(t,truncation=False)['input_ids']) for t in texts]
    embeddings=model.encode(texts,normalize_embeddings=True,convert_to_numpy=True)
    matrix=embeddings[:len(pred)] @ embeddings[len(pred):].T
    alternative=[]
    for doc in sorted({p['doc_id'] for p in pred}):
        pi=[i for i,p in enumerate(pred) if p['doc_id']==doc]
        gi=[i for i,g in enumerate(gt) if g['source']==doc]
        a,b=linear_sum_assignment(-matrix[np.ix_(pi,gi)])
        alternative.extend((pi[i],gi[j]) for i,j in zip(a,b) if matrix[pi[i],gi[j]]>=primary['protocol']['threshold'])
    numeric=[]
    for r in read_jsonl(OUT/'sop002_source_supplement.jsonl'):
        if not r.get('numeric'):
            continue
        candidates=[g for g in gt if g['source']=='SOP-002' and g['class']=='ThresholdRule' and g['sensor']==r['sensors'][0]]
        if len(candidates)!=1:
            raise ValueError('Ambiguous numeric reference')
        mismatches=[k for k in ('critLo','warnLo','warnHi','critHi') if Decimal(r['numeric'][k])!=Decimal(candidates[0][k])]
        numeric.append({'sensor':r['sensors'][0],'different_fields':mismatches})
    by_doc=[]
    for doc in ('SOP-001','SOP-002','SOP-003','SOP-004'):
        matches=[m for m in primary['matches'] if m['prediction']['doc_id']==doc]
        by_doc.append({'document':doc,'predictions':sum(p['doc_id']==doc for p in pred),
                       'references':sum(g['source']==doc for g in gt),'content_matches':len(matches),
                       'processed':doc in primary['completed_sop_documents']})
    report={'status':'posthoc_diagnostic_not_primary_metric', 'primary_score_unchanged':True,
            'predictions_sha256':digest((run/'predictions.jsonl').read_bytes()),
            'reference_sha256':primary['reference_sha256'], 'documents':by_doc,
            'tokenization':{'max_input_tokens':max(lengths),'model_limit':model.max_seq_length,
                            'truncated_inputs':sum(n>model.max_seq_length for n in lengths),
                            'inputs_checked':len(texts)},
            'matching_policy_diagnostic':{'primary':'maximize valid count, then cosine; threshold before acceptance',
                'alternative':'document-wise maximize total cosine, then accept >= threshold',
                'primary_matches':primary['content']['tp'],'alternative_matches':len(alternative),
                'reason':'expose policy differences from teammate evaluation; not replace the preregistered primary result'},
            'source_supplement_numeric':{'method':'source-only deterministic table conversion, not LLM extraction',
                'sensors_checked':len(numeric),'fields_checked':4*len(numeric),
                'fields_matching_reference':4*len(numeric)-sum(len(r['different_fields']) for r in numeric),
                'differences':[r for r in numeric if r['different_fields']],
                'interpretation':'Source-vs-reference discrepancy; preserve source values, no reference-driven edits'},
            'matched_field_diagnostics':{'matches_checked':len(primary['matches']),
                'sensor_set_exact':sum(m['sensor_correct'] for m in primary['matches']),
                'severity_exact':sum(m['severity_correct'] for m in primary['matches']),
                'numeric_text_flags':sum(m['numeric_review_needed'] for m in primary['matches'])}}
    write_json(OUT/'posthoc_evaluation_audit.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--evaluation',type=Path,required=True)
    a=p.parse_args(); audit(a.run,a.evaluation)
