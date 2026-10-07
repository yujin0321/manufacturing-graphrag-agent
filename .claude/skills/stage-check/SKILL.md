---
name: stage-check
description: 파이프라인 단계 완료 점검. SHACL 실행, 금지 컬럼(누수) 검색, imaks_data 원본 불변 확인을 한 번에 돌린다. 단계를 마쳤거나 PR 전에 사용.
allowed-tools: Read, Glob, Grep, Bash
---

# 단계 완료 점검

아래 세 스크립트를 저장소 루트에서 실행하고 출력을 그대로 보고한다. 수정은 하지 않는다.

```
python .claude/skills/stage-check/scripts/check_raw_unchanged.py
python .claude/skills/stage-check/scripts/check_leakage.py preprocessed ontology_v1 kg_build src
python .claude/skills/stage-check/scripts/run_shacl.py --data <검증할 .ttl>
```

## 스크립트가 보는 것
- `check_raw_unchanged.py`: `imaks_data/` 파일의 SHA-256을 `harness/raw_manifest.json`과 비교한다. 파일이 바뀌거나 추가/삭제되면 실패(종료 코드 1). 처음 한 번 `--init`으로 기준을 만든다.
- `check_leakage.py`: `harness/forbidden_columns.txt`의 이름이 지정한 폴더의 CSV 헤더, 코드, 노트북, JSON에 나오는지 찾는다. `ground_truth`가 평가용 폴더(`evaluation`, `eval`, `tests`) 밖에서 쓰이면 경고한다. 발견되면 종료 코드 1.
- `run_shacl.py`: `ontology_v1/shapes.ttl`로 데이터 그래프를 검증한다. `pyshacl`이 필요하다(`pip install pyshacl rdflib`).

## 스크립트가 못 보는 것 (수동 확인)
- 출처(provenance) 필드: 문서 ID, 페이지, 문자 위치, 해시가 트리플마다 있는지는 체크리스트로 본다.
- 금지 이름이 아닌 다른 이름으로 정답이 새는 경우. 금지 목록은 실제 CSV 컬럼을 확인한 뒤 갱신한다.
- 키워드가 우연히 일치한 오탐은 사람이 판단한다.
