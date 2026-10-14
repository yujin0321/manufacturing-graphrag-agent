"""C 동시성 테스트용 자식 프로세스(실제 API 호출 없음). 임시 장부·잠금 폴더는 환경변수로 받는다:
IMAKS_EXTRACTION_LEDGER, IMAKS_EXTRACTION_LOCKS.

  python tests/extract_proc_helper.py reserve <approval.json> <run_id> <start_file>
  python tests/extract_proc_helper.py append <estimate_id> <n> <start_file>
  python tests/extract_proc_helper.py hold <approval.json> <run_id> <journal> <ready_file>
  python tests/extract_proc_helper.py run <approval.json> <run_id> <out_root> <fake_dir> <chunk_id> <start_file>
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from imaks_kg.extract import approval, ledger, llm, locks, run  # noqa: E402
from imaks_kg.extract.common import ExtractError  # noqa: E402


def wait_start(path, timeout=20.0):
    end = time.monotonic() + timeout
    while not Path(path).exists():
        if time.monotonic() > end:
            raise SystemExit(3)
        time.sleep(0.005)


def main(argv):
    cmd = argv[0]
    if cmd == "reserve":
        p, run_id, start = argv[1:4]
        wait_start(start)
        try:
            approval.reserve(p, run_id)
            print("OK")
            return 0
        except ExtractError as e:
            print("FAIL", str(e)[:80])
            return 1
    if cmd == "append":
        eid, n, start = argv[1], int(argv[2]), argv[3]
        wait_start(start)
        for i in range(n):
            ledger.append("test_event", {f"{eid}.json": "0" * 64}, estimate_id=eid, state="unused")
        print("OK")
        return 0
    if cmd == "hold":  # 실행 잠금을 쥐고 예약한 뒤 보내는 중(sending)에서 멈춘다 → 부모가 강제 종료
        p, run_id, journal, ready = argv[1:5]
        rl = locks.run_lock(Path(p).stem).acquire()
        approval.reserve(p, run_id, journal=journal)
        with open(journal, "a", encoding="utf-8") as f:
            f.write(json.dumps({"chunk_id": "c1", "attempt": 1, "phase": "prepared"}) + "\n")
            f.write(json.dumps({"chunk_id": "c1", "attempt": 1, "phase": "sending"}) + "\n")
        Path(ready).write_text("ready", encoding="utf-8")
        time.sleep(60)
        rl.release()
        return 0
    if cmd == "run":  # 예약을 첫 호출 직전에 하는 실제 run_calls(가짜 클라이언트). 가짜 호출 수를 출력
        p, run_id, out_root, fake_dir, chunk_id, start = argv[1:7]
        ctx = run.prepare(chunk_ids=[chunk_id], provider="anthropic")
        client = llm.FakeClient(fake_dir)
        wait_start(start)
        try:
            run.run_calls(ctx, client, Path(out_root) / run_id, run_id, "execute", max_chunks=1,
                          on_first_call=lambda: approval.reserve(p, run_id), sleep=lambda s: None)
            code = 0
        except ExtractError:
            code = 1
        print(f"CALLS {len(client.calls)}")
        return code
    raise SystemExit(f"알 수 없는 명령 {cmd}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
