# A·B·C 및 86규칙 평가 최종 설명서 안내

2026-10-14 GPT-6.1 Sol 자동 추출 및 첫 정량 평가 완료.

상세 팀 공유본: [abc_gpt61_sol_full_handoff.md](abc_gpt61_sol_full_handoff.md)
집계 결과: [gpt61_sol_first_evaluation.md](gpt61_sol_first_evaluation.md)
GPT 연결: [gpt61_sol_setup.md](gpt61_sol_setup.md)

A: Station 9, Sensor 22, hasSensor 22, feedsInto 3.
B: Document 7, MaintenanceRule 8, ThresholdRule 22.
C: 60/60청크 성공, 후보 80건, B 재확인 8, 새 규칙 72, 검증 거부·재시도 0건.
검토 전 합본 4,698트리플, SHACL 적합.

사용자 제공 두 평가 정의서에 따라 GPT 원본 F1 0.590361, B+C pipeline F1 0.648936(TP 61, FP 41, FN 25).
개별 예측·정답 매칭은 로컬 전용이다. 사람의 1·2차 검토와 검토 후 최종 KG 확정은 남아 있다.
중복/세분화 조합 검사 관찰과 미실행 보조 분석은 상세 인계서에 명시했다.
