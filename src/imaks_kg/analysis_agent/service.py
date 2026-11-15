"""UI 연결용 서비스 계층. UI(또는 HTTP 서버)는 이 클래스만 호출한다.

    svc = AnalysisService()
    overview = svc.create_session(csv_bytes, "line_data.csv")      # 업로드 → 분석(약 20~30초, API 0회)
    reply = svc.ask(overview["session_id"], "가장 심각한 이상 설명해줘")  # 질문 → 설명(유료 API, offline=True면 0회)
    svc.get_session(session_id), svc.list_sessions(), svc.conversation(session_id)

세션 폴더(kg_build/analysis_sessions/<session_id>/):
    session.json · input/(ingest_report.json, sensor_input.csv) · engine/(봉인) · overlay/(봉인)
    conversation.json · questions/<run_id>/(계획·도구 결과·근거·모델 응답·검증·answer.json)
"""
from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from imaks_kg.detection import rules as v1
from imaks_kg.rag import vector as v

from . import agent, analysis, ingest, providers, tools

SESSION_ROOT = v.REPO_ROOT / "kg_build/analysis_sessions"
SESSION_ID = re.compile(r"sess_[0-9]{8}T[0-9]{6}_[0-9a-f]{8}")
CARD_KEYS = ("id", "sensor_id", "station_id", "start", "end", "onset_estimate", "anomaly_type", "severity",
             "type_reason", "rule_ids", "flags")


class SessionError(ValueError):
    pass


class AnalysisService:
    def __init__(self, root: Path = SESSION_ROOT):
        self.root = Path(root)
        self._workspaces: dict[str, tools.Workspace] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ sessions
    def create_session(self, data: bytes, filename: str = "upload.csv",
                       config: str = analysis.DEFAULT_CONFIG) -> dict:
        """업로드 CSV 분석. 입력 오류는 ingest.IngestError(사용자 메시지)로 올린다."""
        groups, report = ingest.parse(data, filename)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        sid = f"sess_{stamp}_{uuid.uuid4().hex[:8]}"
        path = self.root / sid
        path.mkdir(parents=True, exist_ok=False)
        meta = {"session_id": sid, "created_at": datetime.now(timezone.utc).isoformat(), "config": config,
                "status": "analyzing", "file_name": report["file_name"]}
        v.write(path / "session.json", meta)
        try:
            report["normalized_sha256"] = ingest.write_normalized(groups, path / "input/sensor_input.csv")
            v.write(path / "input/ingest_report.json", report)
            ref = {"file_name": report["file_name"], "file_sha256": report["file_sha256"]}
            analysis.run_engine(groups, path / "engine", ref, config)
            analysis.build_overlay(path / "engine", path / "overlay", ref)
        except Exception as exc:
            v.write(path / "session.json", {**meta, "status": "failed", "error_type": type(exc).__name__})
            raise
        v.write(path / "session.json", {**meta, "status": "ready"})
        return self.get_session(sid)

    def create_reference_session(self) -> dict:
        """저장소의 고정 기준 입력(전처리된 iMAKS 센서 데이터)으로 세션을 만든다. 데모·테스트용."""
        data = (v.REPO_ROOT / v1.INPUT).read_bytes()
        return self.create_session(data, Path(v1.INPUT).name)

    def path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
            raise SessionError("잘못된 세션 ID입니다.")
        path = self.root / session_id
        if not (path / "session.json").is_file():
            raise SessionError("세션을 찾을 수 없습니다.")
        return path

    def workspace(self, session_id: str) -> tools.Workspace:
        path = self.path(session_id)
        if v.read(path / "session.json")["status"] != "ready":
            raise SessionError("분석이 완료되지 않은 세션입니다.")
        if session_id not in self._workspaces:
            self._workspaces[session_id] = tools.Workspace(path, base=analysis.base_graph())
        return self._workspaces[session_id]

    def get_session(self, session_id: str) -> dict:
        """첫 화면용 결과: 입력 요약, 집계, 사건 카드, 상관 후보."""
        ws = self.workspace(session_id)
        meta = v.read(self.path(session_id) / "session.json")
        incidents = sorted(ws.store.incidents, key=tools.rank_key)
        return {**meta, "ingest": ws.ingest, "summary": ws.summary,
                "incidents": [{k: i.get(k) for k in CARD_KEYS} for i in incidents],
                "correlations": ws.store.correlations, "warnings": tools.WARNINGS,
                "suggested_questions": suggested_questions(incidents, ws.store.correlations)}

    def list_sessions(self) -> list[dict]:
        if not self.root.exists():
            return []
        rows = [v.read(p) for p in self.root.glob("sess_*/session.json")]
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)

    def conversation(self, session_id: str) -> list[dict]:
        path = self.path(session_id) / "conversation.json"
        return v.read(path) if path.exists() else []

    # ------------------------------------------------------------ questions
    def ask(self, session_id: str, question: str, *, focus_incident_id: str | None = None,
            offline: bool = False, verify: bool = True, provider: str = "openai", model: str | None = None,
            call=None) -> dict:
        """provider: "openai"(기본, 저장소 설정 모델) 또는 "gemini". call은 테스트용 호출 함수 주입."""
        provider_call, model = providers.get(provider, model)
        call = call or provider_call
        ws = self.workspace(session_id)
        if focus_incident_id is not None and focus_incident_id not in ws.store.by_id:
            raise SessionError("선택한 사건이 이 세션에 없습니다.")
        if not self._lock.acquire(blocking=False):
            raise SessionError("다른 질문을 처리 중입니다. 완료 후 다시 시도해 주세요.")
        try:
            turns = self.conversation(session_id)
            last = next((t["focus_incident_id"] for t in reversed(turns) if t.get("focus_incident_id")), None)
            history = [{"question": t["question"], "answer": t["answer"] or ""} for t in turns
                       if t["status"] not in ("error",)]
            run_id = "q_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6]
            result = agent.answer(ws, question, self.path(session_id) / "questions" / run_id, call=call,
                                  offline=offline, verify=verify, focus_incident_id=focus_incident_id,
                                  last_incident_id=last, history=history, model=model, provider=provider)
            turns.append({"run_id": run_id, "question": question, "answer": result["answer"],
                          "status": result["status"], "focus_incident_id": result["focus_incident_id"]})
            v.write(self.path(session_id) / "conversation.json", turns)
            return result
        finally:
            self._lock.release()


def suggested_questions(incidents: list[dict], correlations: list[dict]) -> list[str]:
    """첫 화면 추천 질문. 실제 결과에 있는 사건만 가리킨다."""
    out = ["이번 데이터에서 어떤 이상이 탐지됐는지 요약해줘", "가장 심각한 사건을 설명하고 문서상 조치를 알려줘"]
    if correlations:
        out.append("공정 간 상관 후보가 있으면 근거와 함께 설명해줘")
    types = {i["anomaly_type"] for i in incidents}
    if "DRIFT" in types:
        out.append("서서히 변한(DRIFT) 이상은 어디서 나왔어?")
    if not incidents:
        out = ["규칙에 걸린 사건이 없는 이유와 검사한 규칙 범위를 알려줘"]
    return out
