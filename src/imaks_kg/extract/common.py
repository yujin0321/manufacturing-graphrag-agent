"""C 공용 도구: jsonl 읽기, seed ID 목록, 안전한 파일 이름, 경로 표기."""
import json
import re
from pathlib import Path

from rdflib import RDF, Graph

from imaks_kg.kg.naming import IM
from imaks_kg.settings import REPO_ROOT


class ExtractError(RuntimeError):
    """C 단계에서 멈춰야 하는 오류(입력 불일치, 미결정 검토 등). 추측하지 않고 멈춘다."""


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl_sorted(records):
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records)


def safe_name(chunk_id: str) -> str:
    """청크 ID를 Windows에서도 쓸 수 있는 파일 이름으로(':' 금지). 되돌릴 수 있게 '__'로 바꾼다."""
    if "__" in chunk_id:
        raise ExtractError(f"청크 ID에 '__'가 있어 파일 이름으로 바꿀 수 없음: {chunk_id}")
    name = chunk_id.replace(":", "__")
    if not re.match(r"^[A-Za-z0-9_.\-]+$", name):
        raise ExtractError(f"파일 이름으로 쓸 수 없는 청크 ID: {chunk_id}")
    return name


def disp(p) -> str:
    """출력용 경로: 저장소 안이면 상대 경로, 밖(테스트 임시 폴더)이면 그대로."""
    try:
        return Path(p).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return Path(p).as_posix()


def seed_ids(seed_ttl):
    """seed.ttl에서 Sensor·Station identifier 목록과 센서 → 스테이션 대응(hasSensor)."""
    g = Graph().parse(str(seed_ttl), format="turtle")
    sensors, stations, sensor_station = {}, {}, {}
    for s in g.subjects(RDF.type, IM.Sensor):
        ids = [str(o) for o in g.objects(s, IM.identifier)]
        if len(ids) != 1:
            raise ExtractError(f"seed Sensor {s}의 identifier가 1개가 아님: {ids}")
        sensors[ids[0]] = s
    for s in g.subjects(RDF.type, IM.Station):
        ids = [str(o) for o in g.objects(s, IM.identifier)]
        if len(ids) != 1:
            raise ExtractError(f"seed Station {s}의 identifier가 1개가 아님: {ids}")
        stations[ids[0]] = s
    by_iri = {v: k for k, v in sensors.items()}
    for st_id, st in stations.items():
        for sen in g.objects(st, IM.hasSensor):
            sensor_station[by_iri[sen]] = st_id
    return {"sensors": sorted(sensors), "stations": sorted(stations), "sensor_station": sensor_station,
            "graph": g}
