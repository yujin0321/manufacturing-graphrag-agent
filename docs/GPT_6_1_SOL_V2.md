# GPT-6.1 Sol v2 실행 및 결과 안내

이 브랜치의 공유 결과는 `reports/GPT_6_1_Sol_v2_team_evaluation_20261016_verify.md`다.
주 지표는 **팀 평가 기준 F1_content 86.19%**다. `artifacts/gpt_6_1_sol_v2/summary.json`에 집계 결과가 있다.

## 공개 범위

- v2 프롬프트 생성, API 호출, 출처 검증, KG 생성, 팀 기준 재채점 코드와 회귀 테스트.
- 팀 평가 정의서, v2 전용 보고서, 집계 결과·입력 해시·SHACL 통과 기록.
- 원문, 개별 예측/매칭, API 응답, API 키, 모델 가중치는 공개하지 않는다. 원문과 고정 실험 자료는 팀 내 승인된 경로에서 별도로 확보해야 한다.
- 팀 정의서의 문장 형식 민감도는 미측정이다. 과거 실험에 없던 사전 잠금을 소급 생성한 것으로 주장하지 않는다. 한계는 보고서 8장에 명시했다.

## 실행 전제

기존 전처리 단계의 `preprocessed/documents/`와 원본 iMAKS 데이터가 필요하다.
원본은 `imaks_data/` 또는 `IMAKS_DATA_ZIP` 환경변수로 지정한 원본 ZIP에서 읽는다.
`harness/raw_manifest.json`과 일치해야 한다. 전처리는 기존 저장소의 전처리 안내를 따른다.

Python 경량 환경에 numpy, rdflib, pyshacl이 필요하다. API 통신에는 추가 SDK가 필요 없다.
아래 명령의 `python`은 해당 환경의 Python이다. 로컬 대용량 모델 설치는 필요하지 않다.

```powershell
$env:PYTHONPATH = 'src'
python -m imaks_kg.kg.documents prepare
python scripts/prepare_extraction_v2.py
```

API 키를 실행 프로세스의 `OPENAI_API_KEY`에 설정한 뒤 실행한다. 다음 명령은 **유료 API 호출**이며 문서 원문을 OpenAI로 전송한다. 새 호출의 출력은 비결정적이므로 보고된 점수와 같다고 보장할 수 없다.

```powershell
python -m imaks_kg.kg.run_llm --endpoint https://api.openai.com/v1/chat/completions --model gpt-6.1-sol --key-env OPENAI_API_KEY --request-root kg_build/openai_sol_v2_20261016 --responses kg_build/openai_sol_v2_20261016/responses --max-new 7
python -m imaks_kg.kg.build --predictions kg_build/openai_sol_v2_20261016/llm_predictions.jsonl --output kg_build/openai_sol_v2_20261016/graph
```

저장 응답은 재사용된다. 중단된 요청에 attempt 기록만 있고 응답이 없다면 비용/응답 상태를 확인하기 전 재호출을 차단한다. 이미 고정한 실험을 바꾸려면 다른 실험 디렉터리를 사용한다.

## 팀 기준 재채점

보고된 결과의 재현에는 원문·전처리 외에 다음 고정 자료가 필요하다(모두 로컬 보존):

- `kg_build/openai_sol_v2_20261016/llm_predictions.jsonl`
- `kg_build/openai_sol_v2_20261016/responses/requests/`, `responses/raw/`
- `evaluation/openai_sol_v2_20261016/colab_results/metrics.json` — 행렬과 예측/정답의 연결 해시 검증용. 그 파일의 과거 점수를 팀 주 점수로 재사용하지 않는다.
- 같은 폴더의 `similarities.npy` — SOP 예측 95개 × 정답 86개 순서의 전체 코사인 행렬.

```powershell
python -m imaks_kg.eval.team_rules --run openai_sol_v2_20261016 --definition docs/eval_definition_F1_content.md
```

클래스는 매칭에서 제외한다. 동일 문서의 cosine≥0.6 쌍에 대해 유효 매칭 수를 먼저 최대화하고 유효 유사도 합으로 동률을 해소한다. 결과는 `evaluation/openai_sol_v2_20261016/team_definition/`에 저장된다. 집계만 공유하고 `matches_private.json`은 공유하지 않는다.

새 예측을 평가하려면 같은 revision의 SBERT를 갖춘 클라우드 환경에서 새로운 전체 행렬과 해시 메타데이터를 생성해야 한다. 이 저장소의 공개 집계만으로 새 임베딩이나 고정 예측을 복구할 수는 없다.

## 테스트

```powershell
python -m unittest discover -s tests -p test_api_extraction.py
python -m unittest discover -s tests -p test_team_rules.py
```

첫 테스트는 식별자 정규화 시 원문 내용 보존과 충돌 거부를 검사한다.
두 번째는 Hungarian 완전탐색 대조, 유효 매칭 수 우선, 무효 쌍 유사도 배제, 문서 제한을 검사한다.
