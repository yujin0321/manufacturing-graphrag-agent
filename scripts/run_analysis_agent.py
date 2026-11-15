"""센서 분석 결과 설명 Agent CLI. 키는 .env 또는 환경변수에서 읽고 출력하지 않는다.

  # 1) 분석 세션 만들기 (API 0회)
  python scripts/run_analysis_agent.py analyze --csv path/to/sensor.csv
  python scripts/run_analysis_agent.py analyze --reference        # 저장소 기준 입력 사용
  # 2) 질문 (기본은 OpenAI 유료 API, --offline이면 API 0회 템플릿 답변)
  python scripts/run_analysis_agent.py ask --session <session_id> --question "가장 심각한 사건 설명해줘"
  python scripts/run_analysis_agent.py ask --session <session_id> --question "요약해줘" --provider gemini
  python scripts/run_analysis_agent.py ask --session <session_id> --question "조치는?" --incident <incident_id>
  # 3) 세션 목록
  python scripts/run_analysis_agent.py sessions
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from imaks_kg.analysis_agent import ingest, service  # noqa: E402


def load_local_key(name="OPENAI_API_KEY"):
    path = ROOT / ".env"
    if path.is_file():  # .env에서 키와 GEMINI_MODEL 같은 선택 설정을 읽는다(이미 있는 환경변수는 유지)
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, val = line.split("=", 1)
                if k.strip() in (name, "GEMINI_MODEL") and not os.environ.get(k.strip()):
                    os.environ[k.strip()] = val.strip().strip("\"'")
    if not os.environ.get(name):
        raise SystemExit(f"{name}를 .env 또는 환경변수에 설정해 주세요. 채팅에 붙여넣지 마세요.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze")
    src = a.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", type=Path)
    src.add_argument("--reference", action="store_true")
    a.add_argument("--config", default="v3_1")
    q = sub.add_parser("ask")
    q.add_argument("--session", required=True)
    q.add_argument("--question", required=True)
    q.add_argument("--incident", help="UI에서 선택한 사건 ID")
    q.add_argument("--offline", action="store_true", help="모델 호출 없이 근거 템플릿 답변")
    q.add_argument("--no-verify", action="store_true", help="검증 모델 호출 생략")
    q.add_argument("--provider", choices=["openai", "gemini"], default="openai",
                   help="openai: .env의 OPENAI_API_KEY(유료) / gemini: .env의 GEMINI_API_KEY(결제 미연결 프로젝트면 무료 등급)")
    q.add_argument("--model", help="모델 ID. 기본: openai는 저장소 설정, gemini는 GEMINI_MODEL 또는 gemini-3.8-flash")
    sub.add_parser("sessions")
    args = p.parse_args()
    svc = service.AnalysisService()

    if args.cmd == "analyze":
        try:
            o = svc.create_reference_session() if args.reference else \
                svc.create_session(args.csv.read_bytes(), args.csv.name, args.config)
        except ingest.IngestError as exc:
            raise SystemExit(f"입력 오류: {exc} {json.dumps(exc.details, ensure_ascii=False)}")
        print(json.dumps({"session_id": o["session_id"], "period": o["ingest"]["period"],
                          "dropped_columns": o["ingest"]["dropped_columns"],
                          "incidents": o["summary"]["incidents"], "by_type": o["summary"]["incidents_by_type"],
                          "by_severity": o["summary"]["incidents_by_severity"],
                          "suggested_questions": o["suggested_questions"]}, ensure_ascii=False, indent=2))
    elif args.cmd == "ask":
        if not args.offline:
            load_local_key("GEMINI_API_KEY" if args.provider == "gemini" else "OPENAI_API_KEY")
        r = svc.ask(args.session, args.question, focus_incident_id=args.incident, offline=args.offline,
                    verify=not args.no_verify, provider=args.provider, model=args.model)
        print(r["answer"] or r["error"])
        print("\n" + json.dumps({k: r[k] for k in ("status", "intent", "routing", "focus_incident_id", "provider",
                                                   "model", "run_id")}
                                | {"verification": r["verification"], "model_calls": r["usage"]["model_calls"],
                                   "total_tokens": r["usage"]["total_tokens"]}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(svc.list_sessions(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
