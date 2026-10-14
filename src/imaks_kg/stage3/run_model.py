"""Provider-neutral extraction runner.

An adapter reads one JSON request from stdin and emits one JSON response with
provider, model, rules, and optionally usage. Credentials remain in environment.
The adapter command is passed as an argument vector, never through a shell.
"""
import argparse
import json
import os
import subprocess
from pathlib import Path

from .common import OUT, digest, read_jsonl, write_json, write_jsonl
from .extract import validate_rules
from .local_config import read_gemini_key


def run(command, run_name, timeout=180):
    if not run_name or Path(run_name).name != run_name or run_name in (".", ".."):
        raise ValueError("run_name must be a directory name")
    requests = read_jsonl(OUT / "requests.jsonl")
    adapter_env = os.environ.copy()
    adapter_env["GEMINI_API_KEY"] = read_gemini_key()
    folder = OUT / "model_calls" / run_name
    if folder.exists():
        raise ValueError("Choose a fresh run name to preserve responses")
    folder.mkdir(parents=True)
    write_json(folder / "config.json", {"command": command, "timeout_seconds": timeout,
        "requests_sha256": digest((OUT / "requests.jsonl").read_bytes()), "request_count": len(requests)})
    responses = []
    for request in requests:
        result = subprocess.run(command, input=json.dumps(request, ensure_ascii=False), text=True,
                                encoding="utf-8", capture_output=True, timeout=timeout, shell=False,
                                env=adapter_env)
        # Preserve raw response even if validation fails. Avoid capturing stderr (may contain secrets).
        raw = folder / (request["request_id"] + ".txt")
        raw.write_text(result.stdout, encoding="utf-8")
        if result.returncode:
            raise RuntimeError("Adapter failed for " + request["request_id"] + "; exit=" + str(result.returncode))
        response = json.loads(result.stdout)
        if not response.get("model") or not response.get("provider"):
            raise ValueError("Adapter must report actual model/provider")
        response.update(request_id=request["request_id"], request_sha256=request["request_sha256"])
        validate_rules([{**r, "prediction_id": request["request_id"] + ":" + str(i), "doc_id": request["request_id"]}
                        for i, r in enumerate(response["rules"])])
        responses.append(response)
        write_jsonl(folder / "responses.jsonl", responses)
    print(folder / "responses.jsonl")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--run-name", required=True)
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args()
    command = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not command:
        p.error("Provide an adapter command after --")
    run(command, a.run_name, a.timeout)
