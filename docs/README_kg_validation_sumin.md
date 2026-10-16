# KG Validation Pipeline (kg-val-sumin)

## 2026-10-16 업데이트

실제 실행 완료: [구현·결과 보고서](../reports/sumin_sol_implementation_results_impl.md). SOP 105건 / 정답 86건, F1_content 0.785340, 분류까지 F1 0.544503. 후보 KG SHACL 통과.

GPT-6.1 Sol 실험은 [연결·실행 안내](sol_api_setup_sumin.md)를 따른다.
[방향 검토](direction_review_sumin.md)와 사용자 제공 두 평가 정의서를 기준으로 한다.
`sol_extract`가 자동 예측을 고정하고 `eval.sol_evaluate`가 SBERT/Hungarian으로 평가한다.
아래 기존 `eval.metrics` 명령은 어휘 대리 기준선이며 팀 정의의 F1_content가 아니다.
기존 `llm_rule_extract`는 이전 구현으로 남겼으며 새 유료 실험의 실행 경로로 사용하지 않는다.

이 작업은 현재 `main`의 `ontology_v1/` 설계를 기준으로, 검증된 전처리 산출물에서 KG ABox와 Rule 후보를 구축하고 `ground_truth.csv`와 대조하는 첫 정량 평가 파이프라인이다.

## 원칙

- KG 구축 코드는 원본 CSV/PDF를 직접 읽지 않는다.
- `kg_seed/nodes.csv`, `kg_seed/edges.csv`는 구축 입력이 아니라 평가/감사용 참고 자료로만 사용한다.
- `ground_truth.csv`는 추출·구축 입력이 아니라 평가 단계에서만 사용한다.
- 기준 스키마는 `ontology_v1/ontology.ttl`, 검증 제약은 `ontology_v1/shapes.ttl`이다.
- SOP-002 threshold table의 Station 매핑은 `pages.jsonl`의 `StationID Thresholds` heading과 `tables.jsonl`의 page/table 순서로 결정한다. 새 heading 없이 다음 페이지로 이어지는 표는 직전 Station heading의 continuation으로 처리한다.

## 기존 결정적 기준선 실행

의존성 설치:

```bash
python3 -m pip install -r requirements.txt
```

기본 경로는 `preprocessed/final_v1`, `preprocessed`, `processed` 순서로 자동 감지한다. 특정 산출물을 쓰려면 `--preprocessed`에 명시한다.

```bash
PYTHONPATH=src python3 -m imaks_kg.kg_build.preprocessed_abox --out kg_build/latest
PYTHONPATH=src python3 -m imaks_kg.kg_build.document_nodes --out kg_build/latest
PYTHONPATH=src python3 -m imaks_kg.kg_build.rule_extract --out kg_build/latest
PYTHONPATH=src python3 -m imaks_kg.kg_build.rdf_export --build-dir kg_build/latest --out kg_build/latest/kg.ttl
PYTHONPATH=src python3 -m imaks_kg.kg_build.shacl_validate --data kg_build/latest/kg.ttl --report evaluation/shacl_report.txt
PYTHONPATH=src python3 -m imaks_kg.eval.metrics \
  --pred kg_build/latest/rules_extracted.jsonl \
  --ground-truth preprocessed/final_v1/evaluation/rules_ground_truth_original.csv \
  --out-dir evaluation
```

새 LLM 실행·평가는 [Sol 실행 안내](sol_api_setup_sumin.md)를 따른다. 기존 `latest` 산출물은 기준선으로 보존하고 실제 Sol 결과는 `kg_build/sumin-sol-v1-live/`에 저장한다.

## 산출물

- `kg_build/latest/nodes.jsonl`: Station, Sensor 노드
- `kg_build/latest/relationships.jsonl`: `hasSensor` 관계
- `kg_build/latest/rules_extracted.jsonl`: 문서 기반 Rule 후보
- `kg_build/latest/rules_llm_extracted.jsonl`: LLM 기반 Rule 후보
- `kg_build/latest/kg.ttl`: SHACL 검증용 RDF 변환본
- `kg_build/latest/rule_extract_summary.json`: 추출 요약
- `kg_build/latest/llm_rule_extract_summary.json`: LLM 추출 요약
- `evaluation/shacl_report.txt`: SHACL 검증 결과
- `evaluation/kg_val_metrics.json`: 정량 평가 요약
- `evaluation/kg_val_matches.csv`: 매칭/미매칭 목록

`kg_build/`와 `evaluation/`은 Git 추적 대상이 아니다.

## 기존 기준선의 범위

- `rule_extract`는 deterministic baseline이고, `llm_rule_extract`는 이전 추출기다. 새 실제 실행은 `sol_extract`를 사용한다.
- 위 기존 평가 명령은 lexical content similarity 대리 지표다. 새 `sol_evaluate`는 첨부 MD에 정의된 MiniLM 임베딩을 사용한다.
- seed KG와의 구조 비교는 `src/imaks_kg/eval/seed_reference.py`로 분리했으며 KG 구축 경로에서는 사용하지 않는다.
- SOP-002 threshold table에서 문서 heading으로 Station을 결정할 수 없거나, 문서에서 추출한 Station ID가 전처리 센서 입력으로 구축한 Station과 일치하지 않으면 임의 추정하지 않고 실패 처리한다.
