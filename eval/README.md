# Rule evaluation

This directory contains evaluation code only. Output data, the encoder and the
separate Python environment live under ignored `evaluation/`. Extraction does
not import this directory or read the reference CSV.

1. Install `requirements.lock.txt` into `evaluation/.venv`.
2. Run `evaluation/.venv/Scripts/python.exe eval/download_encoder.py` once.
3. Read the returned snapshot path from `evaluation/model_info.json`.
4. Run `evaluation/.venv/Scripts/python.exe eval/test_rule_matching.py`.
5. Run `evaluation/.venv/Scripts/python.exe eval/evaluate_rules.py --run-dir
   extraction/runs/RUN_ID --stage prereview --model-path SNAPSHOT_PATH --out-dir
   evaluation/rule_metrics/RUN_ID_prereview`.
6. After explicitly approved human review, run the same command with
   `--stage reviewed` and a new output directory.

No output is overwritten. Use a fresh output directory for every evaluation.
See `evaluation_protocol.md` for the fixed scoring definition and limitations.
