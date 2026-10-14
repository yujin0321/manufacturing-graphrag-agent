"""Read the local Gemini key without logging it or modifying the environment."""
import os
from pathlib import Path

from imaks_kg.settings import REPO_ROOT


def read_gemini_key(env_file: Path | None = None) -> str:
    path = env_file if env_file is not None else REPO_ROOT / ".env"
    value = ""
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, separator, candidate = line.partition("=")
            if separator and name.strip() == "GEMINI_API_KEY":
                value = candidate.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1].strip()
    value = value or os.environ.get("GEMINI_API_KEY", "").strip()
    if not value or value == "PASTE_YOUR_KEY_HERE":
        raise ValueError("Set GEMINI_API_KEY in the project's .env file.")
    return value


if __name__ == "__main__":
    try:
        read_gemini_key()
    except ValueError:
        print("Gemini key is not configured yet. Edit .env; never paste the key into chat.")
        raise SystemExit(1)
    print("Gemini key is configured. Value hidden; API connection not tested.")
