"""Run SHACL validation for generated KG Turtle artifacts."""
import argparse
from pathlib import Path

from imaks_kg.common.io_utils import write_text
from imaks_kg.settings import REPO_ROOT


def validate_ttl(data_path, report_path=None):
    try:
        from pyshacl import validate
        from rdflib import Graph
    except ImportError as exc:
        raise RuntimeError("Install dependencies first: python3 -m pip install -r requirements.txt") from exc

    data = Path(data_path)
    shapes = REPO_ROOT / "ontology_v1" / "shapes.ttl"
    ont = REPO_ROOT / "ontology_v1" / "ontology.ttl"
    dg = Graph().parse(str(data), format="turtle")
    sg = Graph().parse(str(shapes), format="turtle")
    og = Graph().parse(str(ont), format="turtle")
    conforms, _, text = validate(dg, shacl_graph=sg, ont_graph=og, inference="none")
    if report_path:
        write_text(Path(report_path), text)
    return conforms, text


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(REPO_ROOT / "kg_build" / "latest" / "kg.ttl"))
    parser.add_argument("--report", default=str(REPO_ROOT / "evaluation" / "shacl_report.txt"))
    args = parser.parse_args(argv)
    conforms, text = validate_ttl(args.data, args.report)
    print(text)
    if not conforms:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
