import csv
import hashlib
import json
from pathlib import Path

from imaks_kg.settings import REPO_ROOT

OUT = REPO_ROOT / "artifacts" / "stage3"
DOCS = REPO_ROOT / "preprocessed" / "documents"
CLASSES = ("OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule")


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def catalog():
    # This allowlist intentionally excludes maintenance content and event labels.
    rows = read_csv(REPO_ROOT / "imaks_data/kg_seed/nodes.csv")
    return {
        "stations": [r["name"] for r in rows if r["label"] == "Component"],
        "sensors": [r["name"] for r in rows if r["label"] == "Sensor"],
    }
