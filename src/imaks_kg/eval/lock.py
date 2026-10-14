"""정답 노출 통제: 정답을 읽기 전에 pre_evaluation_lock.json을 쓴다 (정의서 6장)."""
import json
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from imaks_kg.common.io_utils import write_json
from imaks_kg.eval.gold import file_sha256

LOCK_NAME = "pre_evaluation_lock.json"
LIBRARIES = ("sentence-transformers", "torch", "transformers", "scipy", "numpy")


class LockMismatch(RuntimeError):
    pass


def library_versions() -> dict:
    out = {}
    for name in LIBRARIES:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None  # 미설치
    return out


def build_lock(predictions: Path, definition: Path, model_name: str, revision: str, threshold: float,
               meta: dict | None = None) -> dict:
    return {
        "predictions_file": Path(predictions).name,
        "predictions_sha256": file_sha256(predictions),
        "definition_file": Path(definition).name,
        "definition_sha256": file_sha256(definition),
        "embedding_model": model_name,
        "embedding_model_revision_requested": revision,
        "libraries": library_versions(),
        "threshold": threshold,
        "written_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "meta": meta or {},  # 프롬프트·Example·스키마 해시, 요청/실제 사용 모델 (--meta JSON)
    }


# 이 값들이 다르면 같은 출력 폴더를 재사용할 수 없다 (정책을 조용히 바꾸는 것을 막는다)
_COMPARED = ("predictions_sha256", "definition_sha256", "embedding_model",
             "embedding_model_revision_requested", "threshold", "meta")


def write_lock(out_dir: Path, predictions: Path, definition: Path, model_name: str, revision: str,
               threshold: float, meta: dict | None = None) -> dict:
    """lock을 쓴다. 이미 있으면 비교만 하고(같으면 그대로 둠), 다르면 LockMismatch."""
    path = Path(out_dir) / LOCK_NAME
    new = build_lock(predictions, definition, model_name, revision, threshold, meta)
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        diff = [k for k in _COMPARED if old.get(k) != new[k]]
        if diff:
            raise LockMismatch(
                f"{path.name}이 이미 있고 다음 값이 다릅니다: {', '.join(diff)}. "
                "조용히 덮어쓰지 않습니다. 새 출력 폴더(--out-dir)를 쓰세요.")
        return old
    write_json(path, new)
    return new
