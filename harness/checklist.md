# 단계별 검증 체크리스트

verifier는 이 파일의 항목으로만 판정한다. 단계가 늘면 항목을 추가한다.
각 항목은 "파일을 열거나 명령을 돌려서 PASS/FAIL을 가를 수 있게" 쓴다.

## 공통 (모든 단계)
- [ ] `check_raw_unchanged.py`가 PASS (imaks_data 원본 불변)
- [ ] `check_leakage.py`가 PASS (금지 컬럼 없음)
- [ ] 코드에 절대 경로(`C:\`, `/Users/`, `/home/`)가 없다
- [ ] 큰 산출물·원본 데이터가 git 추적 대상이 아니다 (`git ls-files` 확인)
- [ ] 이상값을 삭제·보간·평활화한 코드가 없다 (파생 값은 별도 컬럼)
- [ ] API 키·토큰이 저장소 코드, 설정, 로그, 보고서, 산출물 어디에도 없다 (`check_secrets.py`를 한 번 실행하고 마지막 요약 줄(검사/건너뜀/발견)과 발견 시 파일:줄만 보고한다. 호출 기록 파일을 통째로 읽지 않는다)
- [ ] 검증 보고서는 항목당 근거를 3줄 이내로 쓰고 파일 전체를 붙여 넣지 않으며, 단위 테스트는 마지막 요약 줄(`Ran N tests`)만 보고한다 (실패 시에만 상세 확인)

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
- [ ] `check_leakage.py` 기본 폴더가 PASS이고, 예외 상수는 `TEXT_EXEMPT_PREFIXES` 1개뿐이고, 포함된 폴더는 `preprocessed/documents/`와 `kg_build/extraction/` 둘뿐이다
- [ ] 단위 테스트(`unittest discover -s tests`)가 전부 통과한다

## ③ 인스턴스 생성
- [ ] 노드 수·엣지 수가 nodes.csv(115)/edges.csv(341)와 일치하거나 차이 사유가 reports에 있다
- [ ] 인스턴스가 `run_shacl.py`로 적합 판정을 받는다
- [ ] 원본 ID가 보존되어 원본 행으로 역추적된다
- [ ] 적재 제외 대상(AnomalyEvent, Person, SafetyEvent, Zone, System, authorized_for 등)이 TTL과 CSV에 없다
- [ ] 값(문구 포함)을 임의로 통일하지 않았고, 원본과 문서가 다른 항목은 두 쪽을 모두 매핑표에 남겼다
- [ ] 노드와 엣지 모두 출처(파일명과 원본 행 식별자)를 추적할 수 있다 (엣지는 TTL이든 CSV든 위치를 정해 보고서에 명시한다)
- [ ] (③ 한정) 같은 입력으로 다시 실행하면 같은 결과가 나온다 (CSV 바이트 동일, TTL은 트리플 집합 동일). ④·⑤에서는 LLM을 다시 호출하지 않는다
- [ ] 트리플 단위 출처 장부(`triple_sources.jsonl`)가 `instances.ttl`의 모든 트리플을 빠짐없이 덮고, 요약(`summary.json`)에 `ledgerComplete: true`가 있다
- [ ] Document의 `sourceSha256`이 실제 PDF를 다시 읽어 계산한 SHA-256과 같다 (manifest 값을 그대로 믿지 않는다)

## ④ LLM 추출
- [ ] 프롬프트가 Role/Task/Example 3단이다
- [ ] 모든 트리플에 문서 ID, 페이지, 문자 위치(표는 좌표), 원문 해시가 있고, 해시가 실제 원문과 일치한다
- [ ] 데이터시트와 SOP-002 수치 충돌이 출처와 함께 둘 다 기록돼 있다
- [ ] ground_truth.csv가 프롬프트·Example·청킹·추출 입력에 쓰이지 않았다 (코드에 파일명이 없고, 프롬프트와 Example 문구가 정답 규칙 문장과 겹치지 않는다. 겹침은 `check_gt_overlap.py`로 계산해 마지막 요약 줄과 기준 초과 (파일, 행번호, 비율)만 보고한다. 종료 코드 2(정답 파일 없음)는 미확인으로 적는다. 검증자는 이 스크립트 실행에서만 정답 파일을 읽고, 직접 열어 규칙 문장을 보지 않으며 보고서에 옮겨 적지 않는다)
- [ ] 공급자, 모델명, 키 환경변수 이름이 설정 파일에서 바뀌고 코드에 모델명 기본값이 없다 (1순위 Gemini, 2순위 OpenAI, `GEMINI_API_KEY`, `OPENAI_API_KEY`)
- [ ] fallback(재시도 → 같은 공급자 다른 모델 → 다른 공급자 → 실패 기록 후 건너뜀)이 mock 테스트로 확인된다 (API를 호출하지 않는다)
- [ ] 호출마다 요청, 응답, 실제로 쓴 모델, 시각, 재시도 횟수, 토큰 사용량이 파일로 남고, 검증은 이 기록을 근거로 한다 (LLM을 다시 호출하지 않는다)
- [ ] 같은 청크·프롬프트·모델이면 저장된 응답을 재사용하는 캐시가 있다
- [ ] 전체 실행 전에 작은 문서 1개 또는 청크 3~5개 분량으로 스모크 테스트를 한 기록이 있다
- [ ] 프롬프트 Example은 가상 이름·수치·문장이며, 정답 고유 문구와 SOP·데이터시트 원문 모두와 5단어 겹침이 0건이고, 데이터셋의 ID·이름·수치+단위 조합을 쓰지 않았다. Example 파일 해시가 요청 기록과 같다
- [ ] 추출 결과의 Rule 클래스가 `OperationalRule`, `ThresholdRule`, `MaintenanceRule`, `AccessRule` 4분류 중 하나이고 Task 클래스가 없다
- [ ] 추출 결과가 `run_shacl.py`로 S7·S8을 포함해 적합 판정을 받는다
- [ ] 사람 검토 2단계의 입력, 수정 내역, 최종 채택 기록이 파일로 남아 있다
- [ ] fallback으로 처리된 결과는 모델별로 구분돼 기록돼 있다

## ⑤ 검증 (평가 코드)
- [ ] 주 지표가 F1_content(Hungarian + SBERT, θ=0.6)이고 F1_strict를 주 지표로 쓰지 않았다
- [ ] 결과 수치를 보고서의 계산 과정으로 재현할 수 있다
- [ ] 임베딩 모델명(all-MiniLM-L6-v2)과 라이브러리 버전이 기록돼 있고, 대조 쌍과 임계 통과 여부가 파일로 남아 있다
- [ ] `ground_truth.csv`를 읽는 코드는 평가 폴더(`src/imaks_kg/eval/`) 아래에만 있다 (`check_leakage.py`의 ground_truth 경고 0건)
- [ ] 보조 지표(Coverage, GT-0009 binary)와 MAINT-01~08 매핑표(seed ↔ SOP-003 ↔ 정답 파일)가 있다
- [ ] 첫 실행 점수가 기준선으로 고정돼 있고, 프롬프트 수정은 최대 2회이며 수정마다 이유와 그 근거(정답 내용이 아닌 오류 유형)가 `work_log.md`에 있다
- [ ] 점수 보고에 사용한 공급자·모델과 fallback 사용 여부가 명시돼 있다

## ⑥ 인과 후보 발굴
- [ ] 입력 컬럼 목록에 금지 컬럼이 없다
- [ ] 출력에 `hasLag`, `hasEvidence`, `likelihoodScore`가 있고 점수가 0~1이다
- [ ] 채택은 점수 0.6 이상, 이벤트당 상위 3개다
- [ ] 발굴 경로와 ⑦ 이후 AnomalyEvent 주입 경로가 코드에서 분리돼 있다
