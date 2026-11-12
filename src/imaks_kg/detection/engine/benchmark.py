"""Stage 4: label-free evaluation of engine configs.

Two views, neither reads dataset labels or the published evaluation:

1. Label-free metrics on the frozen input: alarm and incident rates per
   sensor-day, by kind/type/severity, monitoring windows and links.
2. Synthetic benchmark: SOP-002 anomaly shapes (from the KG type definitions
   and the sensors' SOP-002 bands) are injected into *host windows* of the
   frozen input, and each config is scored against the injected truth.
   Host windows are chosen config-independently: whole window inside the WARN
   band and no v2 threshold/document-rule alarm within +/-1 h on that sensor.
   Calibration (sigma) is fixed from the unmodified input.

Design fixed before the first benchmark run (2026-11-11): shapes, magnitudes,
seeds (0, 1, 2), grace 10 min. Two construction amendments after the first run
(recorded in work_log): the OUT_OF_RANGE injection was a flat line, which is
also a STUCK shape by definition, so it now keeps the sensor's noise; and an
anchor decoy scenario was added because no scenario separated the
monitoring anchors. No detector parameter was changed on benchmark results.

  python -m imaks_kg.detection.engine.benchmark --configs v3 v3_1 v3_2 --out kg_build/engine_benchmark_20261111
"""
from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from imaks_kg.rag import comparison as c
from imaks_kg.rag import vector as v

from .. import kg_rules as k2
from .. import rules as v1
from . import compiler, config, executor
from .run import pipeline

SEEDS = (0, 1, 2)
HOST_HOURS = 4
CLEAR_MIN = 60
GRACE_MIN = 10
PER_TYPE = 3                     # injections per type per seed (single-sensor types)
CAUSE, EFFECT = "ST02_SEALING_CUR", "ST04_PACKAGING_SPD"
STEP = 30


# ------------------------------------------------------------------ label-free metrics
def label_free(result: dict, n_sensors: int, days: float) -> dict:
    alarms, incidents = result["events"], result["incidents"]
    count = lambda xs, key: {k: sum(x[key] == k for x in xs) for k in sorted({x[key] for x in xs})}  # noqa: E731
    return {"alarms": len(alarms), "alarms_per_sensor_day": round(len(alarms) / (n_sensors * days), 3),
            "incidents": len(incidents), "incidents_per_day": round(len(incidents) / days, 3),
            "alarms_by_kind": count(alarms, "kind"), "incidents_by_type": count(incidents, "anomaly_type"),
            "incidents_by_severity": count(incidents, "severity"),
            "slope_signals": len(result["signals"]), "monitor_windows": len(result["monitor_windows"]),
            "correlation_links": len(result["correlations"]),
            "sensors_with_incidents": len({i["sensor_id"] for i in incidents})}


# ------------------------------------------------------------------ hosts and injections
def _ts(rows):
    return [datetime.fromisoformat(r["timestamp"]) for r in rows]


def host_windows(groups: dict, bundle: dict) -> dict:
    """sensor -> list of start indices of clean HOST_HOURS windows (config independent)."""
    n_host = HOST_HOURS * 3600 // STEP
    clear = timedelta(minutes=CLEAR_MIN)
    v2_rules = [r for r in bundle["rules"] if r["executor"] == "threshold_scan"]
    hosts = {}
    for sid, rows in groups.items():
        info = bundle["sensors"][sid]
        x = np.array([float(r["value"]) for r in rows])
        ts = _ts(rows)
        alarms = []
        for ir in (r for r in v2_rules if r["sensor_id"] == sid):
            rule = {"sensor_id": sid, "rule_id": ir["rule_id"], "kind": ir["kind"], "unit": ir["unit"], **{
                k: ir["params"][k] for k in ("op", "value", "second", "duration_seconds")}}
            alarms += [(datetime.fromisoformat(a["trigger_at"]), datetime.fromisoformat(a["last_positive_at"]))
                       for a in k2.scan(rows, rule)]
        inside = (x > info["warnLo"]) & (x < info["warnHi"])
        starts = []
        for i in range(0, len(rows) - n_host, n_host // 2):
            j = i + n_host - 1
            if (ts[j] - ts[i]).total_seconds() != (n_host - 1) * STEP or not inside[i:j + 1].all():
                continue
            if any(a0 <= ts[j] + clear and a1 >= ts[i] - clear for a0, a1 in alarms):
                continue
            starts.append(i)
        hosts[sid] = starts
    return hosts


def _set(rows, i, value):
    rows[i] = {**rows[i], "value": repr(round(float(value), 4))}


def inject(groups: dict, bundle: dict, sigmas: dict, hosts: dict, seed: int) -> tuple[dict, list[dict]]:
    """Copy of groups with injected anomalies, and the truth list."""
    rng = np.random.default_rng(seed)
    out = dict(groups)
    used: dict[str, set[int]] = {}
    truth = []
    singles = [s for s in groups if s not in (CAUSE, EFFECT) and hosts[s]]

    def take(sid):
        free = [h for h in hosts[sid] if h not in used.get(sid, set())
                and all(abs(h - u) >= len(groups[sid]) // 20 for u in used.get(sid, set()))]
        if not free:
            return None
        h = int(rng.choice(free))
        used.setdefault(sid, set()).add(h)
        if out[sid] is groups[sid]:
            out[sid] = copy.copy(groups[sid])
        return h + 3600 // STEP  # injection starts 1 h into the host window

    def record(sid, kind, variant, i0, i1, **extra):
        rows = out[sid]
        truth.append({"sensor_id": sid, "type": kind, "variant": variant, "start": rows[i0]["timestamp"],
                      "end": rows[i1]["timestamp"], **extra})

    for kind in ("SPIKE", "OUT_OF_RANGE", "STUCK", "DRIFT_FAST", "DRIFT_SLOW"):
        for sid in rng.choice(singles, size=PER_TYPE, replace=False):
            sid = str(sid)
            i0 = take(sid)
            if i0 is None:
                continue
            info, rows = bundle["sensors"][sid], out[sid]
            up = bool(rng.integers(0, 2))
            warn, crit = (info["warnHi"], info["critHi"]) if up else (info["warnLo"], info["critLo"])
            mid = warn + 0.5 * (crit - warn)
            if kind == "SPIKE":
                n = int(rng.choice([1, 2, 4]))
                for k in range(n):
                    _set(rows, i0 + k, crit + 0.25 * (crit - warn))
                record(sid, "SPIKE", f"{n}_samples", i0, i0 + n - 1)
            elif kind == "OUT_OF_RANGE":
                # step offset that keeps the sensor's own noise (a flat line would also be STUCK)
                base = float(rows[i0]["value"])
                for k in range(60):
                    _set(rows, i0 + k, float(rows[i0 + k]["value"]) + (mid - base))
                record(sid, "OUT_OF_RANGE", "30min_mid_band_noisy", i0, i0 + 59)
            elif kind == "STUCK":
                frozen = float(rows[i0]["value"])
                for k in range(30):
                    _set(rows, i0 + k, frozen)
                record(sid, "STUCK", "15min_constant", i0, i0 + 29)
            else:
                minutes = 30 if kind == "DRIFT_FAST" else 90
                n = minutes * 60 // STEP
                base = float(rows[i0]["value"])
                for k in range(n + 20):  # ramp to mid band, hold 10 min
                    frac = min(k / n, 1.0)
                    _set(rows, i0 + k, float(rows[i0 + k]["value"]) + frac * (mid - base))
                record(sid, "DRIFT", f"ramp_{minutes}min", i0, i0 + n + 19)
    # CORRELATED (RULE-ST02-04 / SOP-003-EX-01): cause WARNING excursion, then effect speed reduction.
    for variant, lag_min, strong in (("lag20_subtle", 20, False), ("lag60_strong", 60, True)):
        cands = sorted(set(hosts[CAUSE]) & set(hosts[EFFECT]))
        cands = [h for h in cands if all(abs(h - u) >= len(groups[CAUSE]) // 20
                                         for u in used.get(CAUSE, set()) | used.get(EFFECT, set()))]
        if not cands:
            continue
        h = int(rng.choice(cands))
        for sid in (CAUSE, EFFECT):
            used.setdefault(sid, set()).add(h)
            if out[sid] is groups[sid]:
                out[sid] = copy.copy(groups[sid])
        i0 = h + 3600 // STEP
        ci, ei = bundle["sensors"][CAUSE], bundle["sensors"][EFFECT]
        for k in range(4):  # 2 min just above WARN, below CRIT
            _set(out[CAUSE], i0 + k, ci["warnHi"] + 0.3 * (ci["critHi"] - ci["warnHi"]))
        e0 = i0 + lag_min * 60 // STEP
        n = 30 * 60 // STEP
        drop = ((ei["warnLo"] - 0.3 * (ei["warnLo"] - ei["critLo"])) - ei["nominal"] if strong
                else -6 * sigmas[EFFECT]["sigma"])  # subtle: 0.2 sigma/min, stays inside the WARN band
        for k in range(n + 20):
            frac = min(k / n, 1.0)
            _set(out[EFFECT], e0 + k, float(out[EFFECT][e0 + k]["value"]) + frac * drop)
        truth.append({"sensor_id": EFFECT, "type": "CORRELATED", "variant": variant,
                      "start": out[EFFECT][e0]["timestamp"], "end": out[EFFECT][e0 + n + 19]["timestamp"],
                      "cause_sensor": CAUSE, "cause_start": out[CAUSE][i0]["timestamp"],
                      "cause_end": out[CAUSE][i0 + 3]["timestamp"]})
    # Anchor decoy (RULE-ST02-04 "whenever ST02 CUR triggers a WARNING"): the cause incident opens with a
    # MAINT-02 alarm (|x - nominal| > 1.0 A for 30+ min, still inside the WARN band); the WARNING comes
    # 20 min later. A subtle effect speed reduction starts 10 min BEFORE the WARNING, so by the rule text
    # it is not a reaction to the warning. Expected: no correlation link.
    cands = sorted(set(hosts[CAUSE]) & set(hosts[EFFECT]))
    cands = [h for h in cands if all(abs(h - u) >= len(groups[CAUSE]) // 20
                                     for u in used.get(CAUSE, set()) | used.get(EFFECT, set()))]
    if cands:
        h = int(rng.choice(cands))
        for sid in (CAUSE, EFFECT):
            used.setdefault(sid, set()).add(h)
            if out[sid] is groups[sid]:
                out[sid] = copy.copy(groups[sid])
        i0 = h + 3600 // STEP
        ci, ei = bundle["sensors"][CAUSE], bundle["sensors"][EFFECT]
        plateau = ci["nominal"] + 0.5 * ((ci["warnHi"] - ci["nominal"]) + 1.0)  # between nominal+1.0 and warnHi
        hold = 50 * 60 // STEP                                                 # MAINT-02 fires after 30 min
        for k in range(hold):
            # plateau plus 5 % of the sensor's own deviation (keeps small noise, stays inside the WARN band)
            _set(out[CAUSE], i0 + k, plateau + (float(groups[CAUSE][i0 + k]["value"]) - ci["nominal"]) * 0.05)
        w0 = i0 + hold
        for k in range(4):
            _set(out[CAUSE], w0 + k, ci["warnHi"] + 0.3 * (ci["critHi"] - ci["warnHi"]))
        e0 = w0 - 10 * 60 // STEP
        n = 30 * 60 // STEP
        for k in range(n + 20):
            _set(out[EFFECT], e0 + k, float(out[EFFECT][e0 + k]["value"]) - min(k / n, 1.0) * 6 * sigmas[EFFECT]["sigma"])
        truth.append({"sensor_id": EFFECT, "type": "DECOY_NO_LINK", "variant": "effect_before_warning",
                      "start": out[EFFECT][e0]["timestamp"], "end": out[EFFECT][e0 + n + 19]["timestamp"],
                      "cause_sensor": CAUSE, "cause_start": out[CAUSE][i0]["timestamp"],
                      "cause_end": out[CAUSE][w0 + 3]["timestamp"], "warning_at": out[CAUSE][w0]["timestamp"]})
    return out, truth


# ------------------------------------------------------------------ scoring
def _overlap(inc, sensor, t0, t1, grace):
    return (inc["sensor_id"] == sensor and datetime.fromisoformat(inc["start"]) <= t1 + grace
            and datetime.fromisoformat(inc["end"]) >= t0)


def score(result: dict, truth: list[dict]) -> dict:
    grace = timedelta(minutes=GRACE_MIN)
    incidents = result["incidents"]
    by_id = {i["id"]: i for i in incidents}
    rows = []
    for t in truth:
        t0, t1 = datetime.fromisoformat(t["start"]), datetime.fromisoformat(t["end"])
        hits = sorted((i for i in incidents if _overlap(i, t["sensor_id"], t0, t1, grace)), key=lambda i: i["start"])
        row = {**t, "detected": bool(hits)}
        if hits:
            row["latency_min"] = (datetime.fromisoformat(hits[0]["start"]) - t0).total_seconds() / 60
            row["predicted_type"] = hits[0]["anomaly_type"]
            row["type_correct"] = hits[0]["anomaly_type"] == t["type"]
        if t["type"] in ("CORRELATED", "DECOY_NO_LINK"):
            c0, c1 = datetime.fromisoformat(t["cause_start"]), datetime.fromisoformat(t["cause_end"])
            row["link_correct"] = any(
                l["effect_incident"] in {h["id"] for h in hits}
                and _overlap(by_id[l["cause_incident"]], t["cause_sensor"], c0, c1, grace)
                for l in result["correlations"])
        rows.append(row)
    return {"rows": rows}


def summarize(rows: list[dict]) -> dict:
    out = {}
    for kind in sorted({r["type"] for r in rows}) + ["ALL"]:
        rs = [r for r in rows if (kind == "ALL" and r["type"] != "DECOY_NO_LINK") or r["type"] == kind]
        det = [r for r in rs if r["detected"]]
        lat = [r["latency_min"] for r in det]
        out[kind] = {"injected": len(rs), "detected": len(det),
                     "type_correct": sum(r.get("type_correct", False) for r in det),
                     "median_latency_min": float(np.median(lat)) if lat else None}
        if kind == "CORRELATED":
            out[kind]["link_correct"] = sum(r.get("link_correct", False) for r in rs)
        if kind == "DECOY_NO_LINK":
            out[kind]["false_link"] = sum(r.get("link_correct", False) for r in rs)
    return out


def spurious(result: dict, truth: list[dict], baseline_ids: set[tuple]) -> int:
    """Incidents that exist only in the injected run, overlap no truth window
    (with grace) and are not cause excursions: side effects of the injection."""
    grace = timedelta(minutes=GRACE_MIN)
    windows = [(t["sensor_id"], datetime.fromisoformat(t["start"]), datetime.fromisoformat(t["end"])) for t in truth]
    windows += [(t["cause_sensor"], datetime.fromisoformat(t["cause_start"]), datetime.fromisoformat(t["cause_end"]))
                for t in truth if t["type"] in ("CORRELATED", "DECOY_NO_LINK")]
    n = 0
    for i in result["incidents"]:
        if (i["sensor_id"], i["start"]) in baseline_ids:
            continue
        if not any(_overlap(i, s, a, b, grace) for s, a, b in windows):
            n += 1
    return n


def run_benchmark(cfg_names: list[str], out: Path) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    groups, _, _ = v1.read_inputs()
    bundle = compiler.compile_ir(c.load_graph())
    cfgs = {n: config.load(n) for n in cfg_names}
    sigmas = executor.calibrate(groups, next(iter(cfgs.values())))
    ts = _ts(next(iter(groups.values())))
    days = (ts[-1] - ts[0]).total_seconds() / 86400 + STEP / 86400
    report = {"design": {"seeds": SEEDS, "host_hours": HOST_HOURS, "clear_min": CLEAR_MIN, "grace_min": GRACE_MIN,
                         "per_type": PER_TYPE, "correlated_pair": [CAUSE, EFFECT],
                         "labels_read": False, "published_evaluation_used": False},
              "label_free": {}, "synthetic": {}}
    baseline = {}
    for name, cfg in cfgs.items():
        res, _ = pipeline(groups, bundle, cfg, sigmas)
        baseline[name] = {(i["sensor_id"], i["start"]) for i in res["incidents"]}
        report["label_free"][name] = label_free(res, len(groups), days)
    hosts = host_windows(groups, bundle)
    report["design"]["host_windows_per_sensor"] = {s: len(h) for s, h in hosts.items()}
    all_truth = {}
    for seed in SEEDS:
        injected, truth = inject(groups, bundle, sigmas, hosts, seed)
        all_truth[seed] = truth
        for name, cfg in cfgs.items():
            res, _ = pipeline(injected, bundle, cfg, sigmas)
            entry = report["synthetic"].setdefault(name, {"rows": [], "spurious_incidents": 0})
            entry["rows"] += [{**r, "seed": seed} for r in score(res, truth)["rows"]]
            entry["spurious_incidents"] += spurious(res, truth, baseline[name])
    for name, entry in report["synthetic"].items():
        entry["summary"] = summarize(entry["rows"])
    v.write(out / "truth.json", all_truth)
    v.write(out / "benchmark.json", report)
    v.write(out / "complete.json", {p.name: v.digest(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file()})
    return report


def markdown(report: dict) -> str:
    names = list(report["label_free"])
    lines = ["# 룰 탐지 엔진 정답 비의존 평가 (2026-11-11)", "",
             "데이터셋 라벨과 공개된 평가 결과는 읽지 않았다. 아래 두 지표만 쓴다.", "",
             "## 1. 라벨 없는 지표 (원본 입력)", "",
             "| 지표 | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for key in ("alarms", "alarms_per_sensor_day", "incidents", "incidents_per_day", "slope_signals",
                "monitor_windows", "correlation_links", "sensors_with_incidents"):
        lines.append(f"| {key} | " + " | ".join(str(report["label_free"][n][key]) for n in names) + " |")
    for key in ("incidents_by_type", "incidents_by_severity"):
        lines.append(f"| {key} | " + " | ".join(json.dumps(report["label_free"][n][key], ensure_ascii=False)
                                                 for n in names) + " |")
    d = report["design"]
    lines += ["", "## 2. 합성 주입 벤치마크", "",
              f"시드 {list(d['seeds'])}, 단일 센서 유형마다 시드당 {d['per_type']}건, 상관 2건(시차 20분 미세 저하, 60분 경고 이탈), "
              "기준 시각 미끼 1건(원인 사건이 MAINT-02로 먼저 시작하고 WARNING은 20분 뒤, 결과 저하는 WARNING 10분 전 시작: 연결되면 오연결). "
              f"호스트 구간: {d['host_hours']}시간 동안 WARN 대역 안, ±{d['clear_min']}분 안에 v2 알람 없음(설정과 무관). "
              f"판정: 주입 구간(끝 +{d['grace_min']}분)과 겹치는 같은 센서 사건. σ는 원본 입력으로 고정.", "",
              "| 유형 | 지표 | " + " | ".join(names) + " |", "|---|---|" + "---|" * len(names)]
    kinds = list(report["synthetic"][names[0]]["summary"])
    for kind in kinds:
        for metric in ("detected", "type_correct", "median_latency_min", "link_correct", "false_link"):
            vals = [report["synthetic"][n]["summary"][kind].get(metric) for n in names]
            if all(x is None for x in vals) and metric in ("link_correct", "false_link"):
                continue
            inj = report["synthetic"][names[0]]["summary"][kind]["injected"]
            fmt = [("-" if x is None else f"{x}/{inj}" if metric in ("detected", "type_correct", "link_correct", "false_link")
                    else f"{x:.1f}") for x in vals]
            lines.append(f"| {kind} | {metric} | " + " | ".join(fmt) + " |")
    lines.append("| (전체) | 주입 부작용 사건 | " + " | ".join(str(report["synthetic"][n]["spurious_incidents"])
                                                  for n in names) + " |")
    lines += ["", "## 3. 해석 주의", "",
              "- 합성 모양은 SOP-002 정의를 그대로 옮긴 것이라 실제 이상의 다양성을 대표하지 않는다.",
              "- 호스트 구간은 WARN 대역 안이지만 라벨로 확인한 정상 구간은 아니다(라벨을 읽지 않음).",
              "- 공개 정답(14건) 평가는 설계·합성 평가·봉인 뒤 마지막에 1회만 한다.", ""]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--configs", nargs="+", default=["v3", "v3_1", "v3_2"])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--report-md", type=Path)
    a = p.parse_args()
    report = run_benchmark(a.configs, a.out)
    if a.report_md:
        a.report_md.write_text(markdown(report), encoding="utf-8")
    print(markdown(report))


if __name__ == "__main__":
    main()
