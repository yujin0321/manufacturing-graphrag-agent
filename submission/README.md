# iMAKS 개인 과제 제출물

**목표:** 10/1~10/7 데이터 전처리, Ontology v1, SHACL 실습. 작성·실행일 2026-10-05.

## 먼저 볼 파일

1. `reports/findings.md`: 실제 점검 결과·주의사항·회의 쟁점.
2. `01_data_check.ipynb`: 8개 코드 셀을 끝까지 실행한 학습용 노트북.
3. `ontology_v1.md`: 질문 3개, 클래스 7개, 관계·속성·설계 이유·관계도.
4. `shapes.ttl`, `sample_valid.ttl`, `sample_invalid.ttl`: SHACL 규칙과 예제.
5. `reports/shacl_summary.csv`: 정상·위반 예제 및 정적 KG 검증 9건의 기대 결과 일치 확인.

## 완료한 것

|작업|결과|
|---|---|
|원본 확보|Zenodo 20075430의 ZIP 다운로드, 공개 MD5와 일치 확인|
|데이터 파악|선택 CSV 6개 파일의 모든 컬럼 설명·자료형·결측·예시 저장|
|시계열 점검|211,200행·22센서·9스테이션, 센서별 30초 간격 확인|
|전처리|원본 보존, 시간 형식 정리 및 센서·시각 정렬, 입력 6개 컬럼 분리|
|평가 분리|점 단위 라벨·86개 규칙·14개 정답 이벤트 별도 저장|
|문서|SOP 4개·데이터시트 3개, 총 10페이지 텍스트·표·출처 추출 및 시각 대조|
|KG|ID·관계 끝점·센서 메타데이터 점검, 정적 CSV 및 RDF 생성|
|온톨로지|팀 자체 초안과 실행 가능한 Turtle 생성|
|검증|SHACL 9개 사례와 예제 질문 3개 실행 성공|

이상 탐지 학습·LLM 전체 문서 추출·GraphRAG·Agent 구현은 이번 제출물에 포함하지 않는다. 문서 규칙 1건과 DEMO 이벤트는 구조를 설명하는 수동 예제이다. 전처리 완료는 모델 입력 준비까지이며, 학습/검증/평가 분할 확정은 팀 회의 후 진행한다.

## 실행 방법

Python 3.12 권장. 아래 명령은 `submission` 폴더에서 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe prepare.py
.\.venv\Scripts\python.exe validate_graph.py
```

노트북을 다시 생성하고 모든 셀을 실행하려면:

```powershell
.\.venv\Scripts\python.exe build_notebook.py
```

기존 노트북을 VS Code/Jupyter에서 열어 `.venv`의 Python을 커널로 선택해도 된다. `build_notebook.py`는 커널 등록 정보를 프로젝트 내부 `.jupyter`에만 만든다. 생성 노트북을 직접 수정한 뒤 이 스크립트를 재실행하면 수정 내용은 덮어써지므로 복사본에서 학습할 것.

현재 컴퓨터에서는 Codex 제공 Python을 기반으로 `.venv`를 생성해 실행했다. 실제 라이브러리 버전은 `reports/environment.json`에 기록했다. 위 새 환경 설치 명령 자체를 별도 새 컴퓨터에서 시험한 것은 아니다.

로컬 제출본의 원본 ZIP 위치는 `data/source/iMAKS_dataset.zip`이다. GitHub에는 원본 ZIP과 파생 대용량 데이터를 포함하지 않았으므로 처음 실행할 때 다음 명령으로 다운로드한다:

```powershell
New-Item -ItemType Directory -Force data/source | Out-Null
Invoke-WebRequest 'https://zenodo.org/records/20075430/files/iMAKS_dataset.zip?download=1' -OutFile data/source/iMAKS_dataset.zip
```

`prepare.py`는 MD5 `1670c2d42e9495b9b06a79b867fc5d15`만 허용한다. 다른 버전이면 자동으로 진행하지 않는다.

## 폴더 구분

|경로|사용 목적|
|---|---|
|`data/source/`|다운로드한 원본 ZIP|
|`data/raw/`|원본 ZIP에서 선택 추출한 파일; 수정 금지|
|`data/processed/timeseries_input.csv`|전체 센서 입력; 정답·경보·품질·임계값 제외|
|`data/processed/timeseries_production.csv`|ST01~ST04 부분집합; 115,200행|
|`data/processed/sensor_metadata.csv`|센서·스테이션·단위 매핑|
|`data/processed/static_nodes.csv`, `static_edges.csv`|화이트리스트로 남긴 정적 seed CSV; 39노드·72관계|
|`data/processed/static_graph.ttl`|온톨로지 초안에 맞춰 센서·스테이션·공정 흐름만 변환한 RDF|
|`data/processed/documents.json`|문서 전체 10페이지 추출 결과; 검증된 LLM 지식 추출 결과가 아님|
|`data/evaluation/`|정답 및 제외된 seed 내용; 모델 입력 경로로 사용 금지|
|`examples/`|SHACL 통과·위반 사례; 학습용|
|`reports/`|점검 수치, 해시, 검증 로그, 회의 요약|
|`qa/`|PDF 원본 시각 대조 이미지; 제출 ZIP에서 제외|

정답 분리는 파일 수준의 운영 규칙이며 접근 권한 통제가 아니다. 학습/검색 코드가 `data/` 전체를 재귀적으로 읽지 않도록 입력 파일을 명시해야 한다. `mqtt_payloads.json`은 원본 보존만 했으며 별도 분석하지 않았다. CSI와 인물 시계열은 ZIP 목록에만 기록하고 이번 처리에서 제외했다.

**발견된 데이터 충돌:** `nodes_factory.csv`는 `nodes.csv`와 6개 노드 ID의 센서명이 다르므로 병합하지 않았다. `reports/nodes_factory_conflicts.csv`에 목록을 저장했다.

## 회의에서 이렇게 설명하기

> 원본을 점검했더니 기본 결측·중복 문제는 없어서 측정값을 수정하지 않았습니다. 정답과 경보 정보는 입력에서 분리했습니다. 제조 4개 공정만 보면 이벤트가 9개가 되어 평가 범위를 결정해야 합니다. 센서·이벤트·문서 출처를 연결하는 온톨로지를 제안했고, SHACL 정상·위반 예제가 의도대로 동작하는 것을 확인했습니다. 다음 단계는 분할 기준 확정과 문서 규칙 추출입니다.

## 출처

- Andrea Bernardini, [iMAKS, Zenodo record 20075430](https://zenodo.org/records/20075430). 원본 파일 해시는 `reports/source_manifest.json` 참조.
- [W3C SHACL 권고안](https://www.w3.org/TR/shacl/). 구조 검증과 도메인 사실 검증을 구분한다.
