"""Load evaluation-only ground truth files."""
from pathlib import Path

from imaks_kg.common.io_utils import read_csv_rows


def load_ground_truth(path: Path):
    _, rows = read_csv_rows(Path(path))
    return rows
