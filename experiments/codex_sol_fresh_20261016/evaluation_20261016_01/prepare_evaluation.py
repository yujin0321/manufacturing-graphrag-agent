import pathlib,json,hashlib,sys,importlib.metadata
O=pathlib.Path(__file__).resolve().parent;B=O.parent;R=B/'run_20261016_01'
DEFS=pathlib.Path('C:/Users/ysh/Desktop/대학교/동아리/비타민/프로젝트/26-2/지훈코드')
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(n,v):
    with (O/n).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2);f.write('\n')
stage=sys.argv[1]
if stage=='download':
    from huggingface_hub import snapshot_download
    p=snapshot_download('sentence-transformers/all-MiniLM-L6-v2',revision='1110a243fdf4706b3f48f1d95db1a4f5529b4d41',local_dir=O/'embedding_model',cache_dir=O/'model_cache',token=False,allow_patterns=['config.json','config_sentence_transformers.json','modules.json','sentence_bert_config.json','model.safetensors','pytorch_model.bin','tokenizer.json','tokenizer_config.json','vocab.txt','special_tokens_map.json','1_Pooling/config.json'])
    print('Pinned public embedding model downloaded; no prediction or gold sent to a server.')
elif stage=='lock':
    assert not (O/'pre_evaluation_lock.json').exists()
    f=json.loads((R/'freeze.json').read_text(encoding='utf-8'))
    assert h(R/'freeze.json')==(R/'freeze.sha256').read_text().split()[0]
    for n,expected in f['inputs'].items():assert h(B/'input'/n)==expected
    for n,expected in f['artifacts'].items():assert h(R/n)==expected
    from sentence_transformers import SentenceTransformer
    model=SentenceTransformer(str(O/'embedding_model'),device='cpu',local_files_only=True,token=False)
    assert model.get_sentence_embedding_dimension()==384
    versions={n:importlib.metadata.version(n) for n in ['torch','sentence-transformers','transformers','numpy','scipy','huggingface-hub']}
    lock={'prediction_file':str(R/'predictions.raw.jsonl'),'prediction_sha256':h(R/'predictions.raw.jsonl'),'original_freeze_sha256':h(R/'freeze.json'),'definition_files':{n:{'path':str(DEFS/n),'sha256':h(DEFS/n)} for n in ['eval_definition_F1_content.md','eval_definition_team_summary.md']},'original_configuration_hashes':{n:f['artifacts'][n] for n in ['prompt.txt','extraction_policy.txt','output_schema.json','configuration.json','extract.py']},'examples':{'used':False,'file':None},'requested_model':'GPT-6.1 Sol','actual_model':'unverified','evaluation_policy':json.loads((O/'evaluation_policy.json').read_text(encoding='utf-8')),'policy_sha256':h(O/'evaluation_policy.json'),'evaluator_sha256':h(O/'src/imaks_kg/eval/__main__.py'),'embedding_model':{'name':'sentence-transformers/all-MiniLM-L6-v2','revision':'1110a243fdf4706b3f48f1d95db1a4f5529b4d41','dimension':384,'files':{p.relative_to(O/'embedding_model').as_posix():h(p) for p in sorted((O/'embedding_model').rglob('*')) if p.is_file() and '.cache' not in p.parts}},'versions':versions,'gold_not_read_by_this_preparation':True,'exposure':'Attached definitions disclose gold aggregate counts. Historical project gold exposure inherited. This chat has not read individual gold rules.','scope':'Fixed original raw predictions; no prediction rewrite or rule merging.'}
    save('pre_evaluation_lock.json',lock)
    (O/'pre_evaluation_lock.sha256').write_text(h(O/'pre_evaluation_lock.json')+'  pre_evaluation_lock.json\n',encoding='ascii')
    print(json.dumps({'lock_sha256':h(O/'pre_evaluation_lock.json'),'embedding_revision':lock['embedding_model']['revision'],'versions':versions}))
