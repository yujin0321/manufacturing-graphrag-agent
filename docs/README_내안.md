# 지훈 브랜치 안(案) 안내

팀은 각자 자기 브랜치에서 끝까지 개발한 뒤 가장 잘된 안 하나를 고른다. 이 문서는 `지훈` 브랜치 안의 입구다. 원래 `README.md`는 건드리지 않았다.

## 목표
iMAKS로 지식그래프(KG)를 직접 만들고, GraphRAG로 설비 이상의 원인 후보를 점수와 함께 제시하는 Agent를 만든다. 진단 성능보다 **LLM으로 KG를 만드는 과정**을 배우는 것이 목적이고, 핵심은 데이터셋에 없는 **새로운 공정 간 인과관계(`causallyAffects`)** 발굴이다.

## 이 안의 특징
- Station(공정) 수준까지만 다룬다. 후보는 `likelihoodScore` 0.6 이상, 이벤트당 상위 3개.
- 정답 라벨은 ⑥ 입력과 분리한다(누수 방지). 점검 도구와 훅이 자동으로 막는다.
- 모든 규칙·관계에 출처(문서, 쪽, 위치, 해시)를 남긴다.

## 읽는 순서
1. `CLAUDE.md` — 확정 결정과 데이터 규칙
2. `work_log.md` — 결정과 이유의 기록
3. `docs/competency_questions.md` — 온톨로지가 답해야 할 질문 5개
4. `ontology_v1/` — `ontology.ttl`, `shapes.ttl`, `schema_tables.md`, `examples/`
5. `src/imaks_kg/`, `tests/` — 전처리 코드와 테스트
6. `.claude/`, `harness/` — 구현·검증 에이전트, 점검 스크립트, 체크리스트
7. `reports/preprocess_impl.md`, `reports/preprocess_verify.md` — 구현·독립 검증 보고서

## 현재 상태 (2026-10-07)
전처리·온톨로지·SHACL 완료, 독립 검증 PASS, 단위 테스트 50개 통과. 다음은 ③ KG 변환.

## 재현
원본 데이터(`imaks_data/`)는 git에 없다. Zenodo(https://zenodo.org/records/20075430)에서 받아 저장소 루트에 둔다.

```
python -m venv .venv
PYTHONPATH=src python -m imaks_kg.preprocess.sensors
PYTHONPATH=src python -m imaks_kg.preprocess.documents
PYTHONPATH=src python -m unittest discover -s tests
```
