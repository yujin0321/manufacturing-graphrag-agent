# GPT-6.1 Sol 추출 연결 구현

2026-10-14. 기본 공급자 openai, 모델 gpt-6.1-sol. Gemini는 CLI 선택과 기본 실행 경로에서 제거했다. 기존 Gemini 어댑터 파일과 과거 실행 기록은 이력 확인용으로 보존한다. Anthropic은 명시 선택 시에만 사용하며 자동 전환은 없다.

## 호출과 설정

OpenAI Responses API를 표준 HTTP로 호출한다. 추가 SDK 설치 없이 요청마다 실제 전송 1회만 수행한다. JSON Schema strict 출력, reasoning.effort low, max_output_tokens 16000(추론 포함), service_tier default, store false. temperature/top_p/seed는 보내지 않는다.

OPENAI_API_KEY는 환경변수 우선, 없으면 저장소 루트 .env의 해당 항목만 읽는다. 실제 키를 코드·요청 파일에 넣지 않는다. 원래 외부 전송 범위인 SOP-001~004와 imaks_data/rules/ 경로를 유지한다.

401/403은 인증 오류, insufficient_quota는 결제 오류로 전체 중단한다. 429 속도 제한·503만 기존 시도 상한 안에서 재시도한다. 타임아웃·연결 오류·500/504는 처리 및 과금 여부가 불명확하므로 자동 재시도 없이 중단한다. 원본 응답은 해석 전에 저장한다. 미완료·거부·잘못된 JSON은 재호출하지 않는다. 실제 응답 모델이 지정 모델 또는 -NNN 버전 접미사와 다르면 중단한다.

기존 예시 확정, 입력 해시, 호출 상한, 프로세스 잠금, 시도 장부, 승인 상태, 이어하기 검사를 사용한다. Gemini 실행의 승인·응답은 공급자와 모델이 달라 GPT 실행에 재사용할 수 없다.

## 비용

2026-10-14 공식 표준 단가: 입력 $2/100만 토큰, 출력·추론 $10/100만 토큰. 캐시 할인은 승인 상한 계산에 적용하지 않는다. 입력 추정이 요청당 272K를 넘으면 장문 요금으로 실행하지 않고 분할 필요 오류를 낸다. 글자 수 추정은 실제 토큰 수나 청구액을 보장하지 않는다.

## 실행

PowerShell에서 저장소 루트 기준:
```powershell
$env:PYTHONPATH='src'
# 호출 없이 비용 추정 및 승인 ID 생성
.venv/Scripts/python.exe -m imaks_kg.extract.run --dry-run --chunk 'SOP-001:p1:text1'
# API 키 등록 후, 출력된 승인 ID를 넣어 별도 GPT 실행 시작
.venv/Scripts/python.exe -m imaks_kg.extract.run --execute --chunk 'SOP-001:p1:text1' --approve <ESTIMATE_ID> --run-id gpt61-sol-smoke
```
전체 추출은 --chunk를 생략하여 새 dry-run/승인 ID를 만든다. 첫 시험 후 실제 usage와 결과를 확인한다. 키를 채팅·Git에 올리지 않는다.

## 검증 범위

새 어댑터 모의 테스트 12개 통과: 요청 스키마, 모델 고정, 거부·잘림 처리, 토큰 사용량, 인증·결제·속도·타임아웃 분류, 재시도, 헤더, 키 마스킹, 비용, 입력 범위, 설정 해시. 실제 유료 API 호출과 모델 접근 권한·스키마 수용 여부는 아직 시험하지 않았다.

근거: https://developers.openai.com/api/docs/models/gpt-6.1-sol 및 https://developers.openai.com/api/docs/guides/structured-outputs


추가 검증: 기존 오류 처리 회귀 테스트 20개 통과(신규 12개와 합계 32개). 실제 입력 SOP-001:p1:text1 dry-run 완료, 생성 호출 0회. 모의 Responses 응답을 실제 추출 CLI에 연결해 저장·검증·병합·검토 양식 생성 경로 확인. 실제 API 접근 권한과 과금 실행은 미검증.
