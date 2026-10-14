import zipfile,importlib.util,os
from pathlib import Path
p=Path(r'C:\Users\User\OneDrive\문서\ChatGPT\26-2 비타민 학기 프젝\iMAKS_dataset.zip')
with zipfile.ZipFile(p) as z:
    print('\n'.join(n for n in z.namelist() if n.rsplit('/',1)[-1] in ['nodes.csv','edges.csv','ground_truth.csv']))
for n in ['rdflib','pyshacl','numpy','scipy','sentence_transformers','torch','sklearn','transformers']:
    spec=importlib.util.find_spec(n)
    print(n, 'available' if spec else 'missing')
cache=Path(os.environ.get('HF_HOME',Path.home()/'.cache'/'huggingface'))/'hub'
print('embedding cache:',[p.name for p in cache.glob('*MiniLM*')])
