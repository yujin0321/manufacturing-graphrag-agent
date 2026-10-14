# 평가 기준: 사용자 지정 두 문서

2026-10-14부터 docs/eval_definition_F1_content.md 및 docs/eval_definition_team_summary.md를 그대로 적용한다. 기존 총 코사인 최대화 방식은 폐기했다.

- 문장 condition + 공백 + action. ID·인용·클래스 제외.
- all-MiniLM-L6-v2 revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41. 정규화 코사인, 주 임계 0.6.
- 같은 문서 안 Hungarian. 유효 매칭 수 최대화 후 유효 쌍 유사도 합 최대화.
- 클래스 제한 없음. 매칭 뒤 분류 일치 F1·혼동표 별도.
- 주 보고는 SOP 예측 전체와 원본 정답 86건 전체. 미처리 문서는 FN. 데이터시트 예측은 범위 밖 개수만 보고.
- 모델별 분리, 예측 건수·세분화 비율·F1 상한·문서별 점수·0.5/0.7 민감도·센서 일치 보고.
- 예측과 두 정의서, 프롬프트·예시·스키마·실제 모델·모델 파일·라이브러리 해시를 고정한 뒤 평가 전 잠금 생성. 정답은 src/imaks_kg/eval/gold.py가 읽는다.
- C 원본 자동 예측은 검증 거부 여부와 무관하게 보존한다. 자동/검토본 별도. 분할 예측을 임의로 합치지 않는다.
- B 기준선과 B+C pipeline을 별도 계산. Pipeline에서는 추출 시 확정된 같은 문서·같은 인쇄 ID의 B 재확인만 원래 B 값으로 한 번 센다. B+C union도 중복 영향 확인용으로 기록.
- 이전 정답 노출 이력을 명시한다. 첫 결과는 개발 평가이며 독립 holdout으로 주장하지 않는다.
- 개별 예측·매칭 목록은 extraction/evaluation 아래 로컬 보존하고 Git에 올리지 않는다. 집계 보고서는 reports에 기록한다.

실행: evaluation/.venv/Scripts/python.exe -B eval/evaluate_pipeline.py --run-dir extraction/runs/<RUN_ID> --out-dir extraction/evaluation/<NEW_ID>
