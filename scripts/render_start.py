
"""Download verified private runtime data, restore it, and start the Render server."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

RUNTIME_URL = (
    "https://api.github.com/repos/yujin0321/"
    "imaks-runtime-private/contents/imaks_agent_runtime_20261114.zip"
)

EXPECTED_SHA256 = (
    "998f36fa14318a4fcb2d88bf98c5228fa5dc54f861b406a02017ead23071d9ea"
)


def main():
    token = os.environ.get("GITHUB_RUNTIME_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_RUNTIME_TOKEN is not configured")

    request = urllib.request.Request(
        RUNTIME_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.raw+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "imaks-render-runtime",
        },
    )

    print("Downloading private runtime package...", flush=True)

    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()

    actual_sha256 = hashlib.sha256(data).hexdigest()

    if actual_sha256 != EXPECTED_SHA256:
        raise RuntimeError("Runtime SHA-256 verification failed")

    print("Runtime checksum verified.", flush=True)

    with tempfile.TemporaryDirectory() as directory:
        bundle = Path(directory) / "runtime.zip"
        bundle.write_bytes(data)

        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/agent_handoff.py"),
                "restore",
                str(bundle),
                "--target",
                str(ROOT),
            ],
            cwd=ROOT,
            check=True,
        )

    print("Runtime restored. Starting AI server...", flush=True)

    port = os.environ.get("PORT", "8770")

    os.execv(
        sys.executable,
        [
            sys.executable,
            str(ROOT / "scripts/run_xai_agent.py"),
            "--serve",
            "--allow-local-analysis",
            "--port",
            str(port),
            "--page",
            "sensor-ui/integration/serve-page.html",
        ],
    )


if __name__ == "__main__":
    main()
