"""호출 기록: JSONL(호출마다 한 줄) + 응답 원문 파일(독점 생성 'x', 변경 불가).

- 헤더, 키, URL은 기록하지 않는다. 모든 문자열은 마스킹 함수를 거쳐 기록한다(현재 환경의 키 값 포함).
- 응답 원문은 {log_dir}/raw/{call_id}.txt 에 'xb'로 쓴다. 같은 이름이 있으면 FileExistsError.
- 기록 위치는 imaks_data 아래가 될 수 없다.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets as _secrets
from datetime import datetime
from pathlib import Path

from imaks_kg.extract.connectivity import mask
from imaks_kg.settings import IMAKS_DATA


def new_run_id(now=None) -> str:
    return (now or datetime.now()).strftime("%Y%m%dT%H%M%S") + "-" + _secrets.token_hex(3)


class CallLogger:
    def __init__(self, log_dir, run_id=None, key_env_names=(), now=datetime.now):
        d = Path(log_dir).resolve()
        if d == IMAKS_DATA or IMAKS_DATA in d.parents:
            raise PermissionError("imaks_data는 읽기 전용입니다. 호출 기록을 쓸 수 없습니다.")
        self.log_dir = d
        self.raw_dir = d / "raw"
        self.run_id = run_id or new_run_id()
        self.key_env_names = list(key_env_names)
        self.now = now
        self._seq = 0
        self.jsonl_path = d / f"calls_{self.run_id}.jsonl"

    def _secret_values(self):
        return [os.environ[n] for n in self.key_env_names if os.environ.get(n)]

    def clean(self, text) -> str:
        return mask(text, self._secret_values())

    def new_call_id(self) -> str:
        self._seq += 1
        return f"{self.run_id}-{self._seq:04d}"

    def timestamp(self) -> str:
        return self.now().isoformat(timespec="seconds")

    def write_raw(self, call_id: str, text: str) -> dict:
        """응답 원문을 독점 생성 모드로 저장. 반환: 로그 폴더 기준 상대 경로, SHA-256(저장된 바이트), 마스킹 여부."""
        stored = self.clean(text)
        data = stored.encode("utf-8")
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        p = self.raw_dir / f"{call_id}.txt"
        with open(p, "xb") as f:  # 같은 이름이 있으면 FileExistsError(덮어쓰기 불가)
            f.write(data)
        return {"raw_file": f"raw/{call_id}.txt", "response_sha256": hashlib.sha256(data).hexdigest(),
                "raw_masked": stored != text}

    def append(self, record: dict) -> None:
        """JSONL 한 줄 추가. 직렬화한 문자열 전체를 마스킹한 뒤 쓴다."""
        rec = dict(record)
        rec.setdefault("run_id", self.run_id)
        rec.setdefault("time", self.timestamp())
        line = self.clean(json.dumps(rec, ensure_ascii=False))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with open(self.jsonl_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
