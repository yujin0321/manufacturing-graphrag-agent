"""Rule detector engine (stage 1 refactor, 2026-11-11).

KG compile -> rule IR -> time-series execution -> incident post-processing,
driven by one engine and a config file. Reproduces v3, v3-literal and v3.1
outputs exactly; legacy modules (rules.py, kg_rules.py, kg_rules_v3*.py) stay
untouched and are reused only for parsers and per-sample calculations.

  python -m imaks_kg.detection.engine.run --config v3_1 --out <new dir>
"""
