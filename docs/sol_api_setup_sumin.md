# GPT-6.1 Sol 연결·실행 안내

## 지금 필요한 순서

방향 검토는 `direction_review_sumin.md`에 있다. 결제 전에도 코드 준비와 합성 데이터 검증은 가능하다. 아래 실제 추출 단계부터 API 키와 사용 가능한 결제가 필요하다. 모델 결과는 실제 API 응답을 얻은 뒤에만 산출한다.

1. [API Billing](https://platform.openai.com/settings/organization/billing/overview)에서 결제 수단과 사용 가능 잔액을 준비한다. 구매 금액·자동 충전 선택은 계정 화면에서 사용자가 결정한다.
2. [API Keys](https://platform.openai.com/api-keys)에서 프로젝트용 비밀 키를 발급한다.
3. 프로젝트 루트 `.env`의 `OPENAI_API_KEY=` 뒤에 키를 저장한다. `.env`는 Git 제외이며 키를 채팅·소스·보고서에 붙이지 않는다. 예시 `.env.example`에는 키가 없다.

```dotenv
OPENAI_API_KEY=발급받은_키를_로컬에서_입력
OPENAI_MODEL=gpt-6.1-sol
```

이번 실험의 모델은 코드에서 `gpt-6.1-sol`로 고정한다. 다른 모델로 자동 전환하지 않는다. `.env`는 python-dotenv로 읽으며 이미 설정된 환경변수를 덮어쓰지 않는다.

## 실행

실제 첫 실행 경로는 `sumin-sol-v1-live`다. `sumin-sol-v1`은 API 호출 전 준비본으로 보존했다. 아래 평가 출력 폴더는 새 평가 때마다 비어 있어야 한다. 이미 완료된 실행은 결과 파일을 읽고, 재실행이 필요하면 새 평가 경로를 사용한다.

아래 명령은 저장소 루트에서 실행한다. Mac 로컬 가상환경은 `.venv/bin/python`이다. Windows에서는 해당 Python 실행 경로와 `PYTHONPATH` 설정법을 바꾼다.

```bash
# API 호출 없이 입력·프롬프트·스키마 준비 및 고정
PYTHONPATH=src .venv/bin/python -m imaks_kg.kg_build.sol_extract --out kg_build/sumin-sol-v1-live --dry-run

# 가장 작은 데이터시트부터 실제 연결 확인 (이 응답은 전체 실행에서 재사용)
PYTHONPATH=src .venv/bin/python -m imaks_kg.kg_build.sol_extract --out kg_build/sumin-sol-v1-live --documents DS-ELEC-3300

# 7개 문서 전체 추출. 완료한 문서는 검증 후 캐시 사용
PYTHONPATH=src .venv/bin/python -m imaks_kg.kg_build.sol_extract --out kg_build/sumin-sol-v1-live

# 검증을 통과한 규칙으로 후보 KG와 SHACL 보고 생성
PYTHONPATH=src .venv/bin/python -m imaks_kg.kg_build.rdf_export --build-dir kg_build/sumin-sol-v1-live
PYTHONPATH=src .venv/bin/python -m imaks_kg.kg_build.shacl_validate --data kg_build/sumin-sol-v1-live/kg.ttl --report kg_build/sumin-sol-v1-live/shacl_report.txt
PYTHONPATH=src .venv/bin/python -m imaks_kg.kg_build.source_audit --build-dir kg_build/sumin-sol-v1-live

# 자동 예측 전체를 첨부 MD 기준으로 평가 (원본 데이터 위치를 명시)
PYTHONPATH=src HF_HOME=.cache/huggingface HF_HUB_OFFLINE=1 .venv/bin/python -m imaks_kg.eval.sol_evaluate \
  --build-dir kg_build/sumin-sol-v1-live \
  --gold ../iMAKS_dataset/kg_seed/ground_truth.csv \
  --out evaluation/sumin-sol-v1-live
```

평가기는 원본 86행과 SOP 문서 범위를 검사한다. 임베딩 지정 revision은 이번 로컬 실행에서 `.cache/huggingface`에 다운로드·확인했다. 다른 환경에서는 최초 다운로드 후 오프라인 모드를 사용한다. 오프라인 합성 테스트의 통과는 실제 모델 다운로드·임베딩·API 호출 성공과 구분한다.

## 완료된 실행의 추가 진단

원문 감사 후 아래 명령은 원본 정답과 원문 표의 수치 차이만 진단한다. 예측과 점수를 수정하지 않는다.

```bash
PYTHONPATH=src .venv/bin/python -m imaks_kg.eval.source_diagnostics --build-dir kg_build/sumin-sol-v1-live --evaluation-dir evaluation/sumin-sol-v1-live --gold ../iMAKS_dataset/kg_seed/ground_truth.csv
```

## 출력

- `kg_build/sumin-sol-v1-live/requests/`: API에 보낼 내용. 정답·seed KG 없음.
- `responses/`: 원본 응답·호출 시도·수신 시각·요청/응답 해시. 키 없음.
- `predictions.jsonl`: 자동 평가 대상 전체. 원문 검증 플래그가 있다고 몰래 제외하지 않음.
- `rules_extracted.jsonl`: 출처 검증 통과 후보 KG용 규칙. 자동 평가 파일과 분리.
- `validation.json`: 원문 인용·엔티티 검사와 단위별 coverage 누락 진단.
- `extraction_summary.json`: 완료 여부, 모델·토큰 사용량·해시·예측 건수.
- `evaluation/sumin-sol-v1-live/pre_evaluation_lock.json`: 정답 읽기 전 두 정의서·예측·모델·프롬프트·실행 환경 고정.
- `evaluation/sumin-sol-v1-live/report.md`: 실제 결과 보고서. API 실행 전에는 생성하지 않음.
- `metrics.json`, `document_scores.json`: 집계.
- `matches.local.json`, `embeddings_*.npy`: 로컬 재현·감사용. Git에 올리지 않음.

중단된 요청은 자동 재전송하지 않는다. 오류 유형을 확인하고 과금 여부가 불명확한 timeout을 무조건 재시도하지 않는다. 완료 응답은 재사용하며 요청/응답이 변경되면 중단한다. 새 프롬프트 실험은 새 출력 경로로 만들고 기존 결과를 보존한다.

## 평가 코드의 출처와 기준

`eval/team_protocol/`의 핵심 코드는 `origin/지훈` 커밋 `d291373`에서 재사용했다. 수민 실행 어댑터는 두 정의서 해시, 실제 모델 검증, 0건 추출 문서까지 포함한 처리 범위, 예측 불변 검사, 문장 형식 민감도, 집계 보고서 생성을 연결한다. 임계 비교는 정의서대로 정확히 `cosine >= 0.6`이며 이전 코어의 작은 허용 오차를 제거했다.

새 평가 기준을 만든 것이 아니다. 사용자가 지정한 두 MD의 SBERT·Hungarian·분모 정의를 실행하는 코드다. 기존 `eval.metrics`는 어휘 대리 지표이며 이제 `f1_lexical_proxy`로 표기한다. 과거 저장된 결과 파일을 소급 수정하지 않는다.

## 공식 확인 자료

- [API 시작 안내](https://developers.openai.com/api/docs/quickstart)
- [GPT-6.1 Sol 모델](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

확인일: 2026-10-16. 실제 호출은 Responses API, `reasoning.effort=low`, `max_output_tokens=24000`, `store=false`, JSON Schema strict를 사용한다. temperature는 전송하지 않는다. 사용량은 실제 응답에 기록하며 결제 대시보드 청구액과 별도로 확인한다.
