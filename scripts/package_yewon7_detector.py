"""Freeze the selected main-based detector results, without API calls.

Prediction seals are checked before loading evaluation labels. This is a
development-result package, not an independent evaluation or a default change.
"""
from pathlib import Path
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from imaks_kg.rag import vector as v
from imaks_kg.detection import rules
from evaluate_detector_events import gold_events, evaluate, evaluate_warning_stages, LABELS

OUT = v.REPO_ROOT/"artifacts/rule_detector_yewon7_20261106"


def main():
    runs = {"baseline":v.REPO_ROOT/"kg_build/main_baseline",
            "watch2":v.REPO_ROOT/"kg_build/main_watch2"}
    sources = {}
    for name,folder in runs.items():
        seal = v.read(folder/"complete.json")
        for file,expected in seal.items():
            if Path(file).name!=file or v.digest((folder/file).read_bytes())!=expected:
                raise ValueError(f"Changed or invalid prediction: {name}/{file}")
        sources[name] = {"folder":folder.relative_to(v.REPO_ROOT).as_posix(),
                         "seal_sha256":v.digest((folder/"complete.json").read_bytes())}
    _,_,profile = rules.read_inputs()
    labels = v.REPO_ROOT/LABELS
    if v.digest(labels.read_bytes())!=profile["output_sha256"][LABELS]:
        raise ValueError("Changed evaluation labels")
    gold = gold_events(labels)
    OUT.mkdir(parents=True,exist_ok=False)
    comparison = {}
    for name,folder in runs.items():
        destination = OUT/name
        destination.mkdir()
        for file in [*v.read(folder/"complete.json"),"complete.json"]:
            shutil.copyfile(folder/file,destination/file)
        comparison[name] = evaluate(v.read(destination/"events.json"),gold,0)
    stages = evaluate_warning_stages(v.read(OUT/"watch2/warning_transitions.json"),gold)
    unchanged = ["kg_document_rule","kg_threshold_critical"]
    first = v.read(OUT/"baseline/events.json")
    second = v.read(OUT/"watch2/events.json")
    for kind in unchanged:
        if [e for e in first if e["kind"]==kind]!=[e for e in second if e["kind"]==kind]:
            raise ValueError(f"Protected rule family changed: {kind}")
    v.write(OUT/"evaluation/gold_events.json",gold)
    v.write(OUT/"evaluation/comparison.json",comparison)
    v.write(OUT/"evaluation/warning_stages.json",stages)
    v.write(OUT/"selection.json",{
        "branch":"예원7","base_main_commit":"6ce2c702a2b866500e03709e2e01ae2b63a6782e",
        "development_retest":True,"independent_test":False,"api_calls":0,
        "selected":["optional same-side warning confirmation","immediate watch history",
                    "watch/confirmed stage evaluation","correct even-sample latency median"],
        "default_warning_samples":1,"optional_warning_samples":2,
        "unchanged_rule_families":unchanged,"automatic_maintenance_execution":False,
        "not_promoted":["trend/CUSUM notification policies","CUSUM recovery observer",
                        "history Agent depending on experimental trend snapshots"],
        "reason":"Confirmation reduces isolated warnings but can delay detection; preserve the first watch and keep confirmation opt-in.",
        "source_predictions":sources,
        "input_sha256":{p:profile["output_sha256"][p] for p in (rules.INPUT,rules.THRESHOLDS)},
        "evaluation_labels_sha256":profile["output_sha256"][LABELS],
        "kg_sha256":v.read(OUT/"watch2/summary.json")["kg_sha256"]})
    v.write(OUT/"manifest.json",{p.relative_to(OUT).as_posix():v.digest(p.read_bytes())
                               for p in sorted(OUT.rglob("*")) if p.is_file()})
    print(f"Packaged {len(v.read(OUT/'manifest.json'))} files: {OUT}")


if __name__=="__main__":
    main()
