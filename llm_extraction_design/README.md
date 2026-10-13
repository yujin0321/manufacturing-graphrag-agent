# iMAKS LLM 추출 API 설계

현재 상태: **설계 및 오프라인 요청 준비 구현 / 실제 API 연동·추출 테스트 미수행**.
사용자가 API 크레딧 부족을 보고하여, 유료 호출 없이 재개 가능한 설계를 준비했다. 계정 상태를 직접 조회한 결과는 아니다.

## 이번 패키지

- `DESIGN.md`: 처리 단계, 실패 처리, 추적 정보, 재개 조건
- `extraction_prompt.txt`: 문서 전체 규칙 추출 지시문
- `response_schema.json`: 규칙 및 원문 단위 coverage의 출력 계약
- `prepare_request.py`: 입력 해시를 검증하고 Responses API 요청 JSON만 로컬 생성
- `test_prepare_request.py`: 합성 문서로 실행하는 오프라인 테스트
- `STATUS.md`: 완료/미완료 및 다음 작업

Python 3.10 이상과 표준 라이브러리만 필요하다. 설치나 API 키 없이 테스트할 수 있다.

```powershell
python -m unittest discover -s . -p "test_*.py" -v
python prepare_request.py --input-dir "<source-only 폴더>" --document SOP-001 --model "<나중에 확정한 모델 ID>" --output-dir runs/example
```

두 번째 명령은 API를 호출하지 않는다. 생성된 요청에는 원문이 들어 있으므로 runs/는 Git에서 제외한다. 모델 ID는 필수 인수이며 기본 모델/가격을 가정하지 않는다. API 키를 읽거나 저장하는 코드도 없다.

## GitHub 반영 범위

이 디렉터리의 설계·코드·스키마만 커밋한다. 원문 문서, API 키, 계정 정보, 실행 요청/응답, 이전 추출 결과는 포함하지 않는다. 기존 대화에서 수행한 추출은 별도 방법의 산출물이며 API 성공 사례나 정답 데이터로 사용하지 않는다.

## 근거 문서

설계 확인일: 2026-10-13.
Responses API의 Structured Outputs는 `text.format`에 JSON Schema를 지정한다. strict 모드에서는 객체 속성을 required로 선언하고 선택적 값은 null로 표현할 수 있다. 스키마 준수만으로 인용과 의미 정확성이 보장되지는 않으므로 별도 검증이 필요하다.

- [OpenAI 공식 Structured Outputs 문서](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)

향후 실호출 전 선택 모델의 지원 여부와 요청 스키마를 공식 문서 및 실제 응답으로 확인해야 한다.
