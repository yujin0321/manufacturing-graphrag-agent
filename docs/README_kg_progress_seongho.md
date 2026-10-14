# 성호 — 이번 주 KG 구축 및 부분 LLM 추출 평가

2026-10-14. 지훈의 전처리/온톨로지/SHACL을 바탕으로 후속 파이프라인을 구현했다.
기반 커밋: `aadac99d34e10409c2608886d4c17435178d6f06`.
다른 팀원처럼 루트 `src/`, `docs/`, `reports/`, `CLAUDE.md`, `work_log.md` 구조를 사용한다.
기존 `submission/`과 `work_records/`는 첫 주차 개인 제출 및 기록이다.

## 먼저 볼 파일

- [현재 맥락](../CLAUDE.md), [날짜별 활동 기록](../work_log.md)
- [회의 보고서](../reports/kg_progress_seongho_2026-10-14.md)
- [평가 정책과 해석](evaluation_policy_seongho.md)
- [추출 설계·프롬프트·응답 스키마](../llm_extraction_design/README.md)
- [집계 평가](../reports/partial_evaluation_seongho_2026-10-14.json)
- [보완 진단](../reports/posthoc_audit_seongho_2026-10-14.json)

## 현재 결과

| 항목 | 결과 |
|---|---|
| LLM | gemini-3.1-flash-lite |
| 완료 | SOP-001/003/004, DS-ELEC-3300 |
| 미완료 | SOP-002, DS-MECH-4400, DS-THERM-2200 |
| 고정 자동 추출 | 56개; SOP 예측50개; 내용 수정 없음 |
| 전체86건 기준 내용 F1 | 66.18% (TP45/FP5/FN41) |
| 처리한 SOP59건 기준 내용 F1 | 82.57% (TP45/FP5/FN14) |
| 분류까지 일치해야 하는 전체 F1 | 44.12% (TP30) |
| LLM-only KG | 검증된54규칙 반영, 1,654트리플, SHACL 적합 |
| 별도 문서 보충 | SOP-002 표 기반27규칙, LLM 결과/점수에 미포함 |
| 보충한 KG | 4,121트리플, SHACL 적합 |

미처리 SOP-002의 정답27건은 전체 LLM 점수에서는 FN으로 포함된다.
내용 F1은 의미 유사도 기반 개발 평가이며 숫자/단위/분류/인과/진단 정확도와 동일하지 않다.
정답을 읽은 후 기존 예측의 문장·분류·수를 바꾸지 않았다. 보충은 별도 source-only 방법이다.
seed 정비 규칙8개와 LLM 정비 규칙은 출처가 다른 별도 노드로 보존했다. 의미상 통합은 미수행이다.
Neo4j용 Cypher 생성까지만 했고 서버 적재는 미실행이다.

## 저장소 공개 범위

코드, 온톨로지, 프롬프트/스키마, 맥락/활동 기록, 집계 보고서만 포함한다.
원본 PDF/시계열/정답, 전체 추출 응답·개별 대조 목록·RDF·ledger·가상환경은 로컬에 보관한다.
따라서 저장소 집계만으로 개별 규칙을 다시 채점할 수는 없다. 로컬 고정 응답을 쓰거나 새 API 실험으로 재현한다.
고정 입력 해시는 공개 집계에 있다. 새 실험은 기존 결과와 구분한다.
API 키는 로컬 `.env`에서 읽고 Git에서 제외한다.

## 재현

Python 3.12에서 실행했다. 원본은 [iMAKS Zenodo](https://zenodo.org/records/20075430)에서 받아
루트 `imaks_data/` 아래 `kg_seed/`, `sensors/`, `rules/`, `datasheets/` 구조로 준비한다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONUTF8='1'
$env:PYTHONPATH='src'
.\run_stage3.ps1
```

위 명령은 전처리·seed KG·요청 생성·입력 감사·테스트이며 유료/무료 API를 자동 호출하지 않는다.
`.env.example`을 `.env`로 복사하고 키를 입력한 후 명시적으로 호출한다.

```powershell
.\.venv\Scripts\python.exe -m imaks_kg.stage3.gemini --run-name new-run --model gemini-3.1-flash-lite
.\.venv\Scripts\python.exe -m imaks_kg.stage3.extract --import-responses artifacts/stage3/model_calls/new-run/responses.jsonl
# 모델 호출이 일부만 끝났다면 완료 응답만 모은 JSONL을 사용하고 --allow-partial 지정
.\.venv\Scripts\python.exe -m imaks_kg.stage3.evaluate --predictions artifacts/stage3/runs/RUN_ID/predictions.jsonl --output evaluation/new_result.json --revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41
.\.venv\Scripts\python.exe -m imaks_kg.stage3.build --predictions artifacts/stage3/runs/RUN_ID/validated_predictions.jsonl
.\.venv\Scripts\python.exe -m imaks_kg.stage3.supplement
.\.venv\Scripts\python.exe -m imaks_kg.stage3.build --predictions artifacts/stage3/runs/RUN_ID/validated_predictions.jsonl --supplement artifacts/stage3/sop002_source_supplement.jsonl
```

기존 run은 같은 설정으로만 재개하며 결과와 평가를 덮어쓰지 않는다.
문서 보충은 heading/연속 표 문맥으로 Station을 결정하고 모호하면 실패한다. 정답을 읽지 않는다.

## 남은 일

미완료 문서의 실제 LLM 추출, 분류/숫자/단위/대상/근거의 사람 검토,
seed/LLM 규칙 중복 통합 검토, Neo4j 적재 및 조회는 후속이다.
