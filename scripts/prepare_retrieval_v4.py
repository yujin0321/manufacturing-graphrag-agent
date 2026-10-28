"""Prepare the v4 dense row index once, independently of any QA benchmark."""
from pathlib import Path
import sys
import json
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from imaks_kg.rag import retrieval_v3 as r,vector as v
from run_agent_v4 import load_local_key


def prepare():
    manifest_path=r.ROW_INDEX/'manifest.json'
    if manifest_path.exists():
        manifest=v.read(manifest_path);rows=r.row_corpus();policy=r.load_policy()
        if manifest['row_ids']!=[row['chunk_id'] for row in rows] or manifest['corpus_sha256']!=v.digest(v.encoded(rows)):
            raise ValueError('Existing index has a different corpus; preserve it and build a new version')
        if manifest['config']!={'embedding_model':policy['dense_embedding_model'],'dimensions':policy['dense_dimensions']}:
            raise ValueError('Existing index has a different embedding config')
        if v.digest((r.ROW_INDEX/'vectors.npy').read_bytes())!=manifest['vectors_sha256']:
            raise ValueError('Existing index checksum mismatch')
        print(json.dumps({'status':'ready','reused':True,'rows':len(rows)}));return
    load_local_key();manifest=r.build_row_index()
    print(json.dumps({'status':'ready','reused':False,'rows':len(manifest['row_ids']),'api':manifest['api']}))


if __name__=='__main__':prepare()
