# 평가 전 고정 정책 — 2026-10-13

- 입력 예측은 이전 단계에서 고정한 outputs/predictions.jsonl 172건이다. 정답을 읽은 후 추출 문장/클래스/건수를 바꾸지 않는다.
- KG 구축은 source-only 문서, 고정 예측, ZIP의 kg_seed/nodes.csv 및 edges.csv만 사용한다. ground_truth.csv는 KG 빌드 함수에서 받거나 읽지 않는다.
- 원본 nodes/edges에서 Station·Component·Sensor 구조만 사용한다. Component는 동일 명칭 Station으로 흡수하고 Sensor 연결을 단방향 hasSensor로 정리한다. Maintenance는 예측 MAINT 규칙과 별도 매핑표에서 대조하며, 기존 seed를 새 LLM 예측으로 복사하지 않는다. Person/Zone 노드/이벤트 정답/인과 정답은 생성하지 않는다.
- Rule·Document·Provenance를 RDF로 만들고 로컬 파일로 검증한다. Neo4j 서버 적재는 연결 설정이 없는 한 주장하지 않는다. 재현 가능한 Neo4j 입력도 만들 수 있다.
- 정답은 ZIP의 원본 kg_seed/ground_truth.csv를 사용한다. 수정본이나 이전 평가 결과를 사용하지 않는다.
- 주지표 F1_content: SBERT all-MiniLM-L6-v2 코사인 유사도 + Hungarian 1:1 할당, 임계값 0.6. 라이브러리와 모델이 없어 이번 실행에서는 산출 불가. 다른 점수로 대체해 이 이름을 쓰지 않는다.
- 가능한 첫 정량 결과: (1) ID/분할 ID 기준 진단 대조(내용 일치 점수 아님), (2) lowercase 유니코드 단어/숫자 토큰 다중집합 Dice 유사도 + 문서별 Hungarian 1:1 할당, 임계값 0.6의 F1_lexical_proxy. sourceQuote/ID는 유사도 문장에서 제외하고 conditionText+responseText만 사용한다. 클래스는 매칭 제한에 넣지 않고 매칭 후 혼동표로 기록한다.
- 동일 정답의 분할 예측을 임의로 합치지 않는다. 1:1 지표의 원자화 불일치 한계를 명시한다. 예측/정답의 전체 건수와 미매칭 목록을 공개한다. 문서가 없는 정답은 유사도 매칭에서 오류로 중단한다.
- F1_lexical_proxy는 의미 F1이나 사람 평가가 아니다. 수치·부등호·부정의 일치와 의미적 정답성은 보장하지 않는다. 언어 혼용/원자화 차이로 낮은 점수가 생길 수 있다.
- 정답 노출은 추출 완료 이후 평가 단계에만 발생한다. 이후 정답을 보고 추출을 개선하면 새로운 별도 실험으로 표시해야 한다.
- API 호출·새 패키지/모델 설치 없이 실행한다. 큰 원문과 정답은 GitHub에 푸시하지 않고 코드/집계 보고서만 푸시한다.
