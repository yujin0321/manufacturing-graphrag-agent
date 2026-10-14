# F1_content 평가기 검증 보고서
- 판정: PASS
- 범위: src/imaks_kg/eval/, tests/test_eval_f1.py. 기준은 docs/eval_definition_F1_content.md와 harness/checklist.md의 공통 절 및 ⑤ 평가 도구 항목. 결과 점수는 판정에서 제외했다.
- 시험은 scratchpad의 가짜 정답 CSV, 가짜 예측 JSONL, 가짜 임베더로 했다. 실제 정답은 `describe-gold`로 헤더와 행 수만 봤다(86행, SOP-001 29 / SOP-002 27 / SOP-003 11 / SOP-004 19, DS 행 없음).

## 항목별 결과
| 항목 | 결과 | 근거 |
|---|---|---|
| 3장(a) 같은 문서 안에서만 매칭 | PASS | SOP-001 예측과 SOP-002 정답이 코사인 1.0이어도 짝짓지 않았다. 미매칭 예측 1건으로 남음(metrics.py `match`, 문서별 행렬) |
| 3장(b) 일대일 | PASS | 500개 무작위 행렬에서 중복 배정 없음(브루트포스 비교에서 개수 일치) |
| 3장(c) 경계 0.6 유효, 0.59 무효 | PASS | assign([[0.6]])=1건, assign([[0.59]])=0건. 벡터로 만든 코사인 0.6 쌍은 end-to-end에서도 유효(코사인 0.59 쌍은 무효) |
| 3장(d) 유효 수 우선, 같으면 유사도 합 | PASS | 무작위 500개(1~5 x 1~5, 임계 0.3)에서 유효 매칭 수가 브루트포스와 500/500 일치. 반례 [[.99,.61],[.61,.50]]: 합 최대 할당은 유효 1개(1.49), 도구는 유효 2개(1.22)를 택했고 브루트포스도 (2, 1.22). 합 동률 처리는 관찰 1 |
| 3장(e) 클래스는 매칭 제한 아님, 혼동표와 분류 일치 F1 | PASS | 클래스가 다른 쌍(Threshold 정답과 Access 예측)이 매칭되어 혼동표에 기록. 분류 일치 TP 2 / 일반 TP 3, 분류 일치 F1 0.5 |
| 4장 분모: 주 보고와 처리 범위 보고 | PASS | 가짜 사례를 손으로 계산해 대조. 주 보고: SOP 예측 4, 정답 4, TP3 FP1 FN1, P=R=F1=0.75. 처리 범위(SOP-001·002): 정답 3, TP3 FP1 FN0, P .75 R 1.0 F1 0.857. 도구 출력과 일치 |
| 4장 DS 예측은 범위 밖, FP 아님 | PASS | DS 예측 1건은 `datasheet_prediction_count`=1, `counted_as_fp_in_main`=false. 주 보고 FP 1건은 SOP 미매칭 예측이고 DS는 포함되지 않음. assignments.csv에 `out_of_scope` 행으로 따로 기록 |
| 5장 문서별 점수, 건수 비, F1 상한 | PASS | document_scores.csv에 문서별 TP/FP/FN/P/R/F1/분류 일치 F1. pred_gold_ratio=1.0, f1_upper_bound=2*4/8=1.0(손계산과 일치) |
| 5장 임계값 민감도 0.5/0.6/0.7 보고만 | PASS | `threshold_sensitivity`에 세 값 모두 출력. 주 보고는 0.6 고정 |
| 5장 혼동표, 센서 집합 일치 | PASS | `class_confusion_matched_pairs` 확인. sensors 필드가 없으면 "skipped"로 표시(코드 및 테스트 `test_sensor_agreement_only_when_present`) |
| 5장 등급 일치 지표 없음 | PASS | `grep -rniE "severity|grade|등급" src/imaks_kg/eval` 결과 0건 |
| 6장 lock이 정답 읽기 전에 쓰임 | PASS | cli.py에서 `write_lock`이 `gold_loader` 호출보다 앞. 실행 중 정답 로더가 불릴 때 lock 파일이 이미 존재(스파이 로더로 True 확인). lock 수정 시각이 metrics.json보다 이르거나 같음 |
| 6장 lock 내용 | PASS | 키: 예측 SHA-256, 정의서 SHA-256, 모델 `sentence-transformers/all-MiniLM-L6-v2`와 revision `1110a243...`, 라이브러리 5종 버전, 임계값 0.6, written_at_utc, meta |
| 6장 같은 폴더에서 예측이 다르면 중단 | PASS | 예측 1줄을 추가해 같은 폴더에 다시 실행하자 `LockMismatch ... predictions_sha256`로 중단. 같은 예측으로 다시 실행하면 통과 |
| 6장 정답 파일 SHA-256 기록 | PASS | metrics.json `inputs.gold_sha256`와 `gold_rows`. 로드된 revision 확인값(`revision_loaded`)도 요청값과 일치로 기록 |
| 출력에 정답 문장 없음 | PASS | 고유 문장 "SECRETGOLD_*"를 출력 폴더 4개 파일 전체에서 검색해 0건. assignments.csv에는 ruleId와 클래스만 있음 |
| 콘솔·예외에 정답 문장 없음 | PASS | 정답 오류 예외는 행 번호와 ruleId만 포함(`GoldError 정답 2행 ... ruleId='R1'`). 결과 수치만 출력됨 |
| 입력 오류 처리 | PASS | 정답에 알 수 없는 문서면 GoldError로 중단. 예측 JSON 오류는 "e.jsonl 2번째 줄: JSON 파싱 실패", 필드 누락은 "2번째 줄: 'action'가 없거나...", 알 수 없는 document_id도 줄 번호와 함께 예외. 모르는 필드는 무시(오류 없이 실행) |
| 재현성 | PASS | 실제 SBERT로 같은 입력을 두 번 실행: metrics.json과 assignments.csv의 바이트가 동일(metrics에 시각 필드 없음. 시각은 lock에만). 가짜 임베더 실행도 결정적(test_determinism) |
| ⑤ 주 지표 F1_content, F1_strict 미사용 | PASS | metrics.py·cli.py 어디에도 strict 지표가 없음(`grep strict` 0건). 주 보고 f1이 Hungarian과 SBERT, 임계 0.6 |
| ⑤ 임베딩 모델명·버전 기록 | PASS | lock과 metrics `embedding`에 모델명, revision, 라이브러리 버전(sentence-transformers 6.1.0, torch 2.14.1+cpu 등). 대조 쌍과 임계 통과 여부는 assignments.csv(`cosine`, `valid`)에 파일로 남음 |
| ⑤ 정답을 읽는 코드는 eval/ 아래에만 | PASS | `grep -rn ground_truth src`는 eval/gold.py(경로 상수)와 eval/__init__.py(주석)뿐. 정답 읽기 경로는 gold.py의 `load_gold`·`describe_gold`·`file_sha256` 한 모듈. `check_leakage.py`(기본 폴더) PASS, ground_truth 경고 없음 |
| 공통: check_raw_unchanged | PASS | `PASS: imaks_data/ 원본 불변 (1121개 파일)` |
| 공통: check_leakage | PASS | 검사한 파일 58개, `PASS: 금지 컬럼 없음` (기본 폴더와 명시 폴더 모두) |
| 공통: check_secrets | PASS | 검사한 파일 122개, 건너뜀 0, 발견 0건 |
| 공통: 절대 경로 | PASS | src·tests의 .py에서 `C:\`, `C:/`, `/Users/`, `/home/` 검색 0건 |
| 공통: 큰 산출물 비추적 | PASS | `evaluation/`은 .gitignore(222행)에 있고 `git ls-files evaluation` 결과 없음 |
| 공통: 이상값 삭제·보간 코드 없음 | PASS | eval/ 코드에 시계열 처리 없음 |
| 새 테스트가 실제로 검증하는가 | PASS | test_eval_f1.py의 핵심 테스트를 열어 확인: 유효 수 우선(탐욕 대비 반례), 경계 0.6/0.5999, 주·처리 범위 분모 5/3 vs 2/0, lock 순서 스파이 로더. 모두 값을 단언하고 자명하지 않음 |
| 전체 단위 테스트 | PASS | `Ran 115 tests in 86.493s` / `OK` |
| 금지 경로 | PASS | ontology_v1/ 수정 3개 파일(ontology.ttl, schema_tables.md는 3단계 작업의 rowIndex 주석 등)의 수정 시각이 14:45이고 평가기 파일(16:13~16:24)보다 앞섬. 이번 작업과 무관. harness/는 checklist.md만 수정 상태(승인된 수정) |

## 불합격 사유와 수정이 필요한 위치
없음.

## 미확인 항목과 이유
- 실제 정답 파일 기준 점수와 첫 실행 기준선, 튜닝 횟수: 지시에 따라 이번 판정에서 제외했고 실제 정답으로 평가를 돌리지 않았다.
- 로드된 revision 확인은 가중치 객체가 아니라 Hub 캐시 조회로 하는 간접 확인이다(embed.py 설명에 명시). 가중치 자체의 해시는 확인하지 않았다.

## 판정 외 관찰
1. 유사도 합 최대화는 유효 쌍만이 아니라 할당된 모든 쌍(유효하지 않은 쌍 포함)의 유사도를 더한다. 정의서의 비용식 "−(큰 상수 x 유효 여부 + 유사도)"를 문자 그대로 따른 것이어서 정의서와는 일치한다. 그러나 유효 수가 같을 때 "유효 쌍만의 합" 기준 브루트포스와 선택이 달라질 수 있다(임계 0.3 무작위 500개 중 42건, 임계 0.6의 [0.3,0.9] 균일 분포에서 500개 중 20건). 이 경우 TP/FP/FN과 F1은 같고, 어떤 쌍이 매칭됐는지(혼동표, 분류 일치 F1, 센서 일치)만 달라질 수 있다. 정의서에서 "유효 쌍의 합"인지 "전체 할당의 합"인지 한 줄 명시하면 좋다.
2. 정의서 2장의 문장 구성 민감도(`Condition: ... Action: ...` 방식 병행 계산)는 구현되지 않았다(코드에 해당 문자열 없음). 정의서는 "한 번은 두 방식 모두로 계산해 차이를 보고"한다고 했다.
3. 정의서 6장의 lock 내용 중 프롬프트·Example·스키마 해시와 요청/실제 사용 모델은 `--meta` JSON으로 받는 `meta` 필드에 맡겨져 있다. 평가기가 이를 강제하지 않으므로 meta를 주지 않으면 빈 객체로 기록된다.
4. 예측 파일을 먼저 읽어 형식 검증한 뒤 lock을 쓴다. 정답 노출과는 무관하다. 정답 형식 오류(예: 알 수 없는 문서)가 발생해도 lock은 이미 써져 있어 그 폴더에서 다시 실행하려면 같은 예측이어야 한다.
5. 주 보고의 문서 범위는 `SOP-` 접두어로 판별한다. 정답에 DS- 문서가 있으면 `gold_rows_in_datasheet_documents`로 따로 세지만 주 보고 분모(n_gold)에는 정답 전체가 들어간다. 현재 실제 정답은 SOP 4개 문서뿐이라 영향 없음.
6. 정의서 6장 7항(개별 매칭 목록은 저장소에 올리지 않음): assignments.csv가 ruleId 단위 매칭 목록을 담지만 `evaluation/`이 git 제외라 규칙상 충족. 별도 위치로 출력하면 올라갈 수 있다.
