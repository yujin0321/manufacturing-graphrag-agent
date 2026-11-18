# iMAKS 후속 구현

센서 탐지 입력은 common_v1로 연결했다. 2026-10-05에 평균3/STUCK11을 기본 설정으로 적용했다. [README_APPLIED_WINDOW.md](README_APPLIED_WINDOW.md)를 참조한다. `imaks_pipeline.py --detection-only`는 `experiments/common_v1_detection_window3`, 옵션 없는 전체 실행은 `pipeline_outputs_window3`에 새 결과를 저장한다. 기존 결과와 아래 수치·노트북은 이전 실행 기록으로 보존한다.

임계값 사용 정책은 `README_PREPROCESSING.md`를 참조하세요. 현재 코드의 통계 탐지기는 raw의 nominal·경보 임계값을 사용하지 않습니다. 아래 기존 수치·저장된 노트북은 이전 조건의 결과이며, 새 조건 비교 결과는 `preprocessed/threshold_policy_evaluation`에 별도로 생성합니다.

한국어 질의와 조치 조건 검증 후속 작업은 `notebooks/03_korean_conditions_evaluation.ipynb`와 `README_ASSISTANT.md`에 있습니다.

VS Code에서 `notebooks/02_graph_detection_retrieval.ipynb`를 여세요. 전체 분석 결과와 그림이 저장되어 있습니다. 재실행 커널은 프로젝트 `.venv`입니다.

## 구현 범위

1. EDA의 설비·센서 목록과 관계 CSV로 정적 그래프 구성: 노드 31개, 관계 26개. 양방향 monitors를 설비→센서 has_sensor로 정규화하고 원본 출처 보존.
2. PDF 7개·10페이지에서 원문 64청크 추출. 문서명·페이지·규칙 ID·원문 저장 및 동일 페이지 내 원문 존재 검증. PDF 추출 텍스트는 원문 자료로만 사용.
3. 첫 ST02 사례에 원문 근거 연결. 별도로 모델이 예측한 경보 11건에 시점별 그래프·문서 후보 연결.
4. 학습 1/6, 검증 1/7, 평가 1/8–1/9. 실제 사건 수 각각 2/4/8건. 사건이 경계를 가로지르면 중단.
5. SOP 임계값 기준선과 강건 통계 기반 탐지 비교. 미래 정보 배제 및 사건 일대일 평가.
6. 동일 코퍼스·영문 질문·top-k로 일반 BM25와 그래프 보강 검색 비교. 사용자 선택에 따라 LLM 호출은 없음.

## 결과 해석

| 평가일 결과 | SOP 경고 임계값 | 강건 통계 + 과거 윈도우 |
|---|---:|---:|
| 사건 탐지 | 7/8 | 8/8 |
| 생성 경보 | 33 | 11 |
| 사건 정밀도 | 21.2% | 72.7% |
| 사건 재현율 | 87.5% | 100% |
| 실제 사건과 전혀 겹치지 않는 경보 | 0 | 0 |
| 일대일 매칭 후 남는 경보 조각 | 26 | 3 |

경보가 조각나 발생하면 첫 매칭 이후 조각은 정밀도에서 벌점을 받습니다. 실제 이상 구간 밖의 양성 행도 별도로 집계합니다(강건 모델 52행). 따라서 '오탐 0으로 완벽한 모델'이라는 해석은 잘못입니다. 탐지된 사건의 지연 중앙값은 양쪽 0분이지만 사건별 지연은 다르므로 `*_event_matches.csv`를 함께 보세요.

학습 시 라벨은 쓰지 않습니다. 학습 데이터에도 이상이 있어 median/MAD로 완화했으며, 정상 전용 학습을 했다고 주장하지 않습니다. 10개 관측의 평균 편차와 11개 관측의 정체 규칙을 결합합니다. 시간 분할과 공백마다 윈도우를 초기화합니다. 검증일 사건 F1과 경보 수로 선택된 임계값은 순간 6, 평균 4입니다. 평가일을 보고 다시 튜닝하지 않았습니다.

검색 비교는 두 방식 모두 개발 질문 8개에서 hit@3·필수 규칙 회수율·MRR@3·조치 근거 포함률이 1.0입니다. 문서의 명확한 규칙을 직접 묻는 작은 영문 질문셋이라 쉽습니다. GraphRAG 우월성, 한국어 검색 성능, 생성 답변 품질을 입증하지 않습니다. 독립적인 다단계 질문과 부정 사례가 다음 실험에 필요합니다.

## 주요 산출물 (`pipeline_outputs`)

- `static_graph.json`, `graph_document_links.json`: 정적 그래프와 문서 연결
- `sources/`: 원본 PDF 사본, 페이지별 텍스트와 렌더링
- `document_chunks.json`: 페이지 출처가 있는 검색 코퍼스
- `first_event_evidence.json`: 첫 ST02 사건의 실제 측정값과 SOP 근거
- `predicted_event_evidence.json`: 예측 경보별 검색 근거 후보와 이전 경보
- `temporal_splits.csv`, `selected_model.json`: 분할 및 선택 기준
- `detection_metrics.csv`, `*_event_matches.csv`: 탐지·지연·누락·오탐 상세
- `retrieval_comparison.csv`, `retrieval_details.json`: 검색 지표와 실제 후보
- `row_predictions.csv.gz`: 전체 행의 탐지 결과

정답 이벤트는 `evaluation_truth_events.csv`에 별도로 보관합니다. 정적 검색 그래프에 넣지 않습니다. 현재 시점 이후의 대응 기록이나 예측 종료 시각도 온라인 근거에 넣지 않습니다.

첫 ST02 온도 사례의 SOP-001 p.1 RULE-ST02-02는 ST02/ST03/ST04 긴급 정지를 명시하지만 대응 로그 문구는 다릅니다. `first_event_evidence.json`은 규정 조치와 사후 기록을 구분합니다. 이 데모는 현장 설비에 명령을 전송하지 않습니다.

## 재현

프로젝트 루트에서:

```powershell
.\.venv\Scripts\python.exe inspect_sources.py
.\.venv\Scripts\python.exe imaks_pipeline.py
.\.venv\Scripts\python.exe -m unittest test_pipeline -v
.\.venv\Scripts\python.exe build_pipeline_notebook.py
```

기존 EDA 결과가 필요합니다. 새 환경에서는 먼저 `build_eda.py`를 실행하세요. 의존성은 `requirements-eda.txt`에 있습니다. 소스 파일 및 전용 가상환경은 기존 EDA와 같은 작업 폴더를 사용합니다.

## 한계

- 규칙형 후보 검색까지 구현. 조건을 모두 검증한 조치 선택기, LLM 답변 생성, 실제 운용 UI는 후속 범위입니다.
- 제공된 raw 임계값을 사전에 알려진 설정으로 취급합니다. 모든 임계값과 센서 데이터시트 충돌을 교차 감사하지 않았습니다.
- 학습 1일·검증 사건 4건·평가 사건 8건이라 수치를 일반화할 수 없습니다.
- 문서에 명시된 상관 관계는 현재 사건의 인과 판정이 아닙니다.
- 첫 라벨 연결 사례는 사후 데모이고, 모델 평가와 예측 근거 패키지는 별도입니다.
