"""Verify the small checked-in result bundle without raw data or an API key."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from imaks_kg.rag import vector as v
from evaluate_detector_events import evaluate, evaluate_warning_stages

ROOT = v.REPO_ROOT/"artifacts/rule_detector_yewon7_20261106"


def main():
    manifest = v.read(ROOT/"manifest.json")
    actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()}
    if actual != set(manifest)|{"manifest.json"}:
        raise ValueError("Missing or unexpected bundle file")
    for rel,expected in manifest.items():
        if v.digest((ROOT/rel).read_bytes())!=expected:
            raise ValueError(f"Bundle hash mismatch: {rel}")
    gold = v.read(ROOT/"evaluation/gold_events.json")
    comparison = v.read(ROOT/"evaluation/comparison.json")
    for name in ("baseline","watch2"):
        folder = ROOT/name
        for file,expected in v.read(folder/"complete.json").items():
            if v.digest((folder/file).read_bytes())!=expected:
                raise ValueError(f"Prediction seal mismatch: {name}/{file}")
        if evaluate(v.read(folder/"events.json"),gold,0)!=comparison[name]:
            raise ValueError(f"Evaluation mismatch: {name}")
    if evaluate_warning_stages(v.read(ROOT/"watch2/warning_transitions.json"),gold)!=v.read(ROOT/"evaluation/warning_stages.json"):
        raise ValueError("Stage evaluation mismatch")
    first = v.read(ROOT/"baseline/events.json")
    second = v.read(ROOT/"watch2/events.json")
    for kind in ("kg_document_rule","kg_threshold_critical"):
        if [r for r in first if r["kind"]==kind]!=[r for r in second if r["kind"]==kind]:
            raise ValueError(f"Protected family changed: {kind}")
    print(f"PASS: {len(manifest)} file hashes, both prediction seals, paired evaluation and warning stages.")
    print("Development replay: 13/14 events in both settings; confirmed warnings 50 -> 39; latency trade-off retained.")


if __name__=="__main__":
    main()
