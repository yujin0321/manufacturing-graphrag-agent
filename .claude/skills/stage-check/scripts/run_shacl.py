#!/usr/bin/env python3
"""pyshacl로 데이터 그래프를 SHACL shapes에 대해 검증한다.

사용: python run_shacl.py --data <data.ttl> [--shapes ontology_v1/shapes.ttl] [--ont ontology_v1/ontology.ttl]
종료 코드: 0 적합, 1 위반, 2 사용 오류/의존성 없음
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--shapes", default="ontology_v1/shapes.ttl")
    ap.add_argument("--ont", default=None, help="온톨로지(ttl). 하위 클래스 관계를 데이터에 섞는다(추론은 하지 않음). 하위 유형을 쓰는 데이터에는 필요")
    args = ap.parse_args()

    try:
        from pyshacl import validate
        from rdflib import Graph
    except ImportError:
        print("pyshacl/rdflib가 없습니다: pip install pyshacl rdflib")
        return 2

    def resolve(p):
        p = Path(p)
        return p if p.is_absolute() else ROOT / p

    data, shapes = resolve(args.data), resolve(args.shapes)
    for label, p in (("데이터", data), ("shapes", shapes)):
        if not p.exists():
            print(f"{label} 파일이 없습니다: {p}")
            return 2

    dg = Graph().parse(str(data))
    sg = Graph().parse(str(shapes))
    og = Graph().parse(str(resolve(args.ont))) if args.ont else None
    # 추론은 끈다: RDFS 추론은 range 선언으로 값에 타입을 붙여(예: Sensor를 Station으로 간주) sh:class 검사를 무력화한다.
    # --ont는 하위 클래스 관계만 데이터에 섞는 용도로 쓴다.
    conforms, _, text = validate(dg, shacl_graph=sg, ont_graph=og, inference="none")
    print(text)
    print("PASS: SHACL 적합" if conforms else "FAIL: SHACL 위반")
    return 0 if conforms else 1


if __name__ == "__main__":
    sys.exit(main())
