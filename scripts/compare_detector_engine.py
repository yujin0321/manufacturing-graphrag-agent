"""Equivalence check: legacy detectors vs the new engine (stage 1).

Generates legacy outputs (kg_rules_v3 default / --slope-as-alarm, kg_rules_v3_1)
and engine outputs (configs v3 / v3_literal / v3_1) into a NEW directory, then
compares events/incidents/correlations/signals (+ monitor_windows for v3.1).
Bytes first; if bytes differ, JSON with only object keys normalized (array
order and ids compared as-is). summary.json / complete.json are excluded from
cross-version comparison; each run's complete.json is verified against the
actual SHA-256 of the files it lists. Reads no labels and runs no evaluation.

  python scripts/compare_detector_engine.py --work kg_build/engine_equivalence_<date>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from imaks_kg.detection import kg_rules_v3 as k3  # noqa: E402
from imaks_kg.detection import kg_rules_v3_1 as k31  # noqa: E402
from imaks_kg.detection.engine import run as engine  # noqa: E402

CASES = {"v3": (lambda out: k3.run(out), ["events", "incidents", "correlations", "signals"]),
         "v3_literal": (lambda out: k3.run(out, slope_as_alarm=True), ["events", "incidents", "correlations", "signals"]),
         "v3_1": (lambda out: k31.run(out), ["events", "incidents", "correlations", "signals", "monitor_windows"])}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_seal(run_dir: Path) -> None:
    seal = json.loads((run_dir / "complete.json").read_text(encoding="utf-8"))
    for name, digest in seal.items():
        if sha(run_dir / name) != digest:
            raise ValueError(f"seal mismatch: {run_dir / name}")


def first_difference(a, b, path="$"):
    """First differing location; arrays compared in order (no sorting)."""
    if type(a) is not type(b):
        return path, a, b
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}", a.get(k, "<missing>"), b.get(k, "<missing>")
            d = first_difference(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
        return (f"{path}.length", len(a), len(b)) if len(a) != len(b) else None
    return None if a == b else (path, a, b)


def compare(work: Path) -> dict:
    results = {}
    for name, (legacy, files) in CASES.items():
        ldir, edir = work / "legacy" / name, work / "engine" / name
        legacy(ldir)
        engine.run(name, edir)
        verify_seal(ldir)
        verify_seal(edir)
        rows = []
        for f in files:
            lp, ep = ldir / f"{f}.json", edir / f"{f}.json"
            row = {"file": lp.name, "legacy_sha256": sha(lp), "engine_sha256": sha(ep)}
            if row["legacy_sha256"] == row["engine_sha256"]:
                row["result"] = "bytes_equal"
            else:
                diff = first_difference(json.loads(lp.read_text(encoding="utf-8")),
                                        json.loads(ep.read_text(encoding="utf-8")))
                row["result"] = "json_equal_keys_normalized" if diff is None else "DIFFERENT"
                if diff:
                    row["first_difference"] = {"path": diff[0], "legacy": diff[1], "engine": diff[2]}
            rows.append(row)
        results[name] = rows
    return results


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--work", type=Path, required=True, help="new directory (must not exist)")
    a = p.parse_args()
    a.work.mkdir(parents=True, exist_ok=False)
    results = compare(a.work)
    (a.work / "equivalence.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok = True
    for name, rows in results.items():
        for r in rows:
            ok &= r["result"] != "DIFFERENT"
            print(f"{name:11} {r['file']:22} {r['result']:28} {r['engine_sha256'][:12]}")
            if "first_difference" in r:
                print("   first difference:", json.dumps(r["first_difference"], ensure_ascii=False)[:500])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
