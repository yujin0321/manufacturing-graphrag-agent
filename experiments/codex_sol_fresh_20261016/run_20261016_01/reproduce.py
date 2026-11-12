"""Verify frozen files, or replay into a NEW sibling directory. No API or gold access."""
import pathlib,json,hashlib,argparse,shutil,subprocess,sys
O=pathlib.Path(__file__).resolve().parent;I=O.parent/'input'
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
a=argparse.ArgumentParser();a.add_argument('--output',help='New sibling directory name, e.g. replay_01');a.add_argument('--extract-only',action='store_true');args=a.parse_args()
f=json.loads((O/'freeze.json').read_text(encoding='utf-8'))
for n,s in f['inputs'].items():assert h(I/n)==s,n
for n,s in f['artifacts'].items():assert h(O/n)==s,n
assert h(O/'freeze.json')==(O/'freeze.sha256').read_text().split()[0]
print('Frozen input/artifact checksums: PASS')
if args.output:
    assert pathlib.Path(args.output).name==args.output and args.output not in ['.','..']
    dst=O.parent/args.output;dst.mkdir(exist_ok=False)
    for n in ['extraction_policy.txt','output_schema.json','configuration.json','prompt.txt','input_inventory.json','extract.py','validate_build.py','supplemental_checks.py','repair_kg_literals.py','build_report.py','reproduce.py']:
        shutil.copyfile(O/n,dst/n)
    subprocess.run([sys.executable,str(dst/'extract.py')],check=True)
    assert h(dst/'freeze.json')==h(O/'freeze.json'),'Replay freeze differs'
    print('Deterministic extraction replay: identical freeze SHA-256')
    if not args.extract_only:
        # Copy only the explicitly installed validation dependencies; no environment/key inspection.
        shutil.copytree(O/'vendor',dst/'vendor')
        for n in ['validate_build.py','supplemental_checks.py','repair_kg_literals.py','build_report.py']:
            subprocess.run([sys.executable,str(dst/n)],check=True)
