# KG Validation Pipeline (kg-val-sumin)

이 작업은 현재 `main`의 `ontology_v1/` 설계를 기준으로, 검증된 전처리 산출물에서 KG ABox와 Rule 후보를 구축하고 `ground_truth.csv`와 대조하는 첫 정량 평가 파이프라인이다.

## 원칙

- KG 구축 코드는 원본 CSV/PDF를 직접 읽지 않는다.
- `kg_seed/nodes.csv`, `kg_seed/edges.csv`는 구축 입력이 아니라 평가/감사용 참고 자료로만 사용한다.
- `ground_truth.csv`는 추출·구축 입력이 아니라 평가 단계에서만 사용한다.
- 기준 스키마는 `ontology_v1/ontology.ttl`, 검증 제약은 `ontology_v1/shapes.ttl`이다.

## 실행

```bash
PYTHONPATH=src python -m imaks_kg.kg_build.preprocessed_abox --preprocessed preprocessed/final_v1 --out kg_build/latest
PYTHONPATH=src python -m imaks_kg.kg_build.document_nodes --preprocessed preprocessed/final_v1 --out kg_build/latest
PYTHONPATH=src python -m imaks_kg.kg_build.rule_extract --preprocessed preprocessed/final_v1 --out kg_build/latest
PYTHONPATH=src python -m imaks_kg.eval.metrics \
  --pred kg_build/latest/rules_extracted.jsonl \
  --ground-truth preprocessed/final_v1/evaluation/rules_ground_truth_original.csv \
  --out-dir evaluation
```

## 산출물

- `kg_build/latest/nodes.jsonl`: Station, Sensor 노드
- `kg_build/latest/relationships.jsonl`: `hasSensor` 관계
- `kg_build/latest/rules_extracted.jsonl`: 문서 기반 Rule 후보
- `kg_build/latest/rule_extract_summary.json`: 추출 요약
- `evaluation/kg_val_metrics.json`: 정량 평가 요약
- `evaluation/kg_val_matches.csv`: 매칭/미매칭 목록

`kg_build/`와 `evaluation/`은 Git 추적 대상이 아니다.

## 현재 한계

- 현재 extractor는 deterministic baseline이다. LLM 호출 결과는 같은 JSONL 스키마로 `rules_extracted.jsonl`에 병합할 수 있게 설계했다.
- 평가 매칭은 외부 임베딩 모델 없이 동작하도록 lexical content similarity를 기본값으로 사용한다.
- seed KG와의 구조 비교는 `src/imaks_kg/eval/seed_reference.py`로 분리했으며 KG 구축 경로에서는 사용하지 않는다.
