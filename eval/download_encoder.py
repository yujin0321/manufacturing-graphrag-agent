"""Download a pinned encoder snapshot; no dataset or API key is read."""
import hashlib
import json
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

root = Path(__file__).resolve().parents[1]
model_id = "sentence-transformers/all-MiniLM-L6-v2"
revision = HfApi().model_info(model_id).sha
snapshot = Path(snapshot_download(model_id, revision=revision, cache_dir=root / "evaluation/models",
    allow_patterns=["config.json", "config_sentence_transformers.json", "modules.json", "sentence_bert_config.json",
                    "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "vocab.txt",
                    "model.safetensors", "1_Pooling/config.json", "2_Normalize/config.json"]))
info = {"model": model_id, "revision": revision, "snapshot": str(snapshot.resolve()),
        "files": {str(p.relative_to(snapshot)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(snapshot.rglob("*")) if p.is_file()}}
(root / "evaluation/model_info.json").write_text(json.dumps(info, indent=2)+"\n", encoding="utf-8")
print(json.dumps({"model": model_id, "revision": revision, "files": len(info["files"])}))
