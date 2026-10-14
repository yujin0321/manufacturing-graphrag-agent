"""저장소 기준 경로 상수. 절대 경로는 이 파일에서 Path(__file__)로만 계산한다."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# 읽기 전용 원본
IMAKS_DATA = REPO_ROOT / "imaks_data"
RAW_SENSORS_DIR = IMAKS_DATA / "sensors"
RAW_RULES_DIR = IMAKS_DATA / "rules"
RAW_DATASHEETS_DIR = IMAKS_DATA / "datasheets"
KG_SEED_DIR = IMAKS_DATA / "kg_seed"

# 산출물
PREPROCESSED = REPO_ROOT / "preprocessed"
SENSORS_OUT = PREPROCESSED / "sensors"
DOCUMENTS_OUT = PREPROCESSED / "documents"
EVALUATION_DIR = REPO_ROOT / "evaluation"  # 평가 전용 폴더
KG_BUILD = REPO_ROOT / "kg_build"  # KG 변환 산출물(git 무시)
REPORTS_DIR = REPO_ROOT / "reports"

# 온톨로지·SHACL
ONTOLOGY_DIR = REPO_ROOT / "ontology_v1"
ONTOLOGY_TTL = ONTOLOGY_DIR / "ontology.ttl"
SHAPES_TTL = ONTOLOGY_DIR / "shapes.ttl"

# 점검에 쓰는 금지어 목록(코드에 단어를 적지 않고 파일에서 읽는다)
FORBIDDEN_COLUMNS_FILE = REPO_ROOT / "harness" / "forbidden_columns.txt"
FORBIDDEN_HEADER_ONLY_FILE = REPO_ROOT / "harness" / "forbidden_columns_header_only.txt"


def rel(path: Path) -> str:
    """저장소 기준 상대 경로(POSIX 표기)."""
    return Path(path).resolve().relative_to(REPO_ROOT).as_posix()


# B(Rule·Document 승격) 입출력
DOC_MANIFEST = DOCUMENTS_OUT / "doc_manifest.csv"
DOC_PAGES = DOCUMENTS_OUT / "pages.jsonl"
DOC_TABLES = DOCUMENTS_OUT / "tables.jsonl"
SENSOR_THRESHOLDS_CSV = SENSORS_OUT / "rules" / "sensor_thresholds.csv"
SEED_TTL = KG_BUILD / "seed.ttl"
RULES_TTL = KG_BUILD / "rules_deterministic.ttl"
SEED_PLUS_RULES_TTL = KG_BUILD / "seed_plus_rules.ttl"  # SHACL 확인용 합본(seed + rules)

# 전처리 고정 검증 기록(해시 사슬). 생성은 `python -m imaks_kg.kg.preprocess_lock --init`으로만 한다.
PREPROCESS_LOCK = REPO_ROOT / "harness" / "preprocess_lock.json"
PREPROCESS_CODE_DIR = REPO_ROOT / "src" / "imaks_kg" / "preprocess"
PREPROCESS_VERIFY_REPORT = REPORTS_DIR / "preprocess_verify.md"

# C(LLM 규칙 추출, ④) 입출력
DOC_CHUNKS = DOCUMENTS_OUT / "chunks.jsonl"
EXTRACT_CODE_DIR = REPO_ROOT / "src" / "imaks_kg" / "extract"
EXTRACT_PROMPTS_DIR = EXTRACT_CODE_DIR / "prompts"
EXTRACTION_DIR = REPO_ROOT / "extraction"  # 실행 기록·원본 응답·검토 CSV(git 무시)
EXTRACTION_RUNS = EXTRACTION_DIR / "runs"
EXTRACTION_CONFLICTS_CSV = EXTRACTION_DIR / "conflicts.csv"  # 데이터시트 vs SOP-002 수치 충돌 후보
RULES_LLM_TTL = KG_BUILD / "rules_llm.ttl"
RULES_LLM_PREREVIEW_TTL = KG_BUILD / "rules_llm_prereview.ttl"
SEED_RULES_LLM_TTL = KG_BUILD / "seed_plus_rules_llm.ttl"  # SHACL 확인용 합본(seed + B + C)
EXTRACTION_APPROVALS = EXTRACTION_DIR / "approvals"  # --dry-run 비용 추정 기록(--execute 승인 게이트)
DOTENV_FILE = REPO_ROOT / ".env"  # Gemini 키(GEMINI_API_KEY 줄만 읽음). 코드는 쓰지 않는다
EXTRACTION_LEDGER = REPO_ROOT / "harness" / "extraction_ledger.jsonl"  # git 추적 해시 장부(추가만, 해시 사슬)
EXTRACTION_LOCKS = EXTRACTION_DIR / ".locks"  # 프로세스 사이 잠금 파일(git 무시: /extraction/)
