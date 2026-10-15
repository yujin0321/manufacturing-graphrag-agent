# 성호: iMAKS 전처리·Ontology v1·SHACL

## 10/14 후속 작업 — KG 구축·부분 LLM 추출 평가

- [실행 안내·현재 상태](docs/README_kg_progress_seongho.md)
- [회의 보고서](reports/kg_progress_seongho_2026-10-14.md)
- [프로젝트 맥락](CLAUDE.md), [날짜별 활동 기록](work_log.md)
- [프롬프트·응답 스키마·추출 설계](llm_extraction_design/README.md)

지훈 안을 기반으로 실제 LLM 추출56개를 고정하고 SOP 예측50개를 평가했다.
전체86건 내용 F1 66.18%, 처리한 SOP59건 기준82.57%, 분류까지 일치해야 하는 전체 F1 44.12%이다.
검증된54개를 반영한 KG는1,654트리플이다. 미처리 SOP-002 지식은 별도 표 변환27개로 보충해4,121트리플까지 생성·SHACL 검증했다.
보충 규칙을 LLM 점수에 섞지 않았다. 전체 LLM 문서 추출, 사람 검토, Neo4j 실적재는 미완료이다.
팀원 제출처럼 코드·집계·맥락/활동 기록을 공개하고, 키·원본·개별 결과는 로컬에 보관한다.

## 아래는 첫 주차 개인 제출 기록

10/5 실행한 개인 과제 및 10/7 회의 정리. 팀 확정 설계가 아닌 개인 초안이다.

## 먼저 볼 파일

- [수행 내용·재실행 방법](submission/README.md)
- [실행된 노트북](submission/01_data_check.ipynb)
- [온톨로지 설계안](submission/ontology_v1.md)
- [데이터 점검 결과](submission/reports/findings.md)
- [SHACL 검증 결과](submission/reports/shacl_summary.csv)
- [팀원 비교표](work_records/2026-10-07/팀원별_공통점_차이점.md)

## 수행 범위

211,200행·22센서 점검, 원래 측정값 보존, 입력/정답 분리, PDF7개·10페이지·표24개 추출. 클래스7개·관계7개 설계, SHACL9사례 기대 결과 일치. 노트북8개 코드 셀 실행 완료.

탐지 모델·전체 LLM 추출·GraphRAG는 미실행. 예제 이벤트와 규칙은 구조 검증용이다. 실제 보고서와 노트북 출력은 포함하지만 원본 데이터·대용량 파생 CSV·가상환경은 Git에 넣지 않았다. 원본 ZIP을 내려받고 `submission/prepare.py`, `submission/validate_graph.py`를 실행하면 파생 결과를 재생성할 수 있다.

## 날짜별 기록

`work_records`는 대화 날짜별 요약이다. 9/23·9/30 논의 기록은 10/7에 소급 작성했다. 실제 구현 파일은 중복 저장하지 않고 `submission`에 둔다. 팀원 제공 원문은 개인의 구현 산출물이 아니므로 이 브랜치에 복사하지 않았다.
