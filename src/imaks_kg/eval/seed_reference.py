"""Evaluation-only access to iMAKS seed KG references."""
from pathlib import Path

from imaks_kg.common.io_utils import read_csv_rows


def load_seed_counts(nodes_csv: Path, edges_csv: Path):
    _, nodes = read_csv_rows(Path(nodes_csv))
    _, edges = read_csv_rows(Path(edges_csv))
    return {"seed_nodes": len(nodes), "seed_edges": len(edges)}
