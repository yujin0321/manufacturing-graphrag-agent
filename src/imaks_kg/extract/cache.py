"""응답 캐시. 검증을 통과한 응답만 재사용한다(파일 존재만으로 건너뛰지 않는다).

- put(): 응답을 저장하지만 '검증 전' 상태. get_validated()는 돌려주지 않는다.
- mark_validated(key): 2단계 검증기가 코드 검증을 통과시킨 뒤 호출한다. 그때부터 재사용된다.
- 검증 표시는 별도 파일({key}.validated.json). 저장된 응답의 해시가 기록과 다르면 재사용하지 않는다.
- 캐시 키: 문서, 프롬프트, Example, 스키마, 입력 전체, 모델(공급자+설정)을 합친 SHA-256.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from imaks_kg.settings import IMAKS_DATA


def make_cache_key(request, model_fingerprint: str) -> str:
    payload = {"doc_id": request.doc_id, "prompt_sha256": request.prompt_sha256,
               "example_sha256": request.example_sha256, "schema_sha256": request.schema_sha256,
               "input_sha256": request.input_sha256, "expect_json": request.expect_json,
               "model_fingerprint": model_fingerprint}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, cache_dir, now=datetime.now):
        d = Path(cache_dir).resolve()
        if d == IMAKS_DATA or IMAKS_DATA in d.parents:
            raise PermissionError("imaks_data는 읽기 전용입니다. 캐시를 쓸 수 없습니다.")
        self.dir = d
        self.now = now

    def _entry(self, key):
        return self.dir / f"{key}.entry.json"

    def _marker(self, key):
        return self.dir / f"{key}.validated.json"

    def put(self, key: str, entry: dict) -> None:
        """검증 전 상태로 저장. 이미 검증된 키는 덮어쓰지 않는다."""
        if self._marker(key).exists():
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        rec = dict(entry)
        rec["key"] = key
        rec["text_sha256"] = hashlib.sha256(rec["text"].encode("utf-8")).hexdigest()
        rec["stored_at"] = self.now().isoformat(timespec="seconds")
        tmp = self.dir / f"{key}.entry.tmp"
        tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8", newline="\n")
        os.replace(tmp, self._entry(key))

    def mark_validated(self, key: str, validator: str = "") -> None:
        """2단계 검증기가 호출한다. 저장된 응답의 해시를 함께 고정한다."""
        p = self._entry(key)
        if not p.is_file():
            raise KeyError(f"캐시 항목이 없습니다: {key[:12]}")
        rec = json.loads(p.read_text(encoding="utf-8"))
        marker = {"key": key, "text_sha256": rec["text_sha256"], "validator": validator,
                  "validated_at": self.now().isoformat(timespec="seconds")}
        self._marker(key).write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8", newline="\n")

    def is_validated(self, key: str) -> bool:
        return self.get_validated(key) is not None

    def get_validated(self, key: str):
        """검증 표시가 있고 저장된 응답이 표시 당시와 같을 때만 항목을 돌려준다."""
        pe, pm = self._entry(key), self._marker(key)
        if not (pe.is_file() and pm.is_file()):
            return None
        try:
            rec = json.loads(pe.read_text(encoding="utf-8"))
            mk = json.loads(pm.read_text(encoding="utf-8"))
        except ValueError:
            return None
        actual = hashlib.sha256(rec.get("text", "").encode("utf-8")).hexdigest()
        if actual != mk.get("text_sha256") or actual != rec.get("text_sha256"):
            return None
        return rec
