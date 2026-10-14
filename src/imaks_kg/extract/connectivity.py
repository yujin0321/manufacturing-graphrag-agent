"""LLM API 연결 확인 도구(표준 라이브러리만 사용). 키 값은 어디에도 출력·기록하지 않는다.

실행: PYTHONPATH=src python -m imaks_kg.extract.connectivity <status|list-models|ping> ...
모델 이름은 코드에 기본값이 없다(항상 --model 인자). 요청 본문에는 고정 한 문장만 넣는다.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from imaks_kg.common.io_utils import write_json
from imaks_kg.settings import REPO_ROOT

KEY_NAMES = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "hf": "HF_TOKEN"}
ALL_KEY_NAMES = list(KEY_NAMES.values())
LOG_DIR = REPO_ROOT / "llm_logs"
MAX_LINES = 80
TIMEOUT_SEC = 60
MAX_OUT_TOKENS = 128

PROMPT_TEXT = "Reply with the single word OK."
# OpenAI 계열 json_object 모드는 메시지에 'JSON'이라는 단어가 있어야 하므로 JSON 모드에서만 이 문장을 쓴다.
PROMPT_JSON = 'Reply with a JSON object: {"reply": "OK"}.'

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
OPENAI_BASE = "https://api.openai.com/v1"
HF_BASE = "https://router.huggingface.co/v1"

_GENERIC_SECRET = re.compile(r"AIza[0-9A-Za-z_\-]{20,}|(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{10,}|hf_[A-Za-z0-9]{10,}")
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{8,}", re.I)
_KEYPARAM = re.compile(r"([?&](?:key|api_key)=)[^&\s\"']+", re.I)


# ---------------------------------------------------------------- .env / 마스킹
def load_env(path=None) -> int:
    """저장소 루트 .env의 KEY=VALUE를 os.environ에 넣는다. 이미 있는 환경변수는 덮어쓰지 않는다."""
    p = Path(path) if path else REPO_ROOT / ".env"
    if not p.is_file():
        return 0
    added = 0
    for raw in p.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if name in ALL_KEY_NAMES and name not in os.environ and value:
            os.environ[name] = value
            added += 1
    return added


def known_secrets() -> list:
    return [os.environ[n] for n in ALL_KEY_NAMES if os.environ.get(n)]


def mask(text, extra_secrets=()) -> str:
    """현재 환경의 키 값, 추가로 준 값, 키 형식 패턴을 모두 가린다."""
    s = str(text)
    for sec in sorted(set(known_secrets()) | set(extra_secrets), key=len, reverse=True):
        if sec:
            s = s.replace(sec, "***")
    s = _BEARER.sub(r"\1***", s)
    s = _KEYPARAM.sub(r"\1***", s)
    s = _GENERIC_SECRET.sub("***", s)
    return s


# ---------------------------------------------------------------- HTTP
def http_call(method, url, headers, body=None):
    """(HTTP 상태, 본문 문자열). 네트워크 오류는 상태 0과 마스킹된 메시지."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = dict(headers)
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            return getattr(resp, "status", 200), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            txt = e.read().decode("utf-8", "replace")
        except Exception:
            txt = ""
        return e.code, txt
    except Exception as e:  # URLError, timeout 등
        return 0, mask(f"{type(e).__name__}: {e}")


def _key_for(provider):
    name = KEY_NAMES[provider]
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"{name}이(가) 설정되지 않았습니다. .env에 넣거나 환경변수로 설정하세요.")
    return val


def _auth_headers(provider):
    key = _key_for(provider)
    if provider == "gemini":
        return {"x-goog-api-key": key}
    return {"Authorization": "Bearer " + key}


def _error_summary(text, limit=300) -> str:
    msg = text
    try:
        j = json.loads(text)
        err = j.get("error", j) if isinstance(j, dict) else j
        if isinstance(err, dict):
            msg = err.get("message") or json.dumps(err, ensure_ascii=False)
        else:
            msg = str(err)
    except Exception:
        pass
    return mask(" ".join(str(msg).split()))[:limit]


def _hints(status, msg, json_mode) -> list:
    low = msg.lower()
    h = []
    if status in (401, 403):
        h.append("키가 틀렸거나 권한/결제가 없음")
    if status == 404:
        h.append("모델 이름이 틀렸거나 이 키로 호출 불가(list-models로 확인)")
    if status == 429:
        h.append("할당량/속도 제한 또는 크레딧 부족")
    if status == 0:
        h.append("네트워크 오류 또는 타임아웃")
    if "temperature" in low:
        h.append("temperature 매개변수가 거부됨(이 모델은 temperature 지정 불가일 수 있음)")
    if json_mode and any(w in low for w in ("json", "response_format", "responsemimetype", "mime")):
        h.append("JSON 출력 강제가 거부됨(이 모델/엔드포인트는 JSON 모드 미지원일 수 있음)")
    if "max_tokens" in low or "max_completion_tokens" in low or "maxoutputtokens" in low:
        h.append("최대 토큰 매개변수 이름이 거부됨")
    return h


# ---------------------------------------------------------------- 명령 구현
def cmd_status(out=print):
    for n in ALL_KEY_NAMES:
        out(f"{n}: {'설정됨' if os.environ.get(n) else '없음'}")
    return 0


def fetch_model_names(provider) -> list:
    """[(이름, 비고)]. 페이지 토큰이 있으면 모두 순회한다."""
    headers = _auth_headers(provider)
    rows = []
    if provider == "gemini":
        token = None
        for _ in range(100):
            url = GEMINI_BASE + "/models?pageSize=1000"
            if token:
                url += "&pageToken=" + urllib.parse.quote(token)
            status, text = http_call("GET", url, headers)
            if status != 200:
                raise RuntimeError(f"HTTP {status}: {_error_summary(text)}")
            j = json.loads(text)
            for m in j.get("models", []):
                name = m.get("name", "")
                name = name[7:] if name.startswith("models/") else name
                gen = "generateContent" in (m.get("supportedGenerationMethods") or [])
                rows.append((name, "generateContent 지원" if gen else "generateContent 미지원"))
            token = j.get("nextPageToken")
            if not token:
                break
    else:
        url = (OPENAI_BASE if provider == "openai" else HF_BASE) + "/models"
        status, text = http_call("GET", url, headers)
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {_error_summary(text)}")
        j = json.loads(text)
        items = j.get("data", j) if isinstance(j, dict) else j
        for m in items:
            rows.append((m.get("id", ""), ""))
    return sorted(set(rows))


def limited(lines, out=print, cap=MAX_LINES):
    lines = list(lines)
    for ln in lines[:cap]:
        out(ln)
    if len(lines) > cap:
        out(f"외 {len(lines) - cap}건")


def cmd_list_models(provider, contains, out=print, log_dir=None):
    rec = {"command": "list-models", "provider": provider, "model": None}
    try:
        rows = fetch_model_names(provider)
    except RuntimeError as e:
        rec.update(status="fail", error=mask(e))
        out(f"실패: {mask(e)}")
        _log(rec, log_dir)
        return 1
    needles = [c.lower() for c in (contains or [])]
    shown = [r for r in rows if not needles or any(n in r[0].lower() for n in needles)]
    out(f"전체 {len(rows)}개, 표시 대상 {len(shown)}개" + (f" (contains={contains})" if needles else ""))
    limited([f"{n}  [{note}]" if note else n for n, note in shown], out)
    rec.update(status="ok", total=len(rows), shown=len(shown))
    _log(rec, log_dir)
    return 0


def _build_ping(provider, model, json_mode, temperature, token_param):
    prompt = PROMPT_JSON if json_mode else PROMPT_TEXT
    if provider == "gemini":
        gc = {"maxOutputTokens": MAX_OUT_TOKENS}
        if temperature is not None:
            gc["temperature"] = temperature
        if json_mode:
            gc["responseMimeType"] = "application/json"
        url = f"{GEMINI_BASE}/models/{urllib.parse.quote(model, safe='')}:generateContent"
        return url, {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gc}
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            token_param: MAX_OUT_TOKENS}
    if temperature is not None:
        body["temperature"] = temperature
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    base = OPENAI_BASE if provider == "openai" else HF_BASE
    return base + "/chat/completions", body


def _parse_ping(provider, text):
    j = json.loads(text)
    if provider == "gemini":
        cands = j.get("candidates") or []
        parts = (cands[0].get("content", {}).get("parts") or []) if cands else []
        reply = "".join(p.get("text", "") for p in parts)
        u = j.get("usageMetadata") or {}
        return reply, u.get("promptTokenCount"), u.get("candidatesTokenCount")
    ch = j.get("choices") or []
    reply = (ch[0].get("message", {}).get("content") or "") if ch else ""
    u = j.get("usage") or {}
    return reply, u.get("prompt_tokens"), u.get("completion_tokens")


def cmd_ping(provider, model, json_mode=False, temperature=None, out=print, log_dir=None):
    headers = _auth_headers(provider)
    rec = {"command": "ping", "provider": provider, "model": model,
           "json_mode": json_mode, "temperature": temperature, "retried_with_max_tokens": False}
    t0 = time.perf_counter()
    url, body = _build_ping(provider, model, json_mode, temperature, "max_completion_tokens")
    status, text = http_call("POST", url, headers, body)
    if provider != "gemini" and status == 400 and "max_completion_tokens" in text:
        rec["retried_with_max_tokens"] = True
        url, body = _build_ping(provider, model, json_mode, temperature, "max_tokens")
        status, text = http_call("POST", url, headers, body)
    ms = int((time.perf_counter() - t0) * 1000)
    rec["latency_ms"] = ms
    rec["http_status"] = status
    if status == 200:
        try:
            reply, tin, tout = _parse_ping(provider, text)
        except Exception as e:
            rec.update(status="fail", error=mask(f"응답 해석 실패: {type(e).__name__}"))
            out("실패: 응답 형식을 해석하지 못했습니다.")
            _log(rec, log_dir)
            return 1
        rec.update(status="ok", input_tokens=tin, output_tokens=tout)
        out("상태: 성공")
        out(f"지연: {ms} ms")
        out(f"토큰: 입력 {tin if tin is not None else '알 수 없음'}, 출력 {tout if tout is not None else '알 수 없음'}")
        out("응답 첫 80자: " + mask(reply)[:80].replace("\n", " "))
        if json_mode:
            try:
                json.loads(reply)
                out("JSON 파싱: 가능")
                rec["json_parse_ok"] = True
            except Exception:
                out("JSON 파싱: 불가(응답이 잘렸거나 JSON이 아님)")
                rec["json_parse_ok"] = False
        _log(rec, log_dir)
        return 0
    msg = _error_summary(text)
    hints = _hints(status, msg, json_mode)
    rec.update(status="fail", error=msg, hints=hints)
    out(f"상태: 실패 (HTTP {status})")
    out(f"오류: {msg}")
    for h in hints:
        out("힌트: " + h)
    _log(rec, log_dir)
    return 1


def _log(rec, log_dir=None):
    d = Path(log_dir) if log_dir else LOG_DIR
    rec = dict(rec)
    rec["time"] = datetime.now().isoformat(timespec="seconds")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    p = d / f"connectivity_{stamp}.json"
    i = 1
    while p.exists():
        p = d / f"connectivity_{stamp}_{i}.json"
        i += 1
    clean = json.loads(mask(json.dumps(rec, ensure_ascii=False)))
    return write_json(p, clean)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="LLM API 연결 확인")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    pl = sub.add_parser("list-models")
    pl.add_argument("--provider", required=True, choices=list(KEY_NAMES))
    pl.add_argument("--contains", nargs="*", default=[])
    pp = sub.add_parser("ping")
    pp.add_argument("--provider", required=True, choices=list(KEY_NAMES))
    pp.add_argument("--model", required=True)
    pp.add_argument("--json-mode", action="store_true")
    pp.add_argument("--temperature", type=float, default=None,
                    help="지정하지 않으면 온도를 보내지 않는다(기본). 공식 문서상 두 후보 모델은 온도 지정을 무시하거나 거부한다")
    pp.add_argument("--no-temperature", action="store_true", help="온도 매개변수를 보내지 않는다(온도 지정을 거부하는 모델용)")
    a = ap.parse_args(argv)
    load_env()
    if a.cmd == "status":
        return cmd_status()
    if a.cmd == "list-models":
        return cmd_list_models(a.provider, a.contains)
    return cmd_ping(a.provider, a.model, a.json_mode, None if a.no_temperature else a.temperature)


if __name__ == "__main__":
    sys.exit(main())
