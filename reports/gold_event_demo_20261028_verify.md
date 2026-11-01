# 3단계 — 정답 이벤트 14건 별도 시연

2026-10-28. 원래 일정의 ‘정답 이벤트 14건 선투입’을 별도 시연 그래프로 구현했다. 기본 예원 v2·일반 GraphRAG·Agent·탐지 평가 경로에는 병합하지 않았다.

## 완료 내용

- 해시를 확인한 원본 `kg_seed/nodes.csv`에서 `AnomalyEvent` 14개, 고유 `gtId` 14개를 확인했다.
- 비어 있지 않은 원본 필드를 문자열로 그대로 보존했다. magnitude의 단위·원인·조치를 추정해서 추가하지 않았다.
- `edges.csv`의 `Sensor → triggers → Event` 원본 연결을 근거로 시연용 `Event → observedSensor → Sensor` 관계를 만들었다. 방향을 바꾼 조회용 표현이며 새 인과관계 주장이 아니다.
- 각 센서는 원본 nodeId와 v2의 sourceNodeId로 정확히 대응시켰다. 이름 유사도나 모델 추정으로 매핑하지 않았다.
- 이벤트별 센서 1개와 해당 센서에 연결된 기존 v2 규칙·출처를 조회했다. 14건 모두 조회 가능하며 연결 규칙은 사건별 2~6개다.
- 원본의 sourceRule은 문자 그대로 보존한다. 해당 이름을 특정 SOP 규칙과 동일시하지 않는다. 조회된 규칙 목록도 사건의 원인·충족 조건·정답 조치를 판정한 결과가 아니다.

## 그래프와 출처

| 항목 | 결과 |
|---|---|
| 기본 예원 v2 | 2,806트리플, 변경 없음 |
| 별도 이벤트 그래프 | 309트리플, 이벤트 14개 |
| 기본 KG SHA-256 | `8ab82a866135afd1335caab06fe6e6e223d7b1ea37195e3fe6509cbbd407ef51` |
| nodes.csv SHA-256 | `3b78a37ff96c39cd5ef2b1b9bf6019d9c951c7926ca4e708e8cb365b9581964e` |
| edges.csv SHA-256 | `18f6556db405f22091a7c5f2bd5d15e2cebe51597ecd33c8da54c84113b46bd3` |
| API·모델 다운로드 | 없음 |

로컬 산출물은 `kg_build/gold_event_demo_20261028/`에 있다.

- `events.ttl`: 별도 그래프. 실험 전용 이름공간과 ProvidedAnomalyEvent 타입 사용.
- `mapping.json`: 14건의 원본 필드·nodeId·센서 매핑·원본 간선 행 번호.
- `queries.json`: 사건별 규칙·문서·provenance 및 실제 관계 경로.
- `manifest.json`: `gold_loaded=true`, `evaluation_run=false`, `mode=gold_provided_demo`, 입력 해시.
- `index.html`: 결과를 조회하는 별도 시연 화면.
- `complete.json`: 위 산출물들의 SHA-256 봉인.

초기 산출물 생성 후 로컬 서버 기능만 코드에 추가했다. manifest의 code_sha256은 산출물 생성 당시 코드 해시다. 그래프 파일을 덮어쓰거나 봉인을 갱신하지 않았다.

## 격리·검증

`tests/test_seed_event_demo.py`의 테스트 **3개 통과**:

1. 14건의 보존 필드가 원본과 동일하고, 각 사건의 센서 연결과 조회 경로가 있으며 기본 KG에 시연 이벤트가 없음을 검사.
2. 기존 산출물 덮어쓰기 거부, 파일 변조 시 무결성 검사 실패 확인.
3. 원본 kg_seed 및 gold_event_demo 경로를 읽으면 실패하도록 감시한 상태에서 일반 후보 목록·후보 근거·캐시 문서 검색을 실행하여 시연 자료를 읽지 않음을 확인.

이는 검사한 정상 경로의 격리 검증이며 모든 미래 코드 변경에 대한 보장은 아니다. 기존 평가 전체를 재실행하거나 과거 정답 노출 이력을 없앤 것은 아니다. 구조·매핑 검사는 Python/RDF 검사로 수행했으며 별도 SHACL 실행 결과로 보고하지 않는다.

## 화면 실행

```powershell
$env:PYTHONPATH='src'
$env:PYTHONUTF8='1'
..\.venv\Scripts\python.exe -m imaks_kg.rag.seed_event_demo --verify
..\.venv\Scripts\python.exe -m imaks_kg.rag.seed_event_demo --serve --port 8769
```

`http://127.0.0.1:8769/`에서 확인한다. 서버는 loopback 주소의 루트 페이지만 제공하고 일반 디렉터리 목록이나 정답 파일 API를 제공하지 않는다. 일반 Agent 화면의 포트 8768과 분리돼 있다. 화면에 ‘정답 이벤트를 제공받은 시연’임을 표시했고, 브라우저에서 14건 목록과 GT-0001의 원본 필드·센서·규칙·출처 경로를 확인했다.

새로 생성하려면 `--output`으로 **존재하지 않는 새 폴더**를 지정한다. 원본 데이터 또는 원본 ZIP, 기존 v2 KG와 가상환경이 필요하다. 로컬 산출물 경로는 Git 제외 대상이므로 코드만 공유하면 생성 자료까지 전달되지는 않는다.

## 이번 단계의 범위

14건 적재·출처 대응·그래프 조회·화면 표시·일반 경로 격리까지 완료했다. 정답을 입력받은 조회 시연이며 이상 탐지 정확도 검증이나 신규 지식 발견 실험은 아니다. 해당 정답을 LLM에 보내 설명을 생성하지 않았다. 일반 Agent가 정답 이벤트를 답변에 자동 혼합하지 않도록 독립 화면으로 제공한다.

다음은 4단계인 전체 E2E 점검과 팀 공유 자료 묶음 정리다. 이번 작업은 커밋·푸시하지 않았다.
