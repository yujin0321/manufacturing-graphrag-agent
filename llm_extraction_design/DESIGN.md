# 온톨로지 기반 추출 설계

## 목적

문서의 명시된 지식을 Rule 노드, appliesToSensor/actionTarget 관계, Document/Provenance 연결로 확장한다.
LLM이 온톨로지에 없는 새 관계 종류나 문서에 없는 인과관계를 자동 확정하지 않게 한다.

## 입력

SOP4+데이터시트3의 전처리 청크·정규화된 표, Station/Sensor ID 허용 목록.
ground_truth.csv와 seed Maintenance 조치 문구는 요청에 제공하지 않는다.
문서 전체를 한 요청에 넣어 표의 제목·페이지 연속 문맥을 함께 보게 한다.

## 출력

Rule 네 분류, printed_rule_id, condition, action, severity, sensors, action_targets,
여러 evidence 객체(chunk_id, 원문 인용, supports, 표 ID 및 0기준 행/열).
없는 조치/등급은 빈 문자열, 없는 인쇄 ID는 null. 대상 식별자는 허용 목록 안에서만 선택한다.
파일 해시·문자 위치는 코드가 계산하며 LLM이 만들어내지 않는다.

## 검증과 보존

JSON 스키마로 형식을 제한하고, 문서/센서 참조·실제 인용 존재·표 좌표를 코드로 검증한다.
실제 원문 인용의 존재는 함의/수치/인과의 정확성을 증명하지 않는다. 사람 의미 검토가 필요하다.
원본 응답·자동 예측은 해시로 고정한다. 잘못된 근거도 점수에서는 숨기지 않고 KG 반영에서 제외한다.
서버 과부하는 제한 재시도, 완료 문서는 캐시로 재사용. 키는 공식 Google API 헤더로만 전송하며 로컬 .env에서 읽는다.

## 실험 구분

3.8 Flash 및 3.6 Flash 연결/부분 실험과 3.1 Flash-Lite 공개 스냅샷을 혼합하지 않는다.
미처리 SOP-002의 표 기반 보충은 별도 결정적 방법이며 LLM 점수에 포함하지 않는다.
