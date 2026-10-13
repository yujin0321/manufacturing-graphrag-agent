# 상태 및 다음 작업

2026-10-13 기준.

## 완료

- 문서 전체 LLM 추출의 원자화·출처·inventory 연결 정책 정리
- Responses API Structured Outputs용 규칙/coverage JSON Schema 작성
- source-only 입력 9개 파일 SHA-256 검증 및 단위별 text 해시 검증
- 네트워크 없는 요청 JSON 준비 코드
- 합성 데이터 테스트 5개 통과: 원문 보존/내장 prompt 제외, 입력 변조 차단, manifest 경로 삽입 차단, 중복 unit 차단, 잘못된 모델/출력 한도 차단
- 실제 SOP-001 전체 문서를 사용한 오프라인 요청 생성 성공. 이 과정에서 9개 입력 파일 해시를 검증함. 모델 값은 오프라인용 placeholder이며 모델 가용성 검증이 아님.

초기 테스트 실행은 Windows 임시 폴더 권한으로 실패했고, TEMP/TMP를 쓰기 가능한 작업 공간 임시 폴더로 설정한 재실행에서 5개 모두 통과했다. 실제 원문과 생성 요청은 커밋하지 않는다.

## 보류 / 미구현

- OpenAI API transport와 인증, 크레딧/권한 확인
- API status/refusal/incomplete 및 오류 종류별 처리
- API 원응답 불변 저장과 요청/응답 모델·사용량 로그
- API 응답에 대한 의미/인용/inventory/coverage 검증기
- 검토본/병합 JSONL/출력 해시 생성기
- 실제 API smoke test, 7개 문서 API 실행, 성능 평가

## 이후 순서

1. API 사용을 재개할 때 프로젝트 크레딧·권한과 모델, 호출 예산을 확정한다.
2. DESIGN.md의 transport·오류 처리·응답 저장·검증 요구사항을 구현한다. 키는 환경변수로 주입한다.
3. 문서 1개로 실호출하여 완료 상태, 정확 인용, coverage, 원응답 저장을 점검한다.
4. 그 뒤 7개 문서로 확장하고 문서별 원응답 및 검토본을 고정한다.
5. 사람 검토는 별도 기록하며, 승인된 정답 평가 절차가 생긴 경우에만 평가한다.

현재 패키지는 학습된 모델이나 API 추출 성능 결과물이 아니다. 추출 건수를 성공 기준으로 삼지 않는다.


## 2026-10-14 후속 작업

API 실험 보류는 유지한다. 별도 `imaks_kg.kg.build` 모듈로 기존 대화의 고정 추출을 Rule·Document RDF로 승격하고 SHACL 검증했다. `imaks_kg.evaluation.offline`로 정답 86건에 대한 진단 대조를 수행했다. 이는 API 응답 검증기나 SBERT F1_content 완성을 의미하지 않는다. [후속 보고서](../reports/kg_followup_2026-10-14.md) 참조.
