# iMAKS UI 전달 안내

- demo/index.html을 열고 예제 데이터 → 탐지 실행 → 경보 선택 순서로 시연합니다.
- integration/serve-page.html은 예원12 서버와 같은 출처에서 제공하는 단일 HTML입니다. integration/index.html과 api.js는 분리된 편집 원본입니다.
- 백엔드는 팀이 승인한 예원12 작업본 또는 해당 코드를 통합한 main을 사용합니다.

## 로컬 연동

예원 백엔드의 별도 시연용 체크아웃에서 기존 src/imaks_kg/rag/xai_demo.html을 백업한 뒤 serve-page.html의 내용으로 교체하세요. 현재 서버는 루트(/)에서 이 HTML을 제공하며 별도의 api.js 정적 경로가 없어 단일 파일을 사용합니다. 서버 실행 전에 원본 저장소의 런타임 및 의존성 준비 절차를 따르세요.

```powershell
.\.venv\Scripts\python.exe scripts/run_xai_agent.py --serve --read-only --allow-local-analysis --port 8770
```

브라우저에서 http://127.0.0.1:8770/ 을 엽니다.

- CSV는 UTF-8, 최대 4 MiB, 20,000행이며 열은 timestamp,zone,station_id,sensor_id,sensor_type,value,unit 순서입니다.
- 기존 timeseries_raw.csv도 UI에서 열 수 있습니다. 브라우저에서 서버용 7개 열과 선택 구간을 추출합니다. 큰 파일의 기본 구간은 최근 약 15,000행이며, 전송 한도 안에서 앞선 최대 30분의 관측을 포함합니다.
- 세션 토큰을 가져와 CSV 본문을 POST /api/analyses로 보낸 뒤 완료까지 조회합니다.
- 시간대 표와 목록의 사건은 incident_items를 사용합니다. 상세 화면은 같은 analysis_id와 incident_id로 시계열과 사건 근거를 읽습니다.
- 그래프의 경고 기준선은 센서 메타데이터에서 옵니다. 실제 규칙 조건은 사건의 구조화된 근거에서 확인합니다.
- 업로드 사건 설명은 로컬 코드가 근거로 구성합니다. 정답 14건 자동 비교와 업로드 사건 자유 질문은 이 서버 경로에 포함되지 않습니다.

## 추가 화면 기능
- 업로드에서 분석 시작·종료를 함께 지정하면 시작 전 원본 관측을 선행 계산에 사용합니다. 둘 다 비우면 전체 파일을 분석합니다.
- 저장된 분석 조회와 ZIP 복원은 완료 결과를 다시 엽니다. 결과 화면의 ZIP 내보내기에는 원시 입력이 포함되므로 팀 내부에서 관리합니다.
- 문서·KG 질문 창에서 저장된 질문 실행을 열 수 있습니다. 새 질문은 generation_enabled 서버에서만 가능하며 모델 호출 비용이 발생할 수 있습니다. 읽기 전용 실행에서는 저장 답변만 조회할 수 있습니다.

- 사건 상세의 후속 질문은 같은 분석 ID와 사건 ID의 기존 구조화 근거를 사용합니다. 별도 LLM 호출과 자유 대화 API는 사용하지 않습니다.
