# 6차 최종 문서 기반 KG

먼저 [최종 보고서·관계 시각화](../../reports/stage6_final_20261016_verify.md)를 확인하세요.

- [최종 KG](final/document_kg.ttl): 3,016 트리플. AI 검토·출처 메타데이터 포함.
- [관계 및 검토 상세](final/relations.json): 조건·출처·검토·수정 반영 기록.
- [집계](final/summary.json): 6개 구조화 연결 및 기존 seed 관계 보강 1개.
- [AI 검토 보고서](../../reports/relation_candidate_ai_review_20261016_verify.md).

비상정지 세 대상은 한 지시에서 나온다. 열 이상 영향은 문서 주장이다. 사람 승인 및 경험적으로 검증된 신규 인과관계는 0개다. 기존 v2 팀 F1 86.19%는 정답 노출 이력이 있는 개발 평가값이며 이번 관계 검토의 점수가 아니다.

## 원본 PDF·API·모델 다운로드 없이 재생성

Python 3.10 이상과 `rdflib`, `pyshacl`만 필요하다. 저장소 루트에서 실행한다. 이미 설치되어 있으면 설치 명령은 생략한다.

```powershell
python -m pip install 'rdflib>=7.1,<8' 'pyshacl>=0.30,<0.41'
$env:PYTHONPATH='src'
python -m imaks_kg.kg.finalize_stage6 --bundle artifacts/stage6_final_20261016
```

출력은 Git에서 제외된 `kg_build/stage6_final_20261016/`에 생성된다. 추출 모델을 다시 호출하거나 SBERT를 설치하지 않는다. 입력 스냅샷은 해시 검사 후 사용한다. 이 모드는 원문 일부의 동결 스냅샷으로 최종 KG를 재구성하는 것이며, 원본 PDF에서 전처리·추출을 다시 하는 실험이 아니다. 원본 PDF 대조는 패키징 시 수행했다.

공유본의 검증 및 재생성 그래프 동등성 검사는 다음 명령으로 실행한다.

```powershell
python -m unittest discover -s tests -p 'test_stage6_bundle.py' -v
```

`inputs/`는 이전 후보, AI 검토, v2 예측, 기본 그래프 등의 재생성 입력이다. `source_units.json`은 사용한 원문 단위 5개(신규 후보 6개에 해당하는 것은 4개)다. 전체 원본 데이터, ground_truth 정답, API 키, 개인 환경 및 모델 파일은 포함하지 않는다. `bundle_manifest.json`은 공유 데이터의 SHA-256 목록이다.
