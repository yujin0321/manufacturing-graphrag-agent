"""Role/Task/Example 3단 프롬프트 조립(버전 파일: prompts/<version>/system.md, examples.json).

- system.md는 '# Role', '# Task', '# Example' 세 절을 이 순서로 가진다(check_structure가 확인).
- {{SENSOR_IDS}}, {{STATION_IDS}}는 seed.ttl에서 읽은 실제 ID 목록으로, {{EXAMPLES}}는 examples.json으로 채운다.
- 기록: 프롬프트 버전, 템플릿·예시 파일 SHA-256, 조립된 system 텍스트의 SHA-256(prompt_sha256).
- examples.json의 confirmationStatus가 CONFIRMED가 아니면(초안) 실제 실행을 거부한다(run.py).
"""
import json
import re

from imaks_kg.common.provenance import sha256_file, sha256_text
from imaks_kg.extract.common import ExtractError
from imaks_kg.settings import EXTRACT_PROMPTS_DIR

PROMPT_VERSION = "v1"
SECTIONS = ("# Role", "# Task", "# Example")
STATUS_DRAFT = "DRAFT_NEEDS_HUMAN_CONFIRMATION"
STATUS_CONFIRMED = "CONFIRMED"
# 예시 확정 상태 키. "status"는 누수 점검의 컬럼 전용 금지어(JSON 키)라 쓰지 않는다.
EXAMPLES_STATUS_KEY = "confirmationStatus"
PLACEHOLDERS = ("{{SENSOR_IDS}}", "{{STATION_IDS}}", "{{EXAMPLES}}")


def check_structure(template: str):
    """세 절이 각각 한 번, Role → Task → Example 순서로 있는지. 틀리면 ExtractError."""
    heads = [ln.strip() for ln in template.splitlines() if re.match(r"^# \S", ln)]
    if heads != list(SECTIONS):
        raise ExtractError(f"프롬프트 절 구성이 Role/Task/Example 3단이 아님: {heads}")
    for ph in PLACEHOLDERS:
        if template.count(ph) != 1:
            raise ExtractError(f"프롬프트 자리표시 {ph}가 정확히 1번 있어야 함")


def render_examples(examples):
    parts = []
    for i, ex in enumerate(examples, 1):
        head = (f"## Example {i}\n"
                f"Document: {ex['doc_id']} | Page: {ex['page']} | Section: {ex.get('section') or '-'} | "
                f"Chunk kind: {ex['kind']}")
        parts.append(head + "\nChunk text:\n<chunk>\n" + ex["input_text"] + "\n</chunk>\nOutput:\n"
                     + json.dumps(ex["output"], ensure_ascii=False, indent=2))
    return "\n\n".join(parts)


def check_examples(examples, sensor_ids, station_ids, chunks_by_id=None):
    """예시가 원문에서 왔는지(입력 줄이 실제 청크에 있음, 인용이 입력에 있음)와 ID가 목록 안인지."""
    errors = []
    for ex in examples:
        cid = ex["source_chunk_id"]
        if chunks_by_id is not None:
            c = chunks_by_id.get(cid)
            if c is None:
                errors.append(f"예시 출처 청크 없음: {cid}")
            else:
                for line in ex["input_text"].split("\n"):
                    if line not in c["text"]:
                        errors.append(f"{cid}: 예시 입력 줄이 청크 원문에 없음: {line[:60]!r}")
        for r in ex["output"]["rules"]:
            if r["sourceQuote"] not in ex["input_text"]:
                errors.append(f"{cid}: 예시 sourceQuote가 입력에 없음")
            if r["ruleIdInText"] is not None and r["ruleIdInText"] not in ex["input_text"]:
                errors.append(f"{cid}: 예시 ruleIdInText가 입력에 없음")
            errors += [f"{cid}: 예시 센서 목록 밖 {s}" for s in r["sensors"] if s not in sensor_ids]
            errors += [f"{cid}: 예시 공정 목록 밖 {s}" for s in r["targetStations"] if s not in station_ids]
    if errors:
        raise ExtractError("예시 검사 실패:\n- " + "\n- ".join(errors))


def load_prompt(sensor_ids, station_ids, version=PROMPT_VERSION, prompts_dir=None, chunks_by_id=None):
    d = (prompts_dir or EXTRACT_PROMPTS_DIR) / version
    tpl_path, ex_path = d / "system.md", d / "examples.json"
    template = tpl_path.read_text(encoding="utf-8")
    check_structure(template)
    ex_doc = json.loads(ex_path.read_text(encoding="utf-8"))
    examples = ex_doc["examples"]
    check_examples(examples, set(sensor_ids), set(station_ids), chunks_by_id)
    system = (template.replace("{{SENSOR_IDS}}", "\n".join(f"- {s}" for s in sorted(sensor_ids)))
              .replace("{{STATION_IDS}}", "\n".join(f"- {s}" for s in sorted(station_ids)))
              .replace("{{EXAMPLES}}", render_examples(examples)))
    return {
        "version": version,
        "system": system,
        "prompt_sha256": sha256_text(system),
        "template_sha256": sha256_file(tpl_path),
        "examples_sha256": sha256_file(ex_path),
        "examples_status": ex_doc.get(EXAMPLES_STATUS_KEY),
        "example_chunk_ids": [ex["source_chunk_id"] for ex in examples],
    }


def build_user_message(chunk, doc_title):
    """청크 하나의 사용자 메시지. 문서 제목·쪽·절은 맥락이고, 인용은 <chunk> 안의 텍스트에서만 한다."""
    return (f"Document: {chunk['doc_id']} | Title: {doc_title} | Page: {chunk['page']} | "
            f"Section: {chunk.get('section') or '-'} | Chunk kind: {chunk['kind']} | Chunk ID: {chunk['chunk_id']}\n"
            "Extract the rules stated in this chunk. Copy sourceQuote exactly from the text between <chunk> and </chunk>.\n"
            "<chunk>\n" + chunk["text"] + "\n</chunk>")
