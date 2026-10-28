# 팀 공유 안내 — GraphRAG + Agent

2026-10-28. 기본 KG는 예원 v2(2,806트리플)로 고정한다. 일반 Agent와 정답 제공 시연은 서로 다른 폴더·화면으로 실행한다.

## 전달 파일

`kg_build/team_handoff_20261028/`에 두 ZIP과 SHA-256 목록이 생성된다. 업로드·푸시는 별도이며 이번 작업에서는 하지 않는다.

1. `imaks_agent_runtime.zip`: 일반 시연 코드, 기존 KG·문서 청크·벡터 인덱스, 봉인된 탐지 후보, 저장된 대표 답변, 실행 설정과 안내. 원문에서 유래한 내용이 포함되므로 프로젝트 팀 내부 공유용이다. API 키·가상환경·원본 전체 데이터셋·정답 이벤트 그래프는 넣지 않는다.
2. `imaks_gold_demo_ONLY.zip`: 정답 이벤트 14건의 별도 RDF·대응표·조회 결과·HTML 및 검증 코드. 탐지·추출 평가 입력으로 사용하지 않는다. 일반 묶음 폴더 안에 풀지 않는다.

ZIP 내부 `BUNDLE_MANIFEST.json`은 파일별 해시를 제공하고 외부 `bundles.json`은 ZIP 자체의 해시와 크기를 기록한다. 원본 ZIP 파일 이름이나 경로를 임의로 모델 도구 입력에 넘기지 않는다.

## 일반 Agent 실행

별도 폴더에 `imaks_agent_runtime.zip`을 풀고 그 폴더에서 실행한다. Python 및 requirements-rag.txt의 패키지가 필요하다. 가상환경과 모델 가중치는 포함하지 않는다. 기존에 패키지가 있다면 다시 설치할 필요가 없다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-rag.txt
$env:PYTHONPATH='src'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m imaks_kg.rag.demo --port 8768
```

`http://127.0.0.1:8768/`을 연다. **저장된 결과 → 결과 열기**는 API 키·추가 요금 없이 사용할 수 있다. 새 질문은 로컬 `OPENAI_API_KEY` 설정이 필요하고 선택·임베딩·생성 비용이 발생할 수 있다. API 키를 채팅·Git·공유 ZIP에 넣지 않는다.

질문 영역의 실행 방식에서 기존 GraphRAG 또는 Agent를 고른다. Agent는 문서 질문·후보 목록·후보 설명·현재 상태 부재를 분류하고 허용된 도구만 실행한다. 후보가 여러 개면 ID를 선택해 새 질문으로 입력한다. 대화 메모리는 없다.

## 정답 제공 시연

별도 폴더에 `imaks_gold_demo_ONLY.zip`을 푼다. `kg_build/gold_event_demo_20261028/index.html`을 브라우저로 열면 미리 계산된 14건의 경로를 볼 수 있다. 자바스크립트·API·모델 없이 작동한다. 프로젝트 코드 환경에서는 아래 서버 방식도 가능하다.

```powershell
$env:PYTHONPATH='src'
python -m imaks_kg.rag.seed_event_demo --serve --port 8769
```

위 Python 실행은 일반 코드·패키지를 갖춘 프로젝트 환경이 필요하다. 별도 ZIP만 받은 팀원은 HTML 열기를 사용한다. 원본으로 그래프를 다시 만들려면 허가된 nodes.csv·edges.csv 또는 원본 ZIP, raw_manifest, 기존 KG가 추가로 필요하다. 정답 시연 ZIP은 원본 재구축용 전체 데이터 배포본이 아니다.

## 완료·한계

- 도구 계약, 제한된 모델 선택·근거 조회·답변 생성, 시연 UI 연결 완료.
- 문서 질문, 특정 후보 설명, 복수 후보 선택 요청, 현재 상태 답변 유보를 실제 API 사례로 확인. 실패했던 전달 형식 문제와 수정 기록도 보존.
- 정답 이벤트 14건 적재·출처 대응·별도 조회 화면과 일반 경로 격리 검사 완료.
- 통합 회귀 테스트 50개 통과. 평가 기준선 699개 파일 변경 없음.
- 이 수치는 기능 검증이다. 독립 미노출 정확도, 제조 인과관계 발견, 실제 설비 진단·조치 실행의 검증이 아니다.
- STUCK 동일값 11표본 가정, AI 단독 검토, 기존 정답 노출·개발 재시험 한계는 유지된다.
- 임계값 탐지의 원본 센서 전체 데이터와 전체 평가 자료는 묶음에 포함하지 않는다. 전체 모델 평가·탐지 재실행용 배포본이 아니다.

상세 근거: [Agent 화면 검증](../reports/agent_ui_validation_20261028_verify.md), [정답 시연 검증](../reports/gold_event_demo_20261028_verify.md), [전체 점검](../reports/e2e_handoff_20261028_verify.md).
