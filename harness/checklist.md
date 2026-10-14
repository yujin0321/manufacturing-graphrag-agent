# 단계별 검증 체크리스트

verifier는 이 파일의 항목으로만 판정한다. 단계가 늘면 항목을 추가한다.
각 항목은 "파일을 열거나 명령을 돌려서 PASS/FAIL을 가를 수 있게" 쓴다.

## 공통 (모든 단계)
- [ ] `check_raw_unchanged.py`가 PASS (imaks_data 원본 불변)
- [ ] `check_leakage.py`가 PASS (금지 컬럼 없음)
- [ ] 코드에 절대 경로(`C:\`, `/Users/`, `/home/`)가 없다
- [ ] 큰 산출물·원본 데이터가 git 추적 대상이 아니다 (`git ls-files` 확인)
- [ ] 이상값을 삭제·보간·평활화한 코드가 없다 (파생 값은 별도 컬럼)

## ② 온톨로지·SHACL
- [ ] `ontology_v1/ontology.ttl`이 rdflib로 파싱된다
- [ ] 모든 클래스·관계에 Domain/Range가 있다
- [ ] `causallyAffects`는 Station→Station이고 `hasLag`, `hasEvidence`, `likelihoodScore`(0~1) 속성이 정의돼 있다
- [ ] Component→Station 매핑만 있고 부품 계층 클래스가 없다
- [ ] `shapes.ttl`이 파싱되고, 의도적 위반 예시 데이터에서 FAIL이 나온다
- [ ] 채택 필터(0.6 이상, 이벤트당 상위 3개)가 SHACL이 아니라 적재 스크립트에 있다

## 전처리 (센서·문서)
- [ ] `preprocessed/sensors/input/ts_input.csv` 헤더가 정확히 `timestamp, zone, station_id, sensor_id, sensor_type, value, unit` 7개이다
- [ ] `ts_input.csv`는 211,200행, 센서 22, 타임스탬프 9,600이고 (sensor_id, timestamp) 중복이 0이다
- [ ] `ts_input.csv`의 모든 행의 7개 값이 `imaks_data/sensors/timeseries_raw.csv`와 문자열로 같다(value 포함)
- [ ] `ts_input.csv`는 (sensor_id, timestamp) 순으로 정렬돼 있다
- [ ] 정답 컬럼과 품질 컬럼은 `evaluation/row_labels.csv`에만 있고 `preprocessed/` 안의 CSV 헤더·JSON 키에는 없다
- [ ] 임계값은 `preprocessed/sensors/rules/`에만 있고 `ts_input.csv`에는 없다
- [ ] 원본의 day·shift·batch_id는 `original_*` 이름의 컬럼으로만 보존돼 있고 원본과 값이 같다
- [ ] 임계값 파일(22행)의 수치가 SOP-002 표(`tables.jsonl`)와 센서별로 같다
- [ ] `doc_manifest.csv`는 7행이고 각 `file_sha256`이 실제 PDF의 SHA-256과 같다. 쪽 합계 10, 표 24개이다
- [ ] 모든 청크에 doc_id, page, 위치(char_start/char_end 또는 표 좌표 bbox), text_sha256, source_file_sha256이 있고 text_sha256이 text의 SHA-256과 같다
- [ ] SOP-001의 `RULE-ST02-04` 규칙이 1쪽의 한 청크 안에 온전히 들어 있다
- [ ] 글리프 치환은 Symbol/ZapfDingbats 폰트 문자에만 적용됐고(일반 글꼴의 "fi"는 그대로) 모든 치환이 `glyph_fixes.csv`에 기록돼 있다. 원문은 `text_raw`/`rows_raw`에 보존돼 있다
- [ ] 코드(`src/`)가 정답 규칙 파일(`ground_truth`)을 읽지 않는다
- [ ] `/preprocessed/`와 `/evaluation/`이 git 무시 대상이고 `src/`는 무시되지 않는다(`git check-ignore`)
- [ ] `check_leakage.py` 기본 폴더가 PASS이고, 예외 상수는 `TEXT_EXEMPT_PREFIXES`(문서 폴더) 1개뿐이다
- [ ] 단위 테스트(`unittest discover -s tests`)가 전부 통과한다

## ③ 인스턴스 생성
- [ ] 노드 수·엣지 수가 nodes.csv(115)/edges.csv(341)와 일치하거나 차이 사유가 reports에 있다
- [ ] 인스턴스가 `run_shacl.py`로 적합 판정을 받는다
- [ ] 원본 ID가 보존되어 원본 행으로 역추적된다

## ④ LLM 추출
- [ ] 프롬프트가 Role/Task/Example 3단이다
- [ ] 모든 트리플에 문서 ID, 페이지, 문자 위치, 원문 해시가 있다
- [ ] 데이터시트와 SOP-002 수치 충돌이 출처와 함께 둘 다 기록돼 있다
- [ ] ground_truth.csv가 프롬프트·청킹·추출 입력에 쓰이지 않았다

## ⑤ 검증 (평가 코드)
- [ ] 주 지표가 F1_content(Hungarian + SBERT, θ=0.6)이고 F1_strict를 주 지표로 쓰지 않았다
- [ ] 결과 수치를 보고서의 계산 과정으로 재현할 수 있다

## ⑥ 인과 후보 발굴
- [ ] 입력 컬럼 목록에 금지 컬럼이 없다
- [ ] 출력에 `hasLag`, `hasEvidence`, `likelihoodScore`가 있고 점수가 0~1이다
- [ ] 채택은 점수 0.6 이상, 이벤트당 상위 3개다
- [ ] 발굴 경로와 ⑦ 이후 AnomalyEvent 주입 경로가 코드에서 분리돼 있다
