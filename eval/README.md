# 현재 평가 실행 안내 (2026-10-14)

사용자 지정 기준은 docs/eval_definition_F1_content.md 및 docs/eval_definition_team_summary.md다.
현재 실행 프로그램은 evaluate_pipeline.py와 src/imaks_kg/eval/이다. 문서별 유효 매칭 수 우선 Hungarian, 임계 0.6, 정답 전체 86건 분모를 적용한다.

```powershell
evaluation/.venv/Scripts/python.exe -B eval/evaluate_pipeline.py --run-dir extraction/runs/<RUN_ID> --out-dir extraction/evaluation/<NEW_ID>
```

evaluate_rules.py의 load_b는 B 입력 변환에 사용하지만 기존 CLI 및 rule_matching.py는 아래 과거 평가 방식이다. 새 비교에는 사용하지 않는다.
상세 구현·결과는 reports/abc_gpt61_sol_full_handoff.md를 참고한다.

---

## 과거 구현 기록

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
