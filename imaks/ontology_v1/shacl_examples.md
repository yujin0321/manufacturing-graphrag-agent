# SHACL 핵심 제약 5개와 통과·실패 예제

최소 제출물의 5개 제약 그룹을 SHACL Core와 SHACL-SPARQL로 구현한다. helper shape는 스테이션·문서 등의 내용을 검사하며 별도의 핵심 그룹으로 세지 않는다. RDF 파일별로 `im:InputData` 제어 노드와 프로필이 반드시 있어야 한다.

| ID | 검사 내용 | 통과 예제 | 실패 예제 | 예제 파일 |
|---|---|---|---|---|
| C1 | Sensor의 ID·타입·단위가 각각 하나, 소속 Station 하나, 타입/단위 대응 및 Station의 Zone/System 연결 | ST02 TMP, °C, ST02_SEALING 소속 | Sensor의 unit 누락 | examples/C1_pass.ttl, C1_fail.ttl |
| C2 | Observation의 Sensor·시각·유한 수치·단위가 있고 센서 단위와 일치 | TMP 관측 1,000,000°C도 형식과 단위가 맞으면 통과 | TMP 관측 단위를 A로 기록 | examples/C2_pass.ttl, C2_fail.ttl |
| C3 | Rule·Document 출처 메타데이터, 인용·조건·대응·추출 방식, 유효한 페이지 | 실제 SOP-001 p.1, 원문 인용, 대응 조치 | 2쪽 문서의 출처를 p.99로 기록 | examples/C3_pass.ttl, C3_fail.ttl |
| C4 | ThresholdRule의 임계값 5개가 유한 수치이며 순서·센서 단위 일치 | 165 < 175 < 185 < 195 < 210°C | critLo=200으로 바꿔 warnLo=175보다 크게 기록 | examples/C4_pass.ttl, C4_fail.ttl |
| C5 | 입력 프로필, 명시적 라벨/알람/GT 사건 차단, ML에서 문서·임계값 차단 | ml_metadata에 정적 구조만 존재 | gt_id=GT-0007을 입력 그래프에 추가 | examples/C5_pass.ttl, C5_fail.ttl |

C2는 이상 탐지 목적에 맞춰 **관측값의 정상 범위를 검사하지 않는다**. 1,000,000°C는 센서 오류/이상 판단 대상일 수 있지만 공통 원본을 삭제·보정하기 위한 SHACL 실패 조건이 아니다. NaN과 ±INF처럼 유효한 유한 관측값으로 계산할 수 없는 값은 별도로 거부한다.

C3는 문서 주소·형식이 유효한지 검사한다. 인용 내용의 정확성은 빌더의 원문·표·해시·lineage 검사로 확인한다. 범용 Rule은 센서를 반드시 갖지 않아도 되며, ThresholdRule에만 적용 센서가 필수다. 아직 출입 규칙 등 모든 문서를 구조화한 것은 아니다.

C5는 그래프 전체를 검사하므로 무관한 노드에 숨긴 quality나 alarm 필드도 검사한다. 자연어 이름용 `rdfs:label`은 허용한다. 명시적 필드 검사는 알려지지 않은 이름으로 재인코딩된 라벨이나 의미적 프록시의 완전한 차단을 보장하지 않는다.

## 실제 검증 결과

2026-10-06 기준, `verify_ontology_v1.py --record-date 2026-10-06`으로 다음을 실행한다.

- 생성한 입력 그래프 2개: 모두 SHACL 통과.
- 통과 예제 5개: 모두 통과.
- 실패 예제 5개: 모두 거부.
- 정상적인 rule_context를 ML 프로필로 바꾼 추가 예제: 거부.
- 질문별 SPARQL 조회 5개: 예상 센서·근거·대상·문서 결과 확인.

이 실행의 근거는 `validation/validation_results.json`, 각 `*_report.ttl`, `competency_answers.json`, 해시 manifest다. 엔진은 pySHACL 0.30.1·RDFLib 7.1.4이고 OWL 추론·원격 import·SHACL-JS·규칙 실행은 사용하지 않는다. OWL 어휘 선언과 SHACL 데이터 검증을 분리한다.

`test_ontology_v1.py`는 위 예제 외에도 제어 노드 삭제, 다중 스테이션 연결, 단위 불일치, 비어 있는 인용, 잘못된 문서 해시, 비정상 페이지 수, 비유한 관측/임계값, 우회 문서 텍스트, 숨긴 라벨, 원문 lineage를 확인한다. 결과는 `validation/unit_test_results.json`에 기록한다.
