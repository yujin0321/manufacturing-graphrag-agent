"""C: SOP 문서에서 LLM으로 규칙을 추출한다(④). 실제 호출은 run.py --execute에서만 하고, 테스트는 가짜 응답만 쓴다.

모듈
- inputs.py: 입력 청크 선택 + 해시 사슬 검사(harness/preprocess_lock.json)
- prompt.py, prompts/v1/: Role/Task/Example 3단 프롬프트(버전 파일)
- schema.py: 구조화 출력 JSON 스키마와 pydantic 모델
- llm.py: Anthropic SDK 호출(주입식 클라이언트, FakeClient)
- run.py: 실행 CLI(--dry-run, --fake, --execute)
- validate.py: 응답 자동 검사(스키마, 인용 원문 일치, ID 목록) + Provenance 좌표 계산
- merge.py: B(MAINT·임계값) 규칙과 병합
- conflicts.py: 데이터시트 vs SOP-002 수치 충돌 후보(결정적, LLM 없음)
- review.py: 2단계 사람 검토 CSV
- to_rdf.py: 최종 결과 → kg_build/rules_llm.ttl
"""
