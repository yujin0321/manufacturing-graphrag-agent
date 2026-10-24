# 개선 전 기준선 보존 완료

2026-10-24 KST. 사용자가 요청한 개선 절차의 **1번: 현재 결과 보존**을 완료했다. 검색 코드 개선·추가 임베딩·답변 재생성은 이번 작업에서 실행하지 않았다.

## 보존 대상과 확인 결과

- 예원 v2 원래 candidate.ttl 및 자동 추출 예측 파일.
- 원문 청크, Vector RAG 인덱스와 API 응답 캐시.
- LLM·Vector RAG·GraphRAG 코드, 공통 생성 지시문, 설정, 테스트, 실행 스크립트.
- dev/eval 질문, 정답, 고정 채점 기준, 수동 AI 판정과 집계 코드, 결과 보고서.
- 기존 Vector RAG dev6 + 새 두 방식 dev12 + eval72 = **원본 응답90개**, 각 요청·검색·응답 기록.
- 실행 당시 Python·의존성 버전 및 Git HEAD. 미커밋 파일도 ZIP에 직접 보존했으므로 Git HEAD만으로 스냅샷을 대신하지 않는다.

전체 **699개 원본 파일**을 ZIP으로 보존했다. ZIP 크기 **2,331,498바이트(약 2.22MiB)**이며 별도 manifest·seal은 작은 메타데이터다. 원본 파일은 이동·삭제·수정하지 않았다.

검증: 기존 scoring_lock의 동결 파일 해시, 신규84응답 감사 해시, 기존 Vector RAG dev6 응답 해시를 먼저 대조했다. ZIP 생성 후 CRC, 내부 파일 목록·개수·크기, 파일별 SHA-256, 내부/외부 manifest 일치, ZIP 전체 SHA-256을 확인했다. 보존 시점 작업 파일과의 차이는 **0개**다.

## 보존 위치

`evaluation/baselines/yewon_v2_comparison_20261024/`

- `baseline_PRIVATE.zip`: 복구 가능한 코드·입력·출력 사본과 내부 BASELINE_MANIFEST.json.
- `manifest.json`: 저장소 상대 경로별 SHA-256·크기, 환경 버전, 기준 점수.
- `seal.json`: ZIP과 외부 manifest의 SHA-256.

정답·원문·API 응답을 포함하므로 비공개 평가 폴더에 보관하며 Git에서 제외된다. API 키나 환경변수 파일, 가상환경, 모델 가중치, 대용량 원본 PDF ZIP, 관련 없는 실험은 보존 대상에 포함하지 않았다. 새 API 호출·패키지 설치·Git 커밋/푸시는 없다.

이것은 **같은 로컬 디스크의 복구 사본과 변경 탐지 기록**이다. 파일시스템의 영구 쓰기 금지나 외부 재해 복구 백업은 아니다. 코드가 기존 보존 폴더에 덮어쓰기를 거부하며, 변경 여부는 검증 명령으로 확인할 수 있다.

## 고정된 점수

| 집합 | LLM /5 | Vector RAG /5 | GraphRAG /5 |
|---|---:|---:|---:|
| dev6 | 0.6667 | 3.9167 | 3.9167 |
| eval24 | 0.7917 | 4.4375 | 4.4375 |

eval 완전 정답은 각각 0/24, 18/24, 18/24다. AI 단독 채점·문서 접근 차이·과거 정답 노출 등의 기존 한계를 그대로 보존했다. 보존 작업으로 평가의 독립성이 새로 생기는 것은 아니다.

## 이후 확인 방법

저장소 루트 PowerShell에서:

```powershell
$env:PYTHONUTF8='1'
..\.venv\Scripts\python.exe scripts/preserve_comparison_baseline.py verify
# 보존된 파일과 현재 작업 파일의 차이도 확인
..\.venv\Scripts\python.exe scripts/preserve_comparison_baseline.py verify --compare-working
```

첫 명령은 ZIP·manifest의 무결성을 확인한다. 둘째 명령은 이후 코드 개선으로 달라진 작업 파일도 나열한다. 작업 파일 변경은 기준선 ZIP 변조와 구분한다. 복구가 필요하면 ZIP을 별도 새 폴더에 풀어 비교하며 현 작업 폴더에 덮어쓰지 않는다.

다음은 **2번: GraphRAG 검색 개선판을 별도 코드·설정·출력 경로로 구현**하는 단계다. 이 보존본과 기존 비교 응답은 덮어쓰지 않는다.
