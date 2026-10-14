# A·B·C 및 평가 진행 상태 — 중간 업로드

사용자 요청으로 완료한 코드와 검증 기록을 2nd-yujin 브랜치에 먼저 공유한다. 전체 작업 완료 보고서가 아니다.

| 파트 | 구현 방법·모델 | 확인 결과 | 남은 작업 |
|---|---|---|---|
| A | CSV → RDF, Python·rdflib, 모델 없음 | Station 9, Sensor 22, seed 482트리플; 기존 독립 검증 PASS | 이번 범위 완료 |
| B | 표 구조의 결정적 변환, 모델 없음 | Document 7, MaintenanceRule 8, ThresholdRule 22; 2,684트리플; A+B SHACL PASS | 이번 범위 완료 |
| C 코드 | Gemini 어댑터, JSON 스키마, 원문 검사, B 병합, 1·2차 검토, RDF 출력 | 전체 테스트 281개 PASS; 예시 확정 후 관련 12개 PASS; 원본 불변·누수 PASS | 실제 전체 추출·사람 검토·최종 그래프 |
| C 실제 시험 | gemini-3.8-flash, temperature 0, seed 20261012, max output 8192 | 4청크 시험에서 후보 11건, 거부 0, B 병합 8, 새 규칙 3; 503 후 이어하기 동작 확인 | 전체 60청크 중 나머지 처리 중 |
| 평가 코드 | all-MiniLM-L6-v2, cosine, Hungarian, θ=0.6 | 핵심 테스트 4개 PASS; B의 30규칙 변환 점검 PASS; 인코더 오프라인 점검 PASS | 정답 86건 실측 평가 미실행 |

평가 모델 revision: 1110a243fdf4706b3f48f1d95db1a4f5529b4d41. 인코더는 CPU·오프라인에서 384차원 벡터를 만든다.

첫 실제 시험은 7.5초 간격이었고, 503 과부하 뒤 소규모 재시험과 전체 실행은 30초 간격을 사용한다. 성공한 4청크를 재사용하고 남은 56청크의 승인 상한은 66시도다. 모델 자동 전환과 유료 전환은 하지 않는다.

F1_content·Precision·Recall·Coverage는 아직 산출되지 않았다. 평가 코드의 정답 CSV 열 이름만 확인했으며 정답 규칙 내용은 아직 평가하지 않았다. 원문 검토 제안을 먼저 고정하고, 사용자 승인 뒤 최종 반영한다.

API 키(.env), 원본 데이터, 전처리·KG·실행·평가 결과, 모델 가중치, 가상환경은 git 무시 대상이다. 해시 장부에는 파일명·해시·상태만 들어간다.

최종 설명서 reports/final_abc_evaluation_impl.md는 현재 초안이며, 완료 후 실제 결과를 채운다. eval/README.md와 evaluation_protocol.md에 재현 방법과 계산 기준이 있다.

상태 기록 시각(UTC): 2026-10-14T07:42:42.021271+00:00. 이 시점의 확보 청크: 10/60.


## Actual execution interruption
The gemini-3.8-flash run hit FATAL_QUOTA (429, GenerateRequestsPerDayPerProjectPerModel-FreeTier) at 2026-10-14 07:48:57 UTC. Server RetryInfo requested approximately 16 hours. All successful responses and approvals are preserved. Evaluation and final review are not complete. Model switch requires explicit user authorization; no paid fallback.


## GPT-6.1 Sol 완료 기록 (2026-10-14)

위 Gemini 중단 기록은 과거 이력이다. 사용자 승인 후 GPT-6.1 Sol로 새 전체 실행을 완료했다. 60청크 성공, 후보 80, 재시도·검증 거부 0. B+C pipeline F1 0.648936. 자동 첫 평가 완료, 사람 검토는 대기. 상세: reports/abc_gpt61_sol_full_handoff.md.
