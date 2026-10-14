"""저장소 기준 경로 상수. 절대 경로는 이 파일에서 Path(__file__)로만 계산한다."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# 읽기 전용 원본
IMAKS_DATA = REPO_ROOT / "imaks_data"
RAW_SENSORS_DIR = IMAKS_DATA / "sensors"
RAW_RULES_DIR = IMAKS_DATA / "rules"
RAW_DATASHEETS_DIR = IMAKS_DATA / "datasheets"

# 산출물
PREPROCESSED = REPO_ROOT / "preprocessed"
SENSORS_OUT = PREPROCESSED / "sensors"
DOCUMENTS_OUT = PREPROCESSED / "documents"
EVALUATION_DIR = REPO_ROOT / "evaluation"  # 평가 전용 폴더

# 점검에 쓰는 금지어 목록(코드에 단어를 적지 않고 파일에서 읽는다)
FORBIDDEN_COLUMNS_FILE = REPO_ROOT / "harness" / "forbidden_columns.txt"
FORBIDDEN_HEADER_ONLY_FILE = REPO_ROOT / "harness" / "forbidden_columns_header_only.txt"


def rel(path: Path) -> str:
    """저장소 기준 상대 경로(POSIX 표기)."""
    return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
