"""센서 데이터 분석 결과 설명 Agent.

흐름: 센서 CSV 업로드 → 입력 검증·라벨 컬럼 제거(ingest) → 룰 엔진 실행·KG 오버레이(analysis)
→ 질문 분류(planner) → 도구 실행(tools) → 근거 기반 답변 생성·자기검증(agent).
UI는 service.AnalysisService만 호출한다.
"""
