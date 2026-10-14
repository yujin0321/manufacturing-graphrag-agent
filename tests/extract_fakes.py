"""C 테스트용 가짜 LLM 응답 만들기(실제 호출 없음).

SOP 원문 청크(preprocessed/documents/chunks.jsonl)를 보고 손으로 정한 규칙 사양으로 BetaMessage 형식 응답을 만든다.
정답 규칙 파일은 보지 않았다. 일부러 넣은 오류(목록 밖 센서, 바꿔 쓴 인용, 스키마 위반, 거절·max_tokens·폴백·SDK 예외)는
FAULTS에 모았다. 사양에 없는 청크는 {"rules": []}(제목·머리말 청크처럼 규칙이 없는 응답)이다.

  PYTHONPATH=src python tests/extract_fakes.py <출력 폴더>
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from imaks_kg.extract.common import read_jsonl, safe_name  # noqa: E402
from imaks_kg.settings import DOC_CHUNKS  # noqa: E402

FAKE_MODEL = "claude-opus-5-5"
FAKE_FALLBACK_MODEL = "fake-fallback-model"


def R(cls, cond, resp, quote, sensors=(), stations=(), rid=None, sev=None, steps=()):
    return {"class": cls, "conditionText": cond, "responseText": resp, "ruleSeverity": sev,
            "sensors": list(sensors), "targetStations": list(stations), "sourceQuote": quote,
            "ruleIdInText": rid, "actionSteps": list(steps)}


def _full(cid, chunks):
    return chunks[cid]["text"]


def specs(chunks):
    """청크 ID → 규칙 목록. 인용은 청크 원문에서 그대로 잘라 쓴다."""
    t = lambda cid: _full(cid, chunks)  # noqa: E731
    s = {}
    s["SOP-001:p1:RULE-ST01-01"] = [R("OperationalRule", "FLW", "MUST be maintained between 112 and 128 L/min.",
                                      t("SOP-001:p1:RULE-ST01-01"), ["ST01_FILLING_FLW"], [], "RULE-ST01-01")]
    s["SOP-001:p1:RULE-ST01-02"] = [R("OperationalRule", "TMP exceeds 26°C", "reduce speed by 10% and notify QC",
                                      t("SOP-001:p1:RULE-ST01-02"), ["ST01_FILLING_TMP"], ["ST01_FILLING"],
                                      "RULE-ST01-02", None, ["reduce speed by 10%", "notify QC"])]
    s["SOP-001:p1:RULE-ST01-03"] = [R("OperationalRule", "PRS drop below 3.3 bar", "inspect inlet valve within 5 min.",
                                      t("SOP-001:p1:RULE-ST01-03"), ["ST01_FILLING_PRS"], ["ST01_FILLING"],
                                      "RULE-ST01-03")]
    s["SOP-001:p1:RULE-ST02-01"] = [R("OperationalRule", "TMP", "MUST remain between 175°C and 195°C.",
                                      t("SOP-001:p1:RULE-ST02-01"), ["ST02_SEALING_TMP"], [], "RULE-ST02-01")]
    s["SOP-001:p1:RULE-ST02-02"] = [R("OperationalRule", "TMP > 210°C", "emergency stop ST02, ST03, ST04.",
                                      t("SOP-001:p1:RULE-ST02-02"), ["ST02_SEALING_TMP"],
                                      ["ST02_SEALING", "ST03_LABELLING", "ST04_PACKAGING"], "RULE-ST02-02", "CRITICAL",
                                      ["emergency stop ST02", "emergency stop ST03", "emergency stop ST04"])]
    s["SOP-001:p1:RULE-ST02-04"] = [R("OperationalRule", "ST02_SEALING-CUR triggers a WARNING",
                                      "Monitor ST04_PACKAGING-SPD", t("SOP-001:p1:RULE-ST02-04"),
                                      ["ST02_SEALING_CUR", "ST04_PACKAGING_SPD"], ["ST04_PACKAGING"], "RULE-ST02-04",
                                      "WARNING")]
    s["SOP-001:p1:RULE-ST03-02"] = [
        R("OperationalRule", "CNT below 110 pcs/min", "check for label jam.",
          "RULE-ST03-02: CNT below 110 pcs/min — check for label jam.", ["ST03_LABELLING_CNT"], ["ST03_LABELLING"],
          "RULE-ST03-02"),
        R("OperationalRule", "Below 100", "halt.", "Below 100 (CRITICAL): halt.", ["ST03_LABELLING_CNT"],
          ["ST03_LABELLING"], "RULE-ST03-02", "CRITICAL"),
    ]
    s["SOP-001:p2:RULE-ST04-03"] = [R("OperationalRule", "SPD drops below 1.00 m/s without operator command",
                                      "verify RULE-ST02-04.", t("SOP-001:p2:RULE-ST04-03"), ["ST04_PACKAGING_SPD"],
                                      ["ST04_PACKAGING"], "RULE-ST04-03")]
    s["SOP-001:p2:RULE-WRH01-01"] = [
        R("OperationalRule", "TMP", "MUST remain between 0.5°C and 8°C.",
          "RULE-WRH01-01: TMP MUST remain between 0.5°C and 8°C.", ["WRH01_WAREHOUSE_TMP"], [], "RULE-WRH01-01"),
        R("OperationalRule", "above 12°C", "notify QC and quarantine batch.",
          "CRITICAL above 12°C — notify QC and quarantine batch.", ["WRH01_WAREHOUSE_TMP"], ["WRH01_WAREHOUSE"],
          "RULE-WRH01-01", "CRITICAL", ["notify QC", "quarantine batch"]),
    ]
    s["SOP-001:p1:table1:chunk"] = [R("OperationalRule", "thermal fault", "ST04 speed reduction",
                                      "Downstream Effect: Feeds ST03; thermal fault → ST04 speed reduction",
                                      [], ["ST04_PACKAGING"])]
    # SOP-003 표 1: MAINT-01~08. 대부분 B와 같은 값, 일부는 일부러 다르게(충돌 기록 확인용).
    s["SOP-003:p1:table1:chunk"] = [
        R("MaintenanceRule", "VIB DRIFT >0.05 mm/s over 60 min", "Inspect and lubricate bearing",
          "Rule ID: MAINT-01; Sensor: VIB; Station: ST04_PACKAGING; Trigger: VIB DRIFT >0.05 mm/s over 60 min; "
          "Action: Inspect and lubricate bearing; Priority: HIGH", ["ST04_PACKAGING_VIB"], ["ST04_PACKAGING"],
          "MAINT-01", "HIGH"),
        R("MaintenanceRule", "CUR DRIFT >1.0 A for 30+ min at ST02_SEALING", "Inspect sealing jaw",
          "Rule ID: MAINT-02; Sensor: CUR; Station: ST02_SEALING; Trigger: CUR DRIFT >1.0 A for 30+ min; "
          "Action: Inspect sealing jaw; Priority: HIGH", ["ST02_SEALING_CUR"], ["ST02_SEALING"], "MAINT-02", "HIGH"),
        R("OperationalRule", "TEN STUCK >10 samples", "Replace sensor",
          "Rule ID: MAINT-03; Sensor: TEN; Station: ST03_LABELLING; Trigger: TEN STUCK >10 samples; "
          "Action: Replace sensor; Priority: MEDIUM", ["ST03_LABELLING_TEN"], ["ST03_LABELLING"], "MAINT-03", "MEDIUM"),
        R("MaintenanceRule", "PRS <3.3 bar for >15 min", "Inspect filter and pump",
          "Trigger: PRS <3.3 bar for >15 min; Action: Inspect filter and pump", ["ST01_FILLING_PRS"], ["ST01_FILLING"],
          None),
        R("MaintenanceRule", "TMP >25°C for >5 min", "Activate secondary cooling",
          "Rule ID: MAINT-05; Sensor: TMP; Station: SRV01_SERVERROOM; Trigger: TMP >25°C for >5 min; "
          "Action: Activate secondary cooling; Priority: CRITICAL", ["SRV01_SERVERROOM_TMP"], ["SRV01_SERVERROOM"],
          "MAINT-05", "CRITICAL"),
        R("MaintenanceRule", "TMP DRIFT >2°C over 2 h", "Inspect compressor; notify QC",
          "Rule ID: MAINT-06; Sensor: TMP; Station: WRH01_WAREHOUSE; Trigger: TMP DRIFT >2°C over 2 h; "
          "Action: Inspect compressor; notify QC; Priority: CRITICAL", ["WRH01_WAREHOUSE_TMP"], ["WRH01_WAREHOUSE"],
          "MAINT-06", "CRITICAL", ["Inspect compressor", "notify QC"]),
        R("MaintenanceRule", "TMP >20°C for >10 min", "Emergency ventilation; notify safety officer",
          "Rule ID: MAINT-07; Sensor: TMP; Station: CHM01_CHEMICALSTORAGE; Trigger: TMP >20°C for >10 min; "
          "Action: Emergency ventilation; notify safety officer; Priority: CRITICAL",
          ["CHM01_CHEMICALSTORAGE_TMP"], ["CHM01_CHEMICALSTORAGE"], "MAINT-07", "CRITICAL",
          ["Emergency ventilation", "notify safety officer"]),
        R("MaintenanceRule", "HUM DRIFT >10%RH over 60 min", "Activate dehumidifier; check HVAC drain",
          "Rule ID: MAINT-08; Sensor: HUM; Station: RND01_RDLAB; Trigger: HUM DRIFT >10%RH over 60 min; "
          "Action: Activate dehumidifier; check HVAC drain; Priority: HIGH", ["RND01_RDLAB_HUM"], ["RND01_RDLAB"],
          "MAINT-08", "HIGH", ["Activate dehumidifier", "check HVAC drain"]),
    ]
    s["SOP-003:p1:table2:chunk"] = [
        R("MaintenanceRule", "ST02_SEALING-CUR↑ → ST04_PACKAGING-SPD↓; Primary Fault: Sealing motor overload",
          "1.Verify ST02-CUR trend. 2.Inspect sealing jaw. 3.Reset ST04 speed setpoint.",
          "Pattern: ST02_SEALING-CUR↑ → ST04_PACKAGING-SPD↓; Primary Fault: Sealing motor overload; Secondary Effect: "
          "Conveyor speed drop via electrical coupling; Resolution: 1.Verify ST02-CUR trend. 2.Inspect sealing jaw. "
          "3.Reset ST04 speed setpoint.", ["ST02_SEALING_CUR", "ST04_PACKAGING_SPD"], ["ST02_SEALING", "ST04_PACKAGING"],
          None, None, ["Verify ST02-CUR trend.", "Inspect sealing jaw.", "Reset ST04 speed setpoint."]),
        R("MaintenanceRule", "SRV01-TMP↑ → SCADA latency↑; Primary Fault: Server Room overheating",
          "1.Reduce SRV01-TMP <25°C. 2.Verify PLC heartbeats. 3.Clear STUCK alarms.",
          "Pattern: SRV01-TMP↑ → SCADA latency↑; Primary Fault: Server Room overheating; Secondary Effect: Increased "
          "scan time → apparent STUCK readings; Resolution: 1.Reduce SRV01-TMP <25°C. 2.Verify PLC heartbeats. "
          "3.Clear STUCK alarms.", ["SRV01_SERVERROOM_TMP"], ["SRV01_SERVERROOM"], None, None,
          ["Reduce SRV01-TMP <25°C.", "Verify PLC heartbeats.", "Clear STUCK alarms."]),
        R("MaintenanceRule", "WRH01-TMP↑ → QC HOLD; Primary Fault: Cold warehouse drift",
          "1.Restore WRH01-TMP <8°C. 2.Notify QC. 3.Place batch on HOLD in ERP.",
          "Pattern: WRH01-TMP↑ → QC HOLD; Primary Fault: Cold warehouse drift; Secondary Effect: Product quality risk; "
          "Resolution: 1.Restore WRH01-TMP <8°C. 2.Notify QC. 3.Place batch on HOLD in ERP.",
          ["WRH01_WAREHOUSE_TMP"], ["WRH01_WAREHOUSE"], None, None,
          ["Restore WRH01-TMP <8°C.", "Notify QC.", "Place batch on HOLD in ERP."]),
    ]
    s["SOP-004:p1:RULE-ACCESS-01"] = [R("AccessRule", "Any entry by an unauthorised role",
                                        "MUST be logged as OccupancyEvent::UnauthorisedAccess with person_id, zone, and timestamp.",
                                        t("SOP-004:p1:RULE-ACCESS-01"), [], [], "RULE-ACCESS-01")]
    s["SOP-004:p1:RULE-ACCESS-02"] = [R("AccessRule", "detection",
                                        "Security personnel MUST be notified within 2 minutes of detection.",
                                        t("SOP-004:p1:RULE-ACCESS-02"), [], [], "RULE-ACCESS-02")]
    s["SOP-004:p2:RULE-ACCESS-04"] = [R("AccessRule", "Any UNAUTHORIZED_ACCESS in Chemical Storage",
                                        "immediate escalation to the Safety Officer regardless of role.",
                                        t("SOP-004:p2:RULE-ACCESS-04"), [], [], "RULE-ACCESS-04")]
    s["SOP-004:p1:table2:chunk"] = [R("AccessRule", "Server Room above 2 persons", "access badge required",
                                      "Zone: Server Room; Max Persons: 2; Enforcement: CRITICAL above 2; access badge required",
                                      [], [], None, "CRITICAL")]
    s["SOP-004:p1:table3:chunk"] = [R("AccessRule", "operator, CRITICAL alarm", "acknowledge within 3 min",
                                      "Role: operator; Max Ack — WARNING (min): 15; Max Ack — CRITICAL (min): 3",
                                      [], [], None)]
    s["SOP-002:p1:text1"] = [R("ThresholdRule", "Threshold hierarchy", "CRIT_LO < WARN_LO < NOMINAL < WARN_HI < CRIT_HI.",
                               "Threshold hierarchy: CRIT_LO < WARN_LO < NOMINAL < WARN_HI < CRIT_HI.")]
    return s


# 일부러 넣은 오류와 특수 응답(모두 HTTP 200 응답. SDK 예외는 실행 전체를 중단하므로 test_extract_errors.py에서 따로 다룬다)
FAULTS = {
    # 목록 밖 센서 1건 + 인용을 바꿔 쓴 1건 + 정상 1건
    "SOP-001:p2:RULE-CAF01-01": {"rules": [
        R("OperationalRule", "CO2 above 1000 ppm", "check ventilation system.", "RULE-CAF01-01: TMP above 26°C",
          ["CAF01_CAFETERIA_CO2"], [], "RULE-CAF01-01"),
        R("OperationalRule", "TMP above 26°C", "check ventilation system.",
          "RULE-CAF01-01: TMP above 26 °C - check the ventilation system.", ["CAF01_CAFETERIA_TMP"], [], "RULE-CAF01-01"),
        R("OperationalRule", "TMP above 26°C", "check ventilation system.",
          "RULE-CAF01-01: TMP above 26°C — check ventilation system.", ["CAF01_CAFETERIA_TMP"], ["CAF01_CAFETERIA"],
          "RULE-CAF01-01"),
    ]},
    # 스키마 위반: actionSteps 없음 + 추가 키
    "SOP-001:p2:RULE-RND01-01": {"rules": [
        {k: v for k, v in R("OperationalRule", "TMP", "MUST remain between 18°C and 26°C for experimental validity.",
                            "RULE-RND01-01: TMP MUST remain between 18°C and 26°C for experimental validity.",
                            ["RND01_RDLAB_TMP"], [], "RULE-RND01-01").items() if k != "actionSteps"} | {"confidence": 0.9},
    ]},
    # 원문에 없는 ID
    "SOP-001:p2:RULE-CHM01-01": {"rules": [
        R("OperationalRule", "TMP", "MUST remain between 10°C and 20°C.",
          "RULE-CHM01-01: TMP MUST remain between 10°C and 20°C.", ["CHM01_CHEMICALSTORAGE_TMP"], [], "RULE-CHM01-09"),
    ]},
    # 목록 밖 공정
    "SOP-001:p2:RULE-CHM01-02": {"rules": [
        R("OperationalRule", "HUM >45%RH", "Activate desiccant system", "Activate desiccant system if HUM >45%RH.",
          ["CHM01_CHEMICALSTORAGE_HUM"], ["CHM02_STORAGE"], "RULE-CHM01-02"),
    ]},
}
SPECIAL = {
    "SOP-001:p2:RULE-SRV01-02": "refusal",
    "SOP-001:p2:RULE-CAF01-02": "max_tokens",
    "SOP-001:p2:RULE-SRV01-01": "fallback",
}


def message(cid, body, model=FAKE_MODEL, stop="end_turn", fallback=False, n=0):
    text = json.dumps(body, ensure_ascii=False)
    content = [{"type": "text", "text": text}]
    iterations = [{"type": "message", "input_tokens": 1800 + n, "output_tokens": 40 + len(text) // 4,
                   "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "model": FAKE_MODEL}]
    if fallback:
        content = [{"type": "text", "text": "{\"rules\": [{\"class\": \"Operat"},
                   {"type": "fallback", "from": {"model": FAKE_MODEL}, "to": {"model": FAKE_FALLBACK_MODEL},
                    "trigger": {"type": "refusal", "category": None}},
                   {"type": "text", "text": text}]
        iterations.append({"type": "fallback_message", "input_tokens": 1800 + n, "output_tokens": 40 + len(text) // 4,
                           "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                           "model": FAKE_FALLBACK_MODEL})
    return {
        "id": f"msg_fake_{n:03d}", "type": "message", "role": "assistant",
        "model": FAKE_FALLBACK_MODEL if fallback else model, "content": content, "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 1800 + n, "output_tokens": 40 + len(text) // 4, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": 0, "iterations": iterations},
        "_fake_request_id": f"req_fake_{n:03d}",
    }


FAKE_GEMINI_MODEL = "fake-gemini-model"
THOUGHT_CHUNK = "SOP-001:p1:RULE-ST02-01"   # Gemini: thought part가 앞에 붙은 응답(건너뛰는지 확인)
BLOCKED_CHUNK = "SOP-001:p2:text5"          # Gemini: prompt_feedback.block_reason 응답


def gemini_message(body, finish="STOP", n=0, model=FAKE_GEMINI_MODEL, thought=False, text=None, blocked=None):
    """GenerateContentResponse 형식(실제 응답 필드 이름)."""
    text = json.dumps(body, ensure_ascii=False) if text is None else text
    parts = [{"text": text}]
    if thought:
        parts = [{"text": "Let me think about the chunk first.", "thought": True}] + parts
    usage = {"prompt_token_count": 1700 + n, "candidates_token_count": 30 + len(text) // 4,
             "thoughts_token_count": 120 if thought else 0}
    usage["total_token_count"] = sum(usage.values())
    msg = {"model_version": model, "response_id": f"gemini_fake_{n:03d}", "usage_metadata": usage}
    if blocked:
        msg["prompt_feedback"] = {"block_reason": blocked}
        msg["candidates"] = []
    else:
        msg["candidates"] = [{"content": {"role": "model", "parts": parts}, "finish_reason": finish, "index": 0}]
    return msg


def build(chunk_ids=None, provider="anthropic"):
    """선택 청크 전부(또는 chunk_ids)에 대한 가짜 응답 {청크 ID: dict}. provider="gemini"이면 Gemini 형식."""
    from imaks_kg.extract.inputs import select_chunks
    allc = read_jsonl(DOC_CHUNKS)
    chunks = {c["chunk_id"]: c for c in allc}
    sel = [c["chunk_id"] for c in select_chunks(allc)[0]] if chunk_ids is None else list(chunk_ids)
    sp = specs(chunks)
    for cid, rules in sp.items():
        for r in rules:
            assert r["sourceQuote"] in chunks[cid]["text"], (cid, r["sourceQuote"])
    out = {}
    if provider == "gemini":
        for n, cid in enumerate(sel):
            special = SPECIAL.get(cid, "")
            body = FAULTS.get(cid) or {"rules": sp.get(cid, [])}
            if special == "refusal":
                out[cid] = gemini_message({"rules": []}, finish="SAFETY", n=n)
            elif special == "max_tokens":
                out[cid] = gemini_message(body, finish="MAX_TOKENS", n=n, text=json.dumps(body)[:20])
            elif special == "fallback":  # Gemini 경로에는 폴백이 없다: 보통 응답
                body = {"rules": [R("OperationalRule", "TMP", "MUST NOT exceed 25°C.", chunks[cid]["text"],
                                    ["SRV01_SERVERROOM_TMP"], [], "RULE-SRV01-01")]}
                out[cid] = gemini_message(body, n=n)
            elif cid == BLOCKED_CHUNK:
                out[cid] = gemini_message({}, n=n, blocked="SAFETY")
            else:
                out[cid] = gemini_message(body, n=n, thought=(cid == THOUGHT_CHUNK))
        return out
    for n, cid in enumerate(sel):
        special = SPECIAL.get(cid, "")
        if special.startswith("raise:"):
            out[cid] = {"__raise__": special.split(":", 1)[1]}
            continue
        body = FAULTS.get(cid) or {"rules": sp.get(cid, [])}
        if special == "refusal":
            out[cid] = message(cid, {"rules": []}, stop="refusal", n=n)
        elif special == "max_tokens":
            m = message(cid, body, stop="max_tokens", n=n)
            m["content"][0]["text"] = m["content"][0]["text"][:20]
            out[cid] = m
        elif special == "fallback":
            body = {"rules": [R("OperationalRule", "TMP", "MUST NOT exceed 25°C.", chunks[cid]["text"],
                                ["SRV01_SERVERROOM_TMP"], [], "RULE-SRV01-01")]}
            out[cid] = message(cid, body, fallback=True, n=n)
        else:
            out[cid] = message(cid, body, n=n)
    return out


def write(out_dir, responses=None, provider="anthropic"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for cid, data in sorted((responses or build(provider=provider)).items()):
        (out_dir / f"{safe_name(cid)}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                                        encoding="utf-8", newline="\n")
    return out_dir


if __name__ == "__main__":
    print(write(sys.argv[1], provider=(sys.argv[2] if len(sys.argv) > 2 else "anthropic")))
