"""Stage 2: sealed engine incidents -> KG overlay (pipeline step ⑦).

The overlay is a separate TTL file next to the frozen KG; the base KG is never
modified. Mapping (ontology_v1):

* incident -> AnomalyEvent of exactly one SOP-002 subclass
  (Spike, Drift, StuckSensor, OutOfRange, Correlated), ``Sensor triggers event``,
  ``startTime``/``endTime``.
* each incident -> timeseries ``Provenance`` with a ``windowId`` built from
  sensor + start time (never a GT id), file name and SHA-256 of the input.
* matched rules -> ``det:matchedRule`` pointing at the actual KG Rule nodes.
* correlation links -> ``det:CorrelationCandidate`` (cause/effect events, lag,
  ``det:ruleIds``, ``hasEvidence``-like ``det:evidenceKind``). They are NOT
  written as ``CausalLink``/``causallyAffects``: S5 requires a
  ``likelihoodScore`` and no score definition exists for SOP-rule matches
  (CLAUDE.md 3장: 0.6 / top-3 filters need a score). Left open, not invented.

Loading is refused unless (a) SHACL S1-S8 on base+overlay, inference="none",
reports no violation whose focus node is an overlay node, and (b) the loader
checks pass: rule references resolve, windowIds are registered, no GT-style id,
no dataset label fields. guards/leakage_shapes.ttl states it applies only to
step ⑥ input graphs (its L1-L3 forbid AnomalyEvent, triggers, startTime by
design), so for this step ⑦ overlay only its GT-id rule (L4) is applied, plus
the loader checks above.

  python -m imaks_kg.detection.engine.overlay --run kg_build/rule_engine_v3_1 --out kg_build/rule_engine_v3_1_overlay
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import quote

from rdflib import RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

from imaks_kg.rag import comparison as c
from imaks_kg.rag import vector as v

from .. import rules as v1

DET = Namespace("https://example.org/imaks/detection/engine#")
EVENT = "https://example.org/imaks/detection/engine/event/"
WINDOW = "https://example.org/imaks/detection/engine/window/"
CORR = "https://example.org/imaks/detection/engine/correlation/"
TYPE_CLASS = {"SPIKE": "Spike", "DRIFT": "Drift", "STUCK": "StuckSensor", "OUT_OF_RANGE": "OutOfRange",
              "CORRELATED": "Correlated"}
SHAPES = v.REPO_ROOT / "ontology_v1/shapes.ttl"
ONTOLOGY = v.REPO_ROOT / "ontology_v1/ontology.ttl"
GUARDS = v.REPO_ROOT / "guards/leakage_shapes.ttl"
GT_PATTERN = re.compile(r"GT-[0-9]{4}", re.I)
# dataset annotation fields that must never appear in a detector overlay
LABEL_LOCALS = {"datasetseverity", "anomalylabel", "alarmflag", "gtid", "gteventid", "isanomaly", "rootcause"}


class OverlayRejected(ValueError):
    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report


def verify_seal(run_dir: Path) -> dict:
    seal = v.read(run_dir / "complete.json")
    for name, digest in seal.items():
        if Path(name).name != name or v.digest((run_dir / name).read_bytes()) != digest:
            raise ValueError(f"engine output changed after sealing: {name}")
    for name in ("incidents.json", "correlations.json", "ir.json", "summary.json", "params.json"):
        if name not in seal:
            raise ValueError(f"engine output not sealed: {name}")
    return seal


def window_id(sensor_id: str, start: str) -> str:
    return f"W-{sensor_id}-{start.replace('-', '').replace(':', '')}"


def _dt(s: str) -> Literal:
    return Literal(s, datatype=XSD.dateTime)


def build_overlay(run_dir: Path, base: Graph) -> tuple[Graph, dict]:
    """Return (overlay graph, mapping summary). Pure mapping; no validation."""
    incidents = v.read(run_dir / "incidents.json")
    links = v.read(run_dir / "correlations.json")
    ir = v.read(run_dir / "ir.json")
    params = v.read(run_dir / "params.json")
    events_by_id = {a["id"]: a for a in v.read(run_dir / "events.json")}
    sensor_nodes = {str(base.value(s, c.IM.identifier)): s for s in base.subjects(RDF.type, c.IM.Sensor)}
    rule_nodes = {}
    for r in ir["rules"]:
        rule_nodes.setdefault(r["rule_id"], set()).add(r["kg_node"])
    for p in ir["correlation_pairs"]:  # v3.1 monitor alarms carry "<first pair rule>:monitor"
        rule_nodes.setdefault(p["rule_ids"][0] + ":monitor", set()).update(p["kg_nodes"])
    input_sha = v.digest((v.REPO_ROOT / v1.INPUT).read_bytes())
    g = Graph()
    g.bind("im", c.IM)
    g.bind("det", DET)
    skipped, mapped = [], {}
    for inc in incidents:
        cls = TYPE_CLASS.get(inc["anomaly_type"])
        if cls is None:  # e.g. UNCLASSIFIED: no SOP-002 subclass exists -> not loaded, reported
            skipped.append({"incident": inc["id"], "anomaly_type": inc["anomaly_type"],
                            "reason": "no SOP-002 AnomalyEvent subclass for this type"})
            continue
        node = URIRef(EVENT + inc["id"])
        mapped[inc["id"]] = node
        wid = window_id(inc["sensor_id"], inc["start"])
        prov = URIRef(WINDOW + quote(wid, safe=""))
        g.add((node, RDF.type, c.IM[cls]))
        g.add((node, RDFS.label, Literal(f"{cls} candidate {inc['sensor_id']} {inc['start']}")))
        g.add((sensor_nodes[inc["sensor_id"]], c.IM.triggers, node))
        g.add((node, c.IM.startTime, _dt(inc["start"])))
        g.add((node, c.IM.endTime, _dt(inc["end"])))
        g.add((node, c.IM.hasProvenance, prov))
        g.add((prov, RDF.type, c.IM.Provenance))
        g.add((prov, c.IM.sourceKind, Literal("timeseries")))
        g.add((prov, c.IM.fileName, Literal(v1.INPUT)))
        g.add((prov, c.IM.sensorId, Literal(inc["sensor_id"])))
        g.add((prov, c.IM.intervalStart, _dt(inc["onset_estimate"])))
        g.add((prov, c.IM.intervalEnd, _dt(inc["end"])))
        g.add((prov, c.IM.fileSha256, Literal(input_sha)))
        g.add((prov, c.IM.windowId, Literal(wid)))
        g.add((node, DET.engineIncidentId, Literal(inc["id"])))
        g.add((node, DET.engineConfig, Literal(params["config"]["name"])))
        g.add((node, DET.detectionSeverity, Literal(inc["severity"])))
        g.add((node, DET.typeReason, Literal(inc["type_reason"])))
        g.add((node, DET.onsetEstimate, _dt(inc["onset_estimate"])))
        g.add((node, DET.status, Literal("rule_match_candidate_not_confirmed_anomaly")))
        if inc.get("pre_correlation_type"):
            g.add((node, DET.sensorLevelType, Literal(inc["pre_correlation_type"])))
        for flag in inc["flags"]:
            g.add((node, DET.flag, Literal(flag)))
        for aid in inc["alarm_ids"]:
            alarm = events_by_id[aid]
            kg_nodes = rule_nodes.get(alarm["rule_id"])
            if not kg_nodes:
                raise ValueError(f"alarm rule has no KG node in the IR: {alarm['rule_id']}")
            for kg in sorted(kg_nodes):
                g.add((node, DET.matchedRule, URIRef(kg)))
    correlations = []
    for link in links:
        cause, effect = mapped.get(link["cause_incident"]), mapped.get(link["effect_incident"])
        if cause is None or effect is None:
            skipped.append({"correlation": link, "reason": "cause or effect incident not mapped"})
            continue
        node = URIRef(CORR + v.digest(v.encoded(link))[:20])
        g.add((node, RDF.type, DET.CorrelationCandidate))
        g.add((node, DET.causeEvent, cause))
        g.add((node, DET.effectEvent, effect))
        g.add((effect, DET.correlatedWithEvent, cause))
        g.add((node, DET.lagMinutes, Literal(round(link["lag_min"], 3), datatype=XSD.decimal)))
        g.add((node, DET.evidenceKind, Literal(link["hasEvidence"])))
        g.add((node, DET.status, Literal(link["status"])))
        for rid in link["evidence_rule_ids"]:
            g.add((node, DET.ruleIds, Literal(rid)))
        for kg in link["evidence_kg_nodes"]:
            g.add((node, DET.evidenceRule, URIRef(kg)))
        correlations.append(str(node))
    summary = {"events": len(mapped), "correlation_candidates": len(correlations), "skipped": skipped,
               "causal_links": 0,
               "causal_links_note": "CausalLink/causallyAffects not written: likelihoodScore is required (S5) "
                                    "and no score definition exists for SOP-rule correlation matches."}
    return g, summary


def _rule_identifiers(base: Graph) -> set[str]:
    out = set()
    for cls in ("OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule"):
        for n in base.subjects(RDF.type, c.IM[cls]):
            out.add(str(base.value(n, c.IM.identifier)).rsplit("::", 1)[-1])
    return out


def loader_checks(overlay: Graph, base: Graph) -> list[str]:
    errors = []
    rule_classes = {c.IM[k] for k in ("OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule")}
    for pred in (DET.matchedRule, DET.evidenceRule):
        for _, rule in overlay.subject_objects(pred):
            if not set(base.objects(rule, RDF.type)) & rule_classes:
                errors.append(f"rule reference does not resolve to a KG Rule: {rule}")
    identifiers = _rule_identifiers(base)
    for _, rid in overlay.subject_objects(DET.ruleIds):
        if str(rid) not in identifiers:
            errors.append(f"ruleIds value is not a KG Rule identifier: {rid}")
    registered = {str(w) for p in overlay.subjects(c.IM.sourceKind, Literal("timeseries"))
                  for w in overlay.objects(p, c.IM.windowId)}
    for event in set(overlay.subjects(c.IM.hasProvenance, None)):
        for p in overlay.objects(event, c.IM.hasProvenance):
            if str(overlay.value(p, c.IM.windowId)) not in registered:
                errors.append(f"windowId not registered: {event}")
    for s, p, o in overlay:
        for term in (s, p, o):
            if GT_PATTERN.search(str(term)):
                errors.append(f"GT-style identifier in overlay: {term}")
        local = re.sub(r"[_-]", "", re.split(r"[/#:]", str(p))[-1].lower())
        if local in LABEL_LOCALS:
            errors.append(f"dataset label field in overlay: {p}")
    for cause, effect in ((c_, e) for n in overlay.subjects(RDF.type, DET.CorrelationCandidate)
                          for c_ in [overlay.value(n, DET.causeEvent)] for e in [overlay.value(n, DET.effectEvent)]):
        if cause == effect:
            errors.append(f"correlation candidate is a self-loop: {cause}")
    if (None, c.IM.causallyAffects, None) in overlay or (None, RDF.type, c.IM.CausalLink) in overlay:
        errors.append("overlay must not contain causallyAffects/CausalLink without a likelihoodScore definition")
    return errors


def shacl_checks(overlay: Graph, base: Graph) -> dict:
    """S1-S8 on base+overlay (inference none); violations on overlay nodes block loading.
    guards L4 (GT id) on the overlay alone."""
    from pyshacl import validate

    data = Graph()
    for t in base:
        data.add(t)
    for t in overlay:
        data.add(t)
    ont = Graph().parse(ONTOLOGY, format="turtle")
    shapes = Graph().parse(SHAPES, format="turtle")
    SH = Namespace("http://www.w3.org/ns/shacl#")

    def results_of(graph):
        _, res, _ = validate(graph, shacl_graph=shapes, ont_graph=ont, inference="none", abort_on_first=False,
                             allow_warnings=True)
        return {(str(res.value(r, SH.focusNode)), str(res.value(r, SH.resultMessage)))
                for r in res.subjects(RDF.type, SH.ValidationResult)}

    # Only violations the overlay introduces block loading; pre-existing base-KG results are reported.
    merged, base_results = results_of(data), results_of(base)
    blocking = [{"focus": f, "message": m} for f, m in sorted(merged - base_results)]
    base_only = len(base_results)
    guards = Graph().parse(GUARDS, format="turtle")
    _, gres, _ = validate(overlay, shacl_graph=guards, inference="none", abort_on_first=False)
    gt_hits = [str(gres.value(r, SH.focusNode)) for r in gres.subjects(RDF.type, SH.ValidationResult)
               if str(gres.value(r, SH.resultMessage)).startswith("L4")]
    return {"shacl_blocking": blocking, "shacl_base_only_results": base_only, "guards_L4": gt_hits,
            "guards_scope": "L1-L3 apply to step 6 input graphs only (guards/leakage_shapes.ttl header); "
                            "L4 applied to this step 7 overlay"}


def load(run_dir: Path, out: Path, base: Graph | None = None) -> dict:
    run_dir, out = Path(run_dir), Path(out)
    if out.exists():
        raise FileExistsError(f"overlay output exists (never overwritten): {out}")
    seal = verify_seal(run_dir)
    base = base if base is not None else c.load_graph()
    overlay, summary = build_overlay(run_dir, base)
    report = {"engine_run": run_dir.as_posix(), "engine_seal_sha256": v.digest(v.encoded(seal)), **summary,
              "loader_errors": loader_checks(overlay, base), **shacl_checks(overlay, base)}
    if report["loader_errors"] or report["shacl_blocking"] or report["guards_L4"]:
        raise OverlayRejected("overlay rejected: validation failed", report)
    out.mkdir(parents=True, exist_ok=False)
    overlay.serialize(out / "overlay.ttl", format="turtle")
    v.write(out / "overlay_report.json", report)
    v.write(out / "complete.json", {p.name: v.digest(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file()})
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=Path, required=True, help="sealed engine output directory")
    p.add_argument("--out", type=Path, required=True, help="new overlay directory")
    a = p.parse_args()
    try:
        report = load(a.run, a.out)
    except OverlayRejected as exc:
        print(json.dumps(exc.report, ensure_ascii=False, indent=2))
        raise SystemExit(f"REJECTED: {exc}")
    print(json.dumps({k: report[k] for k in ("events", "correlation_candidates", "causal_links", "skipped",
                                             "shacl_blocking", "shacl_base_only_results")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
