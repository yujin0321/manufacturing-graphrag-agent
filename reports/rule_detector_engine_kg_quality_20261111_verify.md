# 룰 탐지 엔진 KG 품질 보고서 (2026-11-11, 1단계)

탐지 엔진 컴파일 중 확인한 KG 상태다. 보고만 하며 탐지 결과·심각도·KG는 바꾸지 않았다.

- KG: `artifacts/stage6_final_20261016/inputs/kg_build/openai_sol_v2_20261016/graph/candidate.ttl` (sha256 `8ab82a866135…`)
- 센서에 연결된 규칙(Operational/Maintenance/Threshold): 61개
- `ruleSeverity` 값이 없는 규칙: 61개 (전체)
- `conditionText`가 없어 컴파일에서 건너뛴 센서 연결 규칙: 8개

## 1. 원문에 등급 표기가 있지만 `ruleSeverity`가 비어 있는 규칙

| 규칙 ID | 클래스 | 원문 표기 | 실행 종류 | KG 노드 |
|---|---|---|---|---|
| RULE-CHM01-01-CRITICAL | OperationalRule | CRITICAL | kg_document_rule | `https://example.org/imaks/id/candidate-SOP-001%3A%3ARULE-CHM01-01-CRITICAL` |
| RULE-RND01-02-CRITICAL | OperationalRule | CRITICAL | kg_document_rule | `https://example.org/imaks/id/candidate-SOP-001%3A%3ARULE-RND01-02-CRITICAL` |
| RULE-SRV01-02 | OperationalRule | CRITICAL | kg_document_rule | `https://example.org/imaks/id/candidate-SOP-001%3A%3ARULE-SRV01-02` |
| RULE-ST02-02 | OperationalRule | CRITICAL | kg_document_rule | `https://example.org/imaks/id/candidate-SOP-001%3A%3ARULE-ST02-02` |
| RULE-ST03-02-CRITICAL | OperationalRule | CRITICAL | kg_document_rule | `https://example.org/imaks/id/candidate-SOP-001%3A%3ARULE-ST03-02-CRITICAL` |
| RULE-ST04-01 | OperationalRule | WARNING | kg_document_rule | `https://example.org/imaks/id/candidate-SOP-001%3A%3ARULE-ST04-01` |
| RULE-ST04-02 | OperationalRule | CRITICAL | kg_document_rule | `https://example.org/imaks/id/candidate-SOP-001%3A%3ARULE-ST04-02` |
| RULE-WRH01-01-CRITICAL | OperationalRule | CRITICAL | kg_document_rule | `https://example.org/imaks/id/candidate-SOP-001%3A%3ARULE-WRH01-01-CRITICAL` |

incident severity uses only SOP-002 band kinds (kg_threshold_critical / kg_threshold_warning / sop002_out_of_range); document-rule severity tags are not used. Unchanged in stage 1.

## 2. 미지원 규칙

| 규칙 ID | 사유 | KG 노드 |
|---|---|---|
| SOP-003-EX-02 | monitoring/correlation instruction, not a threshold condition; v3: no observable sensor pair/condition | `https://example.org/imaks/id/candidate-SOP-003%3A%3ASOP-003-EX-02` |
| SOP-003-EX-03 | DRIFT slope/baseline is not specified operationally; v3: no observable sensor pair/condition | `https://example.org/imaks/id/candidate-SOP-003%3A%3ASOP-003-EX-03` |

## 3. `conditionText`가 없는 센서 연결 규칙

| 규칙 ID | 클래스 | 같은 ID의 원문 노드 존재 | KG 노드 |
|---|---|---|---|
| MAINT-01 | MaintenanceRule | 예 | `https://example.org/imaks/id/MAINT-01` |
| MAINT-02 | MaintenanceRule | 예 | `https://example.org/imaks/id/MAINT-02` |
| MAINT-03 | MaintenanceRule | 예 | `https://example.org/imaks/id/MAINT-03` |
| MAINT-04 | MaintenanceRule | 예 | `https://example.org/imaks/id/MAINT-04` |
| MAINT-05 | MaintenanceRule | 예 | `https://example.org/imaks/id/MAINT-05` |
| MAINT-06 | MaintenanceRule | 예 | `https://example.org/imaks/id/MAINT-06` |
| MAINT-07 | MaintenanceRule | 예 | `https://example.org/imaks/id/MAINT-07` |
| MAINT-08 | MaintenanceRule | 예 | `https://example.org/imaks/id/MAINT-08` |

## 4. 상관 쌍 방향

모든 상관 쌍의 결과 방향이 원문에서 정해졌다.

## 5. 후속 후보 (이번 단계에서 하지 않음)

- `ruleSeverity`를 KG에 채우거나 원문 등급 표기를 사건 심각도에 반영할지 결정(탐지 결과가 바뀌므로 새 평가 체계 이후).
- 원문 노드가 따로 있는 seed 노드(`conditionText` 없음)를 KG에서 하나로 합칠지 결정(현재 컴파일러는 건너뛰므로 탐지에는 영향 없음).
