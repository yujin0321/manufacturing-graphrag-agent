"""Gemini REST extraction. Secrets are headers only and never written to artifacts."""
import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .common import OUT, CLASSES, digest, read_jsonl, write_json, write_jsonl
from .local_config import read_gemini_key

MODEL = "gemini-3.8-flash"
FREE_MODELS = {"gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite"}
STRING = {"type": "string"}
NULL_STRING = {"type": ["string", "null"]}
NULL_INT = {"type": ["integer", "null"]}
EVIDENCE = {"type": "object", "properties": {
    "supports": {"type": "array", "items": {"type": "string", "enum": ["condition", "action", "severity", "sensors", "action_targets", "printed_rule_id", "class"]}},
    "chunk_id": STRING, "source_quote": STRING, "table_id": NULL_STRING,
    "table_row": NULL_INT, "table_col": NULL_INT},
    "required": ["supports", "chunk_id", "source_quote", "table_id", "table_row", "table_col"]}
RULE = {"type": "object", "properties": {
    "class": {"type": "string", "enum": list(CLASSES)}, "printed_rule_id": NULL_STRING,
    "condition": STRING, "action": STRING, "severity": STRING,
    "sensors": {"type": "array", "items": STRING},
    "action_targets": {"type": "array", "items": STRING},
    "evidence": {"type": "array", "items": EVIDENCE}},
    "required": ["class", "printed_rule_id", "condition", "action", "severity", "sensors", "action_targets", "evidence"]}
SCHEMA = {"type": "object", "properties": {"rules": {"type": "array", "items": RULE}}, "required": ["rules"]}


def run(run_name, only=None, model=MODEL, thinking="auto"):
    if not run_name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in run_name):
        raise ValueError("Use a lowercase run name")
    if model not in FREE_MODELS:
        raise ValueError("Choose a model from the verified free-tier allowlist")
    key = read_gemini_key()
    folder = OUT / "model_calls" / run_name
    folder.mkdir(parents=True, exist_ok=True)
    requests = read_jsonl(OUT / "requests.jsonl")
    config = {"provider": "Google Gemini Developer API", "requested_model": model,
              "temperature": 0, "max_output_tokens": 32768,
              "requests_sha256": digest((OUT / "requests.jsonl").read_bytes()),
              "schema_sha256": digest(json.dumps(SCHEMA, sort_keys=True)),
              "ground_truth_supplied": False}
    if thinking != "auto":
        config["thinking_level"] = thinking
    config_path = folder / "config.json"
    if config_path.exists() and json.loads(config_path.read_text(encoding="utf8")) != config:
        raise ValueError("Cannot resume with different configuration")
    write_json(config_path, config)
    write_jsonl(folder / "requests.jsonl", requests)
    selected = sorted([r for r in requests if only is None or r["request_id"] == only],
                      key=lambda r: (not r["request_id"].startswith("SOP-"), r["request_id"]))
    failed = []
    if not selected:
        raise ValueError("Unknown document")
    for r in selected:
        path = folder / (r["request_id"] + ".response.json")
        if path.exists():
            print("Cached", r["request_id"], flush=True)
            continue
        body = {"systemInstruction": {"parts": [{"text": r["system"]}]},
                "contents": [{"role": "user", "parts": [{"text": json.dumps(r["input"], ensure_ascii=False)}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 32768,
                                     "responseMimeType": "application/json", "responseJsonSchema": SCHEMA}}
        if thinking != "auto":
            body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": thinking}
        req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent",
                                     data=json.dumps(body).encode("utf8"),
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        started = time.monotonic()
        print("Calling", r["request_id"], flush=True)
        raw = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=240) as response:
                    raw = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf8", errors="replace").replace(key, "[REDACTED]")
                write_json(folder / (r["request_id"] + ".error-" + str(time.time_ns()) + ".json"),
                           {"status": exc.code, "detail": detail})
                if exc.code in (500, 502, 503, 504) and attempt < 2:
                    print("Temporary server error", exc.code, "retry", attempt + 1, flush=True)
                    time.sleep(20 * (attempt + 1))
                    continue
                if len(selected) > 1 and exc.code in (500, 502, 503, 504):
                    failed.append(r["request_id"])
                    print("Deferred", r["request_id"], "server unavailable", flush=True)
                    break
                raise RuntimeError("Gemini HTTP " + str(exc.code) + "; see redacted error artifact") from None
            except (TimeoutError, urllib.error.URLError) as exc:
                write_json(folder / (r["request_id"] + ".timeout-" + str(time.time_ns()) + ".json"),
                           {"error_type": type(exc).__name__, "attempt": attempt + 1})
                if len(selected) > 1:
                    failed.append(r["request_id"])
                    print("Deferred", r["request_id"], "connection timeout", flush=True)
                    break
                raise RuntimeError("Gemini connection timeout; progress preserved") from None
        if raw is None:
            continue
        write_json(folder / (r["request_id"] + ".raw.json"), raw)
        candidate = raw.get("candidates", [{}])[0]
        if candidate.get("finishReason") != "STOP":
            raise ValueError("Incomplete/blocked response; preserved raw, finish=" + str(candidate.get("finishReason")))
        text = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []) if not p.get("thought"))
        parsed = json.loads(text)
        result = {"provider": "Google Gemini Developer API", "model": raw.get("modelVersion", model),
                  "requested_model": model, "request_id": r["request_id"], "request_sha256": r["request_sha256"],
                  "usage": raw.get("usageMetadata", {}), "elapsed_seconds": round(time.monotonic() - started, 2),
                  "received_at_utc": datetime.now(timezone.utc).isoformat(), "rules": parsed["rules"]}
        write_json(path, result)
        print("Saved", r["request_id"], "rules=" + str(len(parsed["rules"])), flush=True)
        # Be conservative with free-tier per-minute limits.
        if len(selected) > 1:
            time.sleep(15)
    complete = [folder / (r["request_id"] + ".response.json") for r in requests]
    if all(p.exists() for p in complete):
        write_jsonl(folder / "responses.jsonl", [json.loads(p.read_text(encoding="utf8")) for p in complete])
        print("All documents saved:", folder / "responses.jsonl", flush=True)
    elif failed:
        print("Remaining documents:", ", ".join(failed), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--only")
    parser.add_argument("--model", default=MODEL, choices=sorted(FREE_MODELS))
    parser.add_argument("--thinking", default="auto", choices=["auto", "low", "medium", "high"])
    args = parser.parse_args()
    run(args.run_name, args.only, args.model, args.thinking)
