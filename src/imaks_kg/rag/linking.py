"""Entity linking and duplicate merging for GraphRAG v3.

Two problems remained after graph_v2:

1. graph_v2 only links *exact* identifiers. Questions written the way people
   talk ("ST02 전류", "서버실 온도", "포장기 진동") never reach the graph.
2. The same rule exists twice in the KG: the seed node ``MAINT-04`` and the
   extracted node ``candidate-SOP-003::MAINT-04``. Both become graph cards,
   which wastes budget and hides that the two sources disagree
   ("Inspect inlet filter and pump" vs "Inspect filter and pump").

Linking never invents facts. It only chooses *start nodes*; every fact that
reaches the prompt still comes from a stored triple or a source chunk.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from rdflib import RDF, Graph, URIRef

from . import comparison as c
from .vector import REPO_ROOT

LEXICON_PATH = REPO_ROOT / "docs/graphrag_v3/lexicon.json"
_ASCII = "A-Za-z0-9_"


def load_lexicon(path: Path = LEXICON_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical_id(identifier: str) -> str:
    """``candidate-SOP-003::MAINT-04`` -> ``MAINT-04``."""
    return identifier.rsplit("::", 1)[-1]


def _is_ascii(text: str) -> bool:
    return bool(re.fullmatch(r"[\x00-\x7f]+", text))


def find_spans(alias: str, text: str) -> list[tuple[int, int]]:
    """ASCII aliases need ASCII word boundaries (``MAINT-03의`` matches,
    ``MAINT-030`` does not). Korean aliases match as substrings so that
    particles (``서버실의``) do not block them."""
    if _is_ascii(alias):
        pattern = rf"(?<![{_ASCII}-]){re.escape(alias)}(?![{_ASCII}])"
    else:
        pattern = re.escape(alias)
    return [m.span() for m in re.finditer(pattern, text, re.IGNORECASE)]


@dataclass
class Mention:
    node: str
    alias: str
    start: int
    end: int
    kind: str  # identifier | station_alias | sensor_composed


@dataclass
class EntityIndex:
    graph: Graph
    lexicon: dict
    identifier_aliases: dict[str, list[str]] = field(default_factory=dict)  # node -> aliases
    station_aliases: dict[str, list[str]] = field(default_factory=dict)     # station node -> aliases
    sensors: dict[tuple[str, str], str] = field(default_factory=dict)       # (station, type) -> sensor
    groups: dict[str, list[str]] = field(default_factory=dict)              # canonical id -> nodes

    @classmethod
    def build(cls, graph: Graph, lexicon: dict | None = None) -> "EntityIndex":
        index = cls(graph=graph, lexicon=lexicon or load_lexicon())
        by_identifier = {}
        for node, value in graph.subject_objects(c.IM.identifier):
            if (node, RDF.type, c.IM.Document) in graph:
                continue
            identifier = str(value)
            by_identifier[identifier] = str(node)
            aliases = {identifier, canonical_id(identifier)}
            index.identifier_aliases[str(node)] = sorted(aliases)
            index.groups.setdefault(canonical_id(identifier), []).append(str(node))
        for nodes in index.groups.values():
            nodes.sort()

        for station in graph.subjects(RDF.type, c.IM.Station):
            identifier = str(graph.value(station, c.IM.identifier))
            short = identifier.split("_", 1)[0]  # ST02_SEALING -> ST02
            aliases = {short, *index.lexicon["stations"].get(identifier, [])}
            index.station_aliases[str(station)] = sorted(aliases)
            for sensor in graph.objects(station, c.IM.hasSensor):
                sensor_type = str(graph.value(sensor, c.IM.sensorType))
                index.sensors[(str(station), sensor_type)] = str(sensor)
                # Document spellings: ST02-CUR, ST02_SEALING-CUR, ST02_CUR
                sensor_aliases = {f"{short}-{sensor_type}", f"{short}_{sensor_type}",
                                  f"{identifier}-{sensor_type}"}
                index.identifier_aliases.setdefault(str(sensor), [])
                index.identifier_aliases[str(sensor)] = sorted(
                    set(index.identifier_aliases[str(sensor)]) | sensor_aliases)
        return index

    # ------------------------------------------------------------------ linking
    def link(self, question: str) -> list[Mention]:
        mentions: list[Mention] = []
        for node, aliases in self.identifier_aliases.items():
            for alias in aliases:
                for start, end in find_spans(alias, question):
                    mentions.append(Mention(node, alias, start, end, "identifier"))
        stations = []
        for node, aliases in self.station_aliases.items():
            for alias in aliases:
                for start, end in find_spans(alias, question):
                    stations.append(Mention(node, alias, start, end, "station_alias"))
        stations = _longest_non_overlapping(stations + [m for m in mentions if self._is_station(m.node)])
        types = []
        for sensor_type, aliases in self.lexicon["sensor_types"].items():
            for alias in aliases:
                for start, end in find_spans(alias, question):
                    types.append((sensor_type, alias, start, end))
        types = _longest_non_overlapping_types(types)

        window = self.lexicon.get("sensor_window_chars", 14)
        composed = []
        for sensor_type, alias, start, end in types:
            nearest = _nearest_station(stations, start, end, window)
            if nearest is None:
                continue
            sensor = self.sensors.get((nearest.node, sensor_type))
            if sensor:
                composed.append(Mention(sensor, f"{nearest.alias}+{alias}",
                                        min(start, nearest.start), max(end, nearest.end), "sensor_composed"))
        result = {(m.node, m.kind): m for m in mentions + stations + composed}
        return sorted(result.values(), key=lambda m: (m.start, m.node))

    def _is_station(self, node: str) -> bool:
        return (URIRef(node), RDF.type, c.IM.Station) in self.graph

    def group_of(self, node: str) -> list[str]:
        identifier = self.graph.value(URIRef(node), c.IM.identifier)
        if identifier is None:
            return [node]
        return self.groups.get(canonical_id(str(identifier)), [node])


def _longest_non_overlapping(mentions: list[Mention]) -> list[Mention]:
    chosen: list[Mention] = []
    for m in sorted(mentions, key=lambda m: (-(m.end - m.start), m.start, m.node)):
        if all(m.end <= o.start or m.start >= o.end or m.node == o.node for o in chosen):
            chosen.append(m)
    return sorted(chosen, key=lambda m: m.start)


def _longest_non_overlapping_types(items):
    chosen = []
    for item in sorted(items, key=lambda t: (-(t[3] - t[2]), t[2])):
        if all(item[3] <= o[2] or item[2] >= o[3] for o in chosen):
            chosen.append(item)
    return sorted(chosen, key=lambda t: t[2])


def _nearest_station(stations: list[Mention], start: int, end: int, window: int):
    best, best_gap = None, None
    for s in stations:
        gap = start - s.end if s.end <= start else s.start - end if s.start >= end else 0
        if 0 <= gap <= window and (best_gap is None or gap < best_gap
                                   or (gap == best_gap and s.end <= start)):
            best, best_gap = s, gap
    return best


# ------------------------------------------------------------- merged cards
def merged_card(graph: Graph, nodes: list[str], links: dict) -> dict:
    """One card per real-world entity. Conflicting values are *kept side by
    side with their source*, never collapsed into one value."""
    properties: dict[str, dict[str, list[str]]] = {}
    sources = []
    for node in nodes:
        ref = URIRef(node)
        method = str(graph.value(ref, c.IM.extractionMethod) or "seed_or_structure")
        sources.append({"node": node, "extractionMethod": method})
        for predicate, value in graph.predicate_objects(ref):
            name = str(predicate).rsplit("#", 1)[-1]
            if name in {"hasProvenance", "identifier", "extractionMethod", "sourceNodeId"}:
                continue
            properties.setdefault(name, {}).setdefault(str(value), []).append(method)
    card_properties = {}
    for name, values in sorted(properties.items()):
        if len(values) == 1:
            card_properties[name] = next(iter(values))
        else:  # disagreement between seed and extraction stays visible
            card_properties[name] = [{"value": v, "from": sorted(set(m))} for v, m in sorted(values.items())]
    identifier = canonical_id(str(graph.value(URIRef(nodes[0]), c.IM.identifier)))
    chunks = sorted({cid for n in nodes for cid in links.get(URIRef(n), links.get(n, []))})
    return {"entity": identifier, "status": "stored_kg_assertion_not_live_measurement",
            "merged_from": sources, "properties": card_properties, "source_chunks": chunks}
