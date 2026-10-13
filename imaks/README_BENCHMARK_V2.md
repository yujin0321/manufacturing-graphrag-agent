# GraphRAG 재설계 평가

VS Code에서 `notebooks/04_graphrag_fair_benchmark.ipynb`를 열고 프로젝트 `.venv` 커널을 선택하세요. 이전 노트북과 결과는 보존했습니다.

## 비교 대상

| 방법 | 구현 |
|---|---|
| hybrid | BM25 + 로컬 다국어 MiniLM 벡터 검색, RRF 결합 |
| graph_expansion | 같은 검색기에 관련 설비·규칙 검색어 추가 |
| graph_paths | 최대 3단계 관계 경로와 연결된 규칙·과거 경보를 원문과 함께 제공 |

문서뿐 아니라 정적 그래프 사실의 텍스트 버전도 모든 방법의 공통 검색 코퍼스에 있습니다. 그래프 방법에만 새로운 정답 사실을 제공하지 않습니다.

총 문맥 한도는 공통 계수기 `cl100k_base` 기준 1,800토큰입니다. 그래프 경로도 이 한도에 포함하고 모든 방법이 남은 한도를 사용할 수 있습니다. 각 기록을 통째로 넣으므로 사용량은 약간 다릅니다. 이 계수기가 GPT-6 내부 토크나이저와 같다고 주장하지 않습니다. 키워드/임베딩의 RRF 상수는 60이며, 최종 결과를 보고 튜닝하지 않습니다.

## 질문과 평가 단위

`benchmark_v2.json`에 5유형×3질문=15개 사례와 필수 근거·기대 사실·조건 제약을 고정했습니다.

- 단일 문서 확인
- 여러 설비 관계 연결
- 시점별 과거 경보
- 문서 간 기준 비교
- 정보 부족·잘못된 확정 요구

기존 Q01-Q08과 `evaluation_ko.json`은 개발용입니다. 이번 사례는 새 조합과 시점이지만 일부 규칙·의도가 겹치며 같은 작성자가 구성했습니다. 외부 독립 테스트셋은 아닙니다. 특히 유형별 3개뿐이므로 일반화 주장은 제한합니다.

유형/정답 기준은 답변 생성에 제공하지 않습니다. 센서 ID는 모든 방법에 동일하게 주어지므로 이 평가에 한국어 센서 식별 정확도는 섞이지 않습니다.

## 시간 정보

이전 탐지 모델의 예측 경보에서 `observed_at`과 측정값만 가져옵니다. 실제 이상 주입 시작 시각·종료 시각·원인 라벨·미래 수리 결과는 포함하지 않습니다. 각 질문의 `as_of`와 lookback으로 경보를 필터링합니다. 미래 경보가 제외되는지 자동 테스트합니다.

T01의 관측 시간 차는 09:15:30 → 09:30:00으로 14분30초입니다. 이는 실제 고장 시작 시간이나 인과관계를 확증하지 않습니다. 같은 이상이 여러 조각의 경보로 관측될 수도 있습니다.

## LLM 실행과 채점

사용자가 질문·문서 발췌·설비 관계·시각별 예측 경보 전송을 명시 승인한 범위에서 답변 생성 90회(15×3×2)와 질문별 익명 채점 15회를 실행합니다. 원본 ZIP 전체를 전송하지 않습니다.

- 모델: `gpt-6-astra`, 추론 설정 low, 새 임시 세션.
- CLI에서 temperature를 직접 설정할 수 없어 실제 제어값을 null로 기록합니다. temperature=0 실험이라고 주장하지 않습니다.
- 같은 질문의 반복에도 같은 입력을 사용하며 성공 캐시는 입력 해시로 확인합니다.
- 생성 시 도구 사용이 발생하면 해당 결과를 거부합니다. 실패한 결과는 가짜 응답으로 채우지 않습니다.
- AI 평가자에게 방법·반복 이름을 숨기고 답변 순서를 섞습니다. 문맥의 그래프 형식으로 방법을 추측할 가능성이 있어 완전한 맹검은 아닙니다.
- 근거 일치·조건 처리·완전성을 각각 0–2점으로 평가합니다. 같은 모델의 자기평가 편향이 있을 수 있으며 독립적인 사람 평가를 대신하지 않습니다.

서비스가 보고한 토큰 수·실행 시간도 저장합니다. CLI 기본 지침이 포함되므로 토큰 수는 검색 문맥 크기보다 큽니다. 청구 금액이나 실제 백엔드 모델 버전을 독립 인증하는 지표는 아닙니다.

## 불확실성

질문당 두 반복을 먼저 평균하고 질문 ID를 재표집하는 짝 부트스트랩을 5,000회 수행합니다. 서로 같은 질문의 반복을 독립적인 90개 질문으로 취급하지 않습니다. 질문 간 같은 문서·설비 의존성은 남아 있으므로 이 신뢰구간을 다른 공장으로 일반화하지 않습니다.

## 실행

```powershell
.\.venv\Scripts\python.exe prepare_benchmark_v2.py
.\.venv\Scripts\python.exe -m unittest test_benchmark_v2 -v
.\.venv\Scripts\python.exe run_benchmark_v2.py generate --workers 3
.\.venv\Scripts\python.exe run_benchmark_v2.py judge --workers 3
.\.venv\Scripts\python.exe summarize_benchmark_v2.py
.\.venv\Scripts\python.exe build_benchmark_v2_notebook.py
```

의존성은 `requirements-benchmark.txt`에 있습니다. 임베딩 모델은 최초 다운로드 후 로컬에서 실행합니다. Windows 인증서 경로에서 pip 오류가 나면 설치 당시 사용한 `--use-deprecated=legacy-certs` 옵션을 참고하세요.

## 결과 위치

- `benchmark_v2_outputs/completion.json`: 실제 완료 건수와 미완료 여부
- `retrieval_metrics.csv`, `retrieval_by_type.csv`: 검색 평가
- `generation/answers/`, `generation/logs/`: 실제 생성 답변과 로그
- `judge/answers/`, `judge_private_mapping.json`: 익명 채점과 원래 방법 연결
- `answer_summary.csv`, `answer_by_type.csv`: 답변 품질·유형별 점수
- `paired_bootstrap.csv`: hybrid 대비 차이와 질문 단위 신뢰구간
- `answer_review_detail.json`: 실제 문맥·답변·평가 사유

결과는 이 데이터셋·질문셋·모델·구현 범위에 한정됩니다. 수리 성공률은 평가하지 않습니다.
