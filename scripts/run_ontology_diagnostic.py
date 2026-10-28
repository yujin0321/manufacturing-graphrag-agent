"""Run locked questions only; never load the private grading rubric."""
from imaks_kg.rag import vector as v, live


def main():
    root=v.REPO_ROOT
    lock=v.read(root/'evaluation/ontology_diagnostic_20261027/pre_run_lock.json')
    questions=root/'docs/ontology_diagnostic_20261027/questions.json'
    expected={**lock['baseline_files_sha256'],lock['kg_path']:lock['kg_sha256'],
              str(questions.relative_to(root)):lock['questions_sha256'],str(v.SOURCE.relative_to(root)):lock['source_sha256']}
    for p,h in expected.items():
        if v.digest((root/p).read_bytes())!=h:raise ValueError('Locked input changed: '+p)
    _,_,manifest=v.load_index(v.DEFAULT_INDEX)
    if manifest['config']!=v.read(root/'docs/vector_rag_v1/config.json'):raise ValueError('Index generation config differs')
    out=root/'kg_build/ontology_diagnostic_20261027'
    out.mkdir(parents=True,exist_ok=False)
    v.write(out/'experiment_lock.json',{'input_lock':lock,'runner_sha256':v.digest(__import__('pathlib').Path(__file__).read_bytes()),
             'code_hashes':{p:v.digest((root/p).read_bytes()) for p in ['src/imaks_kg/rag/vector.py','src/imaks_kg/rag/comparison.py']},
             'grading_rubric_loaded':False,'automatic_retries':False})
    completed=[]
    for row in v.read(questions):
        result=live.answer(row['question'],out/row['id'])
        completed.append({'id':row['id'],'model':result['returned_model'],'usage':result['usage'],
            'embedding':result['embedding_api'],'answer_sha256':v.digest((out/row['id']/'answer.json').read_bytes()),
            'retrieval_sha256':v.digest((out/row['id']/'retrieval.json').read_bytes())})
        v.write(out/'progress.json',completed)
        print(row['id'],result['usage'],flush=True)
    v.write(out/'complete.json',{'questions':len(completed),'runs':completed})


if __name__=='__main__':main()
