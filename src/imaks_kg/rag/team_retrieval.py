"""Shared v5 document modes and finite, complete KG queries for the team app."""
import json
from pathlib import Path

import numpy as np
from rdflib import Literal, RDF, URIRef

from . import comparison as c, retrieval_v3 as r3, retrieval_v4 as r4, retrieval_v5 as r5, vector as v
from .kg_query_v5 import KGEngine, short

INDEX = v.REPO_ROOT / 'kg_build/team_app/document_index'


def embedding_text(record, engine):
    text = v.embedding_text(record)
    stations, types = engine.names(text)
    aliases = [alias for station in stations for alias in engine.lexicon['stations'][station]]
    aliases += [alias for kind in types for alias in engine.lexicon['sensor_types'][kind]]
    return text + '\nPublic entity aliases: ' + ' '.join(dict.fromkeys(aliases))


def prepare_index(cache_dir):
    """Reuse the original paid embedding receipt, without any new API call."""
    if (INDEX / 'manifest.json').exists():
        return v.read(INDEX / 'manifest.json')
    rows = r3.row_corpus()
    encoder = r5.Engine(rows=rows)
    expected = [embedding_text(row, encoder) for row in rows]
    matches = []
    for request in Path(cache_dir).glob('*.request.json'):
        payload = v.read(request)
        if payload.get('model') == 'text-embedding-3-small' and payload.get('input', [])[:len(rows)] == expected:
            matches.append(request)
    if len(matches) != 1:
        raise ValueError('Need one matching existing v5 embedding receipt')
    request = matches[0]
    response_path = request.with_name(request.name.replace('.request.json', '.response.json'))
    response = v.read(response_path)
    payload = v.read(request)
    ordered = sorted(response['data'], key=lambda item: item['index'])
    assert [item['index'] for item in ordered[:len(rows)]] == list(range(len(rows)))
    matrix = v.normalized([item['embedding'] for item in ordered[:len(rows)]], len(rows), payload['dimensions'])
    INDEX.mkdir(parents=True, exist_ok=False)
    np.save(INDEX / 'vectors.npy', matrix, allow_pickle=False)
    manifest = {'rows': [row['chunk_id'] for row in rows], 'corpus_sha256': v.digest(v.encoded(rows)),
                'embedding_model': payload['model'], 'dimensions': payload['dimensions'],
                'vectors_sha256': v.digest((INDEX / 'vectors.npy').read_bytes()),
                'original_request_sha256': v.digest(request.read_bytes()),
                'original_response_sha256': v.digest(response_path.read_bytes()), 'new_api_calls': 0}
    v.write(INDEX / 'manifest.json', manifest)
    return manifest


class Retriever:
    def __init__(self, mode='auto'):
        if mode not in ('auto', 'vector', 'graph', 'full'):
            raise ValueError('Unknown document mode')
        self.mode = mode
        self.rows = r3.row_corpus()
        self.graph = c.load_graph()
        self.engine = r5.Engine(self.graph if mode == 'graph' else None, self.rows)
        self.max_tokens = 12000 if mode == 'full' else 4000
        self.manifest = None
        if mode != 'full':
            self.manifest = v.read(INDEX / 'manifest.json')
            if self.manifest['corpus_sha256'] != v.digest(v.encoded(self.rows)):
                raise ValueError('Document index has a different source corpus')
            if v.digest((INDEX / 'vectors.npy').read_bytes()) != self.manifest['vectors_sha256']:
                raise ValueError('Document vectors changed')
            self.vectors = np.load(INDEX / 'vectors.npy', allow_pickle=False)

    def lock(self):
        return {'backend': 'team-v5-' + self.mode, 'context_limit': self.max_tokens,
                'source_sha256': v.digest(v.SOURCE.read_bytes()),
                'kg_sha256': v.digest((v.REPO_ROOT / c.KG_REL).read_bytes()),
                'index': self.manifest, 'retrieval_code_sha256': v.digest(Path(__file__).read_bytes())}

    def retrieve(self, question, call):
        typed = []
        required = []
        if self.mode == 'full':
            context = '\n\n'.join(f"[{row['chunk_id']}] {row['doc_id']} p.{row['page']}\n{row['text']}" for row in self.rows)
            result = {'context': context, 'selected_ids': [row['chunk_id'] for row in self.rows],
                      'context_tokens': len(self.engine.encoder.encode(context, disallowed_special=())),
                      'trace': {'mode': 'all_fixed_document_rows'}}
            complete = True
        else:
            query, _ = v.embed([self.engine.expanded(question)], self.manifest, INDEX / 'query_cache', call=call)
            order = [row['chunk_id'] for row in v.retrieve(self.rows, self.vectors, query[0], len(self.rows))]
            system = {'auto': 'HybridRAG', 'vector': 'VectorRAG', 'graph': 'GraphRAG'}[self.mode]
            result = self.engine.retrieve(question, order, system, self.max_tokens)
            if self.mode != 'vector':
                required, typed = r4.typed_candidates(question, self.rows, self.graph)
                result = self.engine.pack(required + result['selected_ids'], self.max_tokens, system, result['trace'])
            complete = set(required).issubset(result['selected_ids']) if typed else None
        if result['context_tokens'] > self.max_tokens:
            raise ValueError('Document context exceeds the selected mode budget')
        by_id = {row['chunk_id']: row for row in self.rows}
        trace = {**result, 'typed_queries': typed, 'mode': self.mode}
        return {'context': result['context'], 'context_tokens': result['context_tokens'],
                'selected_ids': result['selected_ids'], 'sources': [by_id[cid] for cid in result['selected_ids']],
                'graph_paths': result['trace'].get('edges', []), 'retrieval_trace': trace,
                'coverage_required_ids': required, 'coverage_complete': complete,
                'coverage_scope': 'complete fixed document corpus' if self.mode == 'full' else 'typed query or retrieved excerpts',
                'retrieval_backend': 'team-v5-' + self.mode, 'dense_used': self.mode != 'full'}


QUERY_FIELDS = {'rules': {'sensor_id', 'station_id', 'source_document', 'action_target', 'rule_type'},
                'sensors': {'station_id'}, 'paths': {'start_station', 'end_station'}}


def validate_query(arguments):
    if not isinstance(arguments, dict) or arguments.get('operation') not in QUERY_FIELDS:
        raise ValueError('Unknown KG operation')
    operation = arguments['operation']
    if set(arguments) - {'operation'} - QUERY_FIELDS[operation]:
        raise ValueError('Unknown KG query field')
    if operation == 'sensors' and 'station_id' not in arguments:
        raise ValueError('Sensor query needs a station')
    if operation == 'paths' and not {'start_station', 'end_station'} <= arguments.keys():
        raise ValueError('Path query needs two stations')
    if any(not isinstance(value, str) or not value or len(value) > 128 for value in arguments.values()):
        raise ValueError('Invalid KG query value')
    return dict(arguments)


def query_kg(arguments):
    arguments = validate_query(arguments)
    engine = KGEngine()
    graph = engine.graph
    operation = arguments['operation']
    for field, kind in (('sensor_id', c.IM.Sensor), ('station_id', c.IM.Station),
                        ('start_station', c.IM.Station), ('end_station', c.IM.Station),
                        ('action_target', c.IM.Station), ('source_document', c.IM.Document)):
        if field in arguments and (arguments[field] not in engine.refs or
                                  (engine.refs[arguments[field]], RDF.type, kind) not in graph):
            raise ValueError('Unknown or mismatched KG identifier: ' + field)
    selected = set()
    if operation == 'rules':
        selected = engine.all_rules()
        if 'rule_type' in arguments:
            if arguments['rule_type'] not in ('OperationalRule', 'ThresholdRule', 'MaintenanceRule', 'AccessRule'):
                raise ValueError('Unknown rule type')
            selected &= set(graph.subjects(RDF.type, c.IM[arguments['rule_type']]))
        sensors = set()
        if 'sensor_id' in arguments:
            sensors.add(engine.refs[arguments['sensor_id']])
        if 'station_id' in arguments:
            station_sensors = set(graph.objects(engine.refs[arguments['station_id']], c.IM.hasSensor))
            sensors = sensors & station_sensors if sensors else station_sensors
        if 'sensor_id' in arguments or 'station_id' in arguments:
            selected = {node for node in selected if set(graph.objects(node, c.IM.appliesToSensor)) & sensors}
        for field, predicate in (('source_document', c.IM.sourceDocument), ('action_target', c.IM.actionTarget)):
            if field in arguments:
                selected = {node for node in selected if (node, predicate, engine.refs[arguments[field]]) in graph}
    elif operation == 'sensors':
        selected = set(graph.objects(engine.refs[arguments['station_id']], c.IM.hasSensor))
    else:
        paths = engine.paths(engine.refs[arguments['start_station']], engine.refs[arguments['end_station']])
        selected = {node for path in paths for node in path}
    def values(node, predicate):
        return sorted(str(value) if isinstance(value, Literal) else short(value) for value in graph.objects(node, predicate))
    items = []
    for node in sorted(selected, key=str):
        items.append({'identifier': values(node, c.IM.identifier),
                      **{field: values(node, c.IM[field]) for field in
                         ('unit', 'conditionText', 'responseText', 'sourceDocument', 'appliesToSensor', 'actionTarget')}})
    computed = {'query': arguments, 'count': len(paths) if operation == 'paths' else len(items), 'items': items,
                'scope': 'entire frozen KG; seed and candidate nodes remain distinct'}
    if operation == 'paths':
        computed['paths'] = [[short(node) for node in path] for path in paths]
    rows = [engine.by_id[engine.node_ids[node]] for node in sorted(selected, key=str)]
    edges = [{'s': str(node), 'p': str(predicate), 'o': str(target), 'depth': 1}
             for node in sorted(selected, key=str) for predicate, target in graph.predicate_objects(node)
             if isinstance(target, URIRef)]
    return computed, rows, edges
