# 성호 LLM 추출 설계

- [프롬프트](extraction_prompt.txt)
- [응답 JSON 스키마](response_schema.json)
- [설계 설명](DESIGN.md)
- [실행 상태](STATUS.md)

실제 실행 코드는 `src/imaks_kg/stage3/extract.py`, `gemini.py`, `local_config.py`에 있다.
프롬프트/스키마 파일은 실행 코드의 상수에서 내보낸 동일 내용이다. 설계 변경 시 함께 갱신한다.
원본 응답·문서·정답은 로컬에 보관하며 이 폴더에는 포함하지 않는다.
