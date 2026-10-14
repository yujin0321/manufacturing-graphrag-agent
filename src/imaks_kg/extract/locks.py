"""프로세스 사이 파일 잠금(Windows: msvcrt.locking, POSIX: fcntl.flock). 2026-10-14 보완.

- 잠금 파일은 git이 무시하는 extraction/.locks/(settings.EXTRACTION_LOCKS)에 둔다. 테스트·CLI는 LOCK_DIR_OVERRIDE 또는
  환경변수 IMAKS_EXTRACTION_LOCKS로 바꿀 수 있다.
- 잠금은 파일 핸들에 묶여 있어 프로세스가 죽으면 OS가 핸들을 닫으면서 풀린다.
- 시간 제한이 있다(넘으면 ExtractError). 해제는 컨텍스트 관리자(try/finally)가 한다.
- 잠금 순서는 항상 승인 잠금 → 장부 잠금이다. 장부 잠금을 잡은 채 승인 잠금을 잡지 않는다(교착 방지).
  ledger.append는 장부 잠금만 잡는다. 실행 잠금(run lock)은 실행 내내 쥐는 별도 잠금이고, 다른 쪽은 기다리지 않고
  (timeout 0) 시도만 하므로 교착이 생기지 않는다.
"""
import hashlib
import os
import sys
import time
from pathlib import Path

from imaks_kg.extract.common import ExtractError
from imaks_kg.settings import EXTRACTION_LOCKS

LOCK_DIR_OVERRIDE = None
ENV_LOCKS = "IMAKS_EXTRACTION_LOCKS"
DEFAULT_TIMEOUT_S = 10.0
POLL_S = 0.02

if sys.platform == "win32":
    import msvcrt

    def _try_lock(fh):
        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(fh):
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
else:  # pragma: no cover (POSIX)
    import fcntl

    def _try_lock(fh):
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def lock_dir() -> Path:
    if LOCK_DIR_OVERRIDE:
        return Path(LOCK_DIR_OVERRIDE)
    return Path(os.environ.get(ENV_LOCKS) or EXTRACTION_LOCKS)


class FileLock:
    """배타 잠금. with FileLock(name, timeout): ... 넘으면 ExtractError."""

    def __init__(self, name, timeout=DEFAULT_TIMEOUT_S, what=""):
        self.path = lock_dir() / name
        self.timeout = float(timeout)
        self.what = what or name
        self.fh = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        if os.path.getsize(self.path) == 0:
            fh.write(b"\0")
            fh.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            if _try_lock(fh):
                self.fh = fh
                return self
            if time.monotonic() >= deadline:
                fh.close()
                raise ExtractError(f"잠금을 얻지 못함({self.what}, {self.timeout:g}초): 다른 프로세스가 쓰는 중")
            time.sleep(POLL_S)

    def release(self):
        if self.fh is not None:
            try:
                _unlock(self.fh)
            finally:
                self.fh.close()
                self.fh = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False


def approval_lock(estimate_id, timeout=DEFAULT_TIMEOUT_S):
    return FileLock(f"approval_{estimate_id}.lock", timeout, f"승인 {estimate_id}")


def run_lock(estimate_id, timeout=0.0):
    """승인을 쓰는 실행 동안 쥐는 잠금. 다른 쪽은 기다리지 않고 시도만 한다(쥔 프로세스가 살아 있는지 확인용)."""
    return FileLock(f"approval_{estimate_id}.run.lock", timeout, f"승인 {estimate_id} 실행")


def ledger_lock(ledger_path, timeout=DEFAULT_TIMEOUT_S):
    key = hashlib.sha256(str(Path(ledger_path).resolve()).encode("utf-8")).hexdigest()[:16]
    return FileLock(f"ledger_{key}.lock", timeout, "해시 장부")


def atomic_write_bytes(path, data: bytes):
    """임시 파일에 쓰고 fsync한 뒤 os.replace로 바꾼다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
