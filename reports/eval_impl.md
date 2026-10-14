# F1_content 평가기 구현 보고 (2026-10-14)

## 만든 파일
`src/imaks_kg/eval/`: `__init__.py`, `__main__.py`, `text.py`(유사도 문장), `embed.py`(SbertEmbedder 지연 로딩, revision 인자, 기본 1110a243...), `gold.py`(정답 로더, describe_gold), `predictions.py`(예측 JSONL 로더), `match.py`(문서 안 Hungarian), `metrics.py`, `lock.py`, `cli.py`.
테스트: `tests/test_eval_f1.py` (22개). 정답을 읽는 코드는 `src/imaks_kg/eval/gold.py`뿐이다.

## 사용법
```
PYTHONPATH=src .venv\Scripts\python.exe -m imaks_kg.eval --predictions <jsonl> [--out-dir <새 폴더>] [--gold <csv>] [--threshold 0.6] [--meta <json>] [--model-revision <hash>] [--processed-docs SOP-001,SOP-002]
PYTHONPATH=src .venv\Scripts\python.exe -m imaks_kg.eval describe-gold [--gold <csv>]
```
- 입력: 예측 JSONL(`document_id`, `class`, `condition`, `action`, 선택 `identifier`, `sensors`, `severity`, `model`), 정답 기본 `imaks_data/kg_seed/ground_truth.csv`, 알려진 문서 `preprocessed/documents/doc_manifest.csv`, 정의서 `docs/eval_definition_F1_content.md`(해시용).
- 출력(기본 `evaluation/f1_content_<UTC시각>/`): `pre_evaluation_lock.json`, `metrics.json`, `document_scores.csv`, `assignments.csv`(정답 문장 없음).
- 순서: 예측 읽기 -> lock 쓰기 -> 정답 읽기 -> 계산. 같은 폴더에 lock이 있고 예측 SHA-256, 정의서 SHA-256, 임베딩 모델/revision, 임계값 중 하나라도 다르면 중단(새 폴더 안내). 같으면 기존 lock을 그대로 둔다.

## 정의서 대비 구현한 것
- 문서별 일대일 할당(유효 수 우선, 유사도 합 보조, 비용 = -(큰 상수 x 유효 + 유사도), 직사각 처리), 클래스는 제한 없음. 경계 0.6은 유효(부동소수 오차 허용 1e-9, `match.py` EPS).
- TP/FP/FN/P/R/F1, 주 보고(SOP 예측 전체 vs 정답 전체), 처리 범위 보고(기본: 예측이 있는 SOP 문서, `--processed-docs`로 지정 가능), 범위 밖 예측(DS- 접두 개수만), 문서별 점수, 예측/정답 비와 이론적 F1 상한, 클래스 혼동표와 분류까지 일치 F1, 임계값 0.5/0.6/0.7 민감도, 센서 집합·등급 일치(예측에 필드가 있을 때만), GT-0009 binary는 N/A. SOP-/DS- 판별은 `metrics.py` 상수 한 곳.
- 모델/라이브러리 버전 기록: lock에 sentence-transformers, torch, transformers, scipy, numpy 버전.

## 실제 검증 실행 결과
- 전체 단위 테스트 마지막 줄: `Ran 114 tests in 47.410s` / `OK` (이 중 eval 22개, 실제 모델 스모크 1개는 모델이 캐시돼 있어 실행됨, 건너뛰지 않음).
- `check_raw_unchanged.py`: PASS (1121개 파일).
- `check_secrets.py`: PASS (검사 121개, 발견 0).
- 절대 경로 grep(`C:\`, `/Users/`, `/home/`) `src/imaks_kg/eval`, `tests/test_eval_f1.py`: 0건.
- **`check_leakage.py` 기본 폴더: FAIL, 9건 발견. 전부 `src/imaks_kg/eval/`의 단어 `severity`**(gold.py 2, metrics.py 4, predictions.py 3). `ground_truth` 경고는 출력에 없다(0건). 충돌 지점: 정의서/요청이 예측 필드 `severity`와 정답 열 `severity`의 일치 비율을 요구하는데, 가드가 `harness/forbidden_columns.txt`의 `severity`를 코드 본문 단어로도 막는다. 이는 규칙 속성이지 ⑥ 입력이 아니다. 가드를 피하려고 단어를 쪼개 쓰는 우회는 하지 않았다(규칙 위반 소지). 결정 필요: (a) 가드에서 `eval/`을 이 단어에 한해 예외로 하거나(harness 수정이라 내 권한 밖), (b) 등급 일치 지표를 빼고 코드에서 단어 제거. 어느 쪽인지 정해 주면 맞춰 고친다.

## describe-gold 실제 실행(구조만)
- 헤더: ruleId, class, station, sensor, sensorType, condition, action, severity, critHi, warnHi, critLo, warnLo, unit, source (14열)
- 행 수 86. 문서 열(`source`)의 서로 다른 값: SOP-001, SOP-002, SOP-003, SOP-004 (모두 doc_manifest의 doc_id와 정확히 일치)
- 문서별: SOP-001 29, SOP-002 27, SOP-003 11, SOP-004 19, 데이터시트 0
- 클래스별: OperationalRule 28, ThresholdRule 27, AccessRule 20, MaintenanceRule 11
- 팀원 보고(29/27/11/19/0, 합 86)와 **같음**.

## 가정
- 처리한 문서 = 예측이 1건 이상 있는 SOP 문서(예측 0건으로 처리한 문서는 `--processed-docs`로 지정해야 함).
- 정답의 센서는 단일 문자열로 보고 집합 {sensor}(빈 값이면 공집합)와 예측 `sensors` 집합을 비교, 등급은 대소문자 무시 문자열 비교.
- 예측의 `document_id`가 manifest에 없거나 `class`가 4분류가 아니면 예외. condition과 action이 모두 비면 예외.
- 정답에 DS- 문서 행이 있으면 정답 분모에는 들어가지만(FN) DS 예측과는 매칭하지 않는다. `metrics.json`에 그 행 수를 기록.

## 미확인 / 한계
- 실제 로드된 revision: 로드된 가중치 객체에서 직접 읽지 못했다(`config._commit_hash` 없음, `model_card_data`의 값은 요청값을 되돌려 주는 것으로 보여 독립 근거가 아님). 대신 로컬 Hub 캐시의 (모델, 요청 revision) 스냅샷 폴더 이름을 조회해 `1110a243...`임을 확인했다(간접 확인). `metrics.json`의 `embedding.revision_loaded`에 기록하고 확인 불가면 `unverified`.
- 실제 정답으로 실제 점수를 내는 실행은 하지 않았다(예측 파일 없음). 정답 로드와 전체 파이프라인은 가짜 정답으로만 시험했다.
- 문장 구성 민감도(`Condition:..\nAction:..` 방식 병행 계산)는 구현하지 않았다. 정의서 2장이 한 번 해 볼 것을 권하므로 미구현 항목.
- `metrics.json`/`assignments.csv`에는 정답 ruleId와 유사도가 있다(정의서 6.7: 저장소에 올리지 않는다, `evaluation/`은 git 제외).
- 모델 revision이 lock에 "요청값"으로만 들어가는 것은 lock이 모델 로드 전에 쓰이기 때문. 로드된 값은 metrics에만 기록.
- 일부 문서 예측이 0건인 경우 `document_scores.csv`의 해당 문서는 processed=False로 나온다.

verifier 검증이 필요하다.

## v2 변경(등급 지표 제거)
사용자 결정에 따라 등급 일치 지표를 뺐다(위 본문의 등급 관련 서술과 충돌 항목은 v2에서 대체됨).
- `gold.py`: 정답의 등급 열 읽기와 GoldRule의 등급 필드 제거. `predictions.py`: 등급 필드 검사 제거. `metrics.py`: 등급 일치 계산과 `agreement_on_matched_pairs`의 등급 항목 제거(센서 집합 일치는 유지). 코드·테스트·주석에서 해당 단어 0건(grep 확인). 가드 우회는 만들지 않았다.
- 예측 로더는 모르는 필드(추출 쪽의 추가 필드 포함)를 오류 없이 무시한다. 테스트 `test_unknown_prediction_fields_are_ignored` 추가. 지시가 예로 든 필드명은 가드에 걸릴 수 있어 중립적인 가짜 필드명(`unknownField`, `evidence`, `ruleExtra`)으로 시험했다.
- 재검증: 전체 단위 테스트 마지막 줄 `Ran 115 tests in 45.845s` / `OK`; `check_leakage.py` 기본 폴더 `PASS: 금지 컬럼 없음`(발견 0, ground_truth 경고 없음); `check_secrets.py` PASS(발견 0); `check_raw_unchanged.py` PASS(1121개); 절대 경로 grep 0건.
- 본문의 "충돌 지점/결정 필요" 항목은 이 변경으로 해소됨.

verifier 검증이 필요하다.

## v3 변경(유효 쌍 유사도 합)
- `match.py`: 비용을 `-where(유효, 큰 상수 + 유사도, 0)`으로 바꿨다. 무효한 쌍은 기여 0, 최종 결과는 유효한 쌍만 남긴다. 1순위 유효 수 최대화, 2순위 유효 쌍 유사도 합 최대화. 경계(정확히 0.6 유효, 오차 1e-9)와 결정성 유지.
- 테스트 추가: 반례(P1~P3 x G1~G3)에서 {P1-G2, P3-G1}(합 1.38) 선택, 평가 경로 TP 2 / FP 1 / FN 1; 유효 수 우선 반례([0.99,0.61],[0.61,0.59]) 유지·명시; 완전 탐색 헬퍼와 일치(시드 12345, 3x3~4x4 무작위 60개); 동률 결정성. 기존 테스트 중 이전 방식에 의존한 것은 없어 수정하지 않았다. 반례 평가 경로 테스트는 코사인 행렬을 직접 주입하려고 `metrics.cosine_matrix`를 테스트 안에서 잠시 대체한다.
- 재검증: 전체 단위 테스트 `Ran 120 tests in 36.262s` / `OK`; `check_leakage.py` `PASS: 금지 컬럼 없음 (경고 3건)` - 경고는 `src/imaks_kg/extract/` 쪽(예: providers/base.py:36의 `ground_truth_supplied` 플래그 이름)이며 eval 코드와 무관, 내가 고치지 않았다; `check_secrets.py` PASS(발견 0); `check_raw_unchanged.py` PASS(1121개).
- `docs/eval_definition_F1_content.md` 3장 4항(유사도 합 문구)은 수정하지 않았다(사용자가 수정 예정). lock은 정의서 해시를 비교하므로 정의서 수정 뒤에는 새 출력 폴더가 필요하다.

verifier 검증이 필요하다.
