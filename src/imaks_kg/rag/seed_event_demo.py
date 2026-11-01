"""Explicit gold-provided demonstration only. Never imported by normal QA."""
import argparse
import html
from pathlib import Path
from urllib.parse import quote
from rdflib import Graph, Namespace, RDF, Literal, URIRef
from imaks_kg.common.raw_io import raw_csv_rows, raw_sha256
from imaks_kg.settings import IMAKS_DATA
from . import comparison as c, vector as v

EX = Namespace('https://example.org/imaks/gold-demo/v1#')
OUT = v.REPO_ROOT / 'kg_build/gold_event_demo_20261028'
NOTICE = '정답 이벤트를 제공받은 시연입니다. 탐지 성능 평가·신규 이상 발견 결과가 아닙니다.'


def query_event(base, overlay, gt_id):
    matches = list(overlay.subjects(EX.gtId, Literal(gt_id)))
    if len(matches) != 1:
        raise ValueError('Unknown or duplicate event')
    event = matches[0]
    sensors = list(overlay.objects(event, EX.observedSensor))
    paths, rules = [], []
    for sensor in sensors:
        paths.append([str(event), str(EX.observedSensor), str(sensor)])
        for rule in sorted(set(base.subjects(c.IM.appliesToSensor, sensor)), key=str):
            docs = sorted(str(d) for d in base.objects(rule, c.IM.sourceDocument))
            prov = sorted(str(d) for d in base.objects(rule, c.IM.hasProvenance))
            rules.append({'iri': str(rule), 'documents': docs, 'provenance': prov,
                          'conditions': [str(x) for x in base.objects(rule, c.IM.conditionText)],
                          'actions': [str(x) for x in base.objects(rule, c.IM.responseText)]})
            paths.append([str(rule), str(c.IM.appliesToSensor), str(sensor)])
            paths.extend([str(rule), str(c.IM.sourceDocument), doc] for doc in docs)
    return {'mode': 'gold_provided_demo', 'gold_loaded': True, 'evaluation_run': False,
            'notice': NOTICE, 'gt_id': gt_id, 'event_iri': str(event),
            'sensors': [str(x) for x in sensors], 'related_rules': rules, 'paths': paths,
            'rule_note': '센서에 연결된 규칙 목록이며 해당 사건의 원인·충족 규칙·조치 정답으로 판정한 결과가 아닙니다.'}


def build(output=OUT):
    output = Path(output)
    if output.exists():
        raise FileExistsError('Do not overwrite an existing demo')
    base = c.load_graph()
    base_hash = v.digest((v.REPO_ROOT / c.KG_REL).read_bytes())
    node_path, edge_path = (IMAKS_DATA / 'kg_seed' / f for f in ('nodes.csv', 'edges.csv'))
    _, nodes = raw_csv_rows(node_path)
    _, edges = raw_csv_rows(edge_path)
    node_hash, edge_hash = raw_sha256(node_path), raw_sha256(edge_path)
    events = [n for n in nodes if n['label'] == 'AnomalyEvent']
    if len(events) != 14 or len({n['gtId'] for n in events}) != 14 or any(not n['gtId'] for n in events):
        raise ValueError('Expected 14 unique source events')
    by_id = {n['nodeId']: n for n in nodes}
    overlay = Graph()
    overlay.bind('demo', EX)
    mapping, queries = [], []
    for n in events:
        uri = URIRef('https://example.org/imaks/gold-demo/event/' + quote(n['gtId'], safe=''))
        overlay.add((uri, RDF.type, EX.ProvidedAnomalyEvent))
        # Preserve nonempty source cells as literals without inferring units or causes.
        for key, value in n.items():
            if value:
                overlay.add((uri, EX[key], Literal(value)))
        overlay.add((uri, EX.sourceFile, Literal('kg_seed/nodes.csv')))
        overlay.add((uri, EX.sourceSha256, Literal(node_hash)))
        overlay.add((uri, EX.goldProvided, Literal(True)))
        source_edges = []
        for line, e in enumerate(edges, 2):
            if e['toId'] != n['nodeId'] or e['type'] != 'triggers':
                continue
            sensor = by_id[e['fromId']]
            if sensor['label'] != 'Sensor':
                raise ValueError('Expected sensor source')
            targets = list(base.subjects(c.IM.sourceNodeId, Literal(sensor['nodeId'])))
            targets = [s for s in targets if (s, RDF.type, c.IM.Sensor) in base]
            if len(targets) != 1:
                raise ValueError('Ambiguous v2 sensor mapping')
            overlay.add((uri, EX.observedSensor, targets[0]))
            claim = URIRef(str(uri) + '/edge/' + str(line))
            overlay.add((uri, EX.mappingEvidence, claim))
            for key, val in {'sourceFile': 'kg_seed/edges.csv', 'sourceSha256': edge_hash,
                             'sourceLine': str(line), 'originalPredicate': e['type'],
                             'sourceNodeId': e['fromId'], 'targetNodeId': e['toId']}.items():
                overlay.add((claim, EX[key], Literal(val)))
            source_edges.append({'line': line, 'source_node': sensor['nodeId'],
                                 'sensor_name': sensor['name'], 'sensor_iri': str(targets[0])})
        if len(source_edges) != 1:
            raise ValueError('Expected one sensor link per event')
        mapping.append({'gt_id': n['gtId'], 'source_node': n['nodeId'], 'event_iri': str(uri),
                        'source_fields': {k: val for k, val in n.items() if val}, 'edges': source_edges})
        queries.append(query_event(base, overlay, n['gtId']))
    output.mkdir(parents=True)
    overlay.serialize(output / 'events.ttl', format='turtle')
    v.write(output / 'mapping.json', mapping)
    v.write(output / 'queries.json', queries)
    manifest = {'mode': 'gold_provided_demo', 'gold_loaded': True, 'evaluation_run': False,
                'notice': NOTICE, 'event_count': 14, 'overlay_triples': len(overlay),
                'base_triples': len(base), 'base_sha256': base_hash,
                'source_hashes': {'kg_seed/nodes.csv': node_hash, 'kg_seed/edges.csv': edge_hash},
                'api_calls': 0, 'code_sha256': v.digest(Path(__file__).read_bytes()),
                'mapping_note': 'Original Sensor triggers Event is represented as Event observedSensor Sensor for demo lookup; no causal claim.'}
    v.write(output / 'manifest.json', manifest)
    rows = []
    for m, q in zip(mapping, queries):
        fields = ''.join('<tr><th>'+html.escape(k)+'</th><td>'+html.escape(val)+'</td></tr>' for k, val in m['source_fields'].items())
        rule_rows = ''.join('<li>'+html.escape(r['iri'])+'<br>문서: '+html.escape(', '.join(r['documents']))+'</li>' for r in q['related_rules'])
        paths = '\n'.join(' → '.join(p) for p in q['paths'])
        rows.append('<details><summary>'+html.escape(m['gt_id']+' · '+m['edges'][0]['sensor_name'])+'</summary><table>'+fields+'</table><p>'+html.escape(q['rule_note'])+'</p><ul>'+rule_rows+'</ul><pre>'+html.escape(paths)+'</pre></details>')
    page = '<!doctype html><html lang="ko"><meta charset="utf-8"><title>정답 이벤트 14건 · 별도 시연</title><style>body{font:16px/1.7 system-ui;max-width:1100px;margin:30px auto;padding:20px;background:#f5f7f6}aside{background:#fff0cc;padding:18px}details{background:white;margin:14px 0;padding:18px;border:1px solid #ccd8d0}summary{cursor:pointer;font-weight:bold}td,th{border-bottom:1px solid #ddd;padding:6px;text-align:left}pre,li{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>정답 이벤트 14건 · 별도 시연</h1><aside>'+NOTICE+'</aside><p>기본 예원 v2는 변경하지 않았습니다. 원본 이벤트 → 센서 → 기존 규칙·출처를 조회합니다. magnitude의 단위나 원인·조치를 임의로 추정하지 않습니다. API 호출 없음.</p>'+''.join(rows)+'</html>'
    (output / 'index.html').write_text(page, encoding='utf-8')
    if v.digest((v.REPO_ROOT / c.KG_REL).read_bytes()) != base_hash:
        raise ValueError('Base changed')
    v.write(output / 'complete.json', {p.name: v.digest(p.read_bytes()) for p in output.iterdir() if p.is_file()})
    return manifest


def verify(output=OUT):
    output = Path(output)
    seal = v.read(output / 'complete.json')
    required = {'events.ttl', 'mapping.json', 'queries.json', 'manifest.json', 'index.html'}
    if set(seal) != required:
        raise ValueError('Incomplete seal')
    for name, checksum in seal.items():
        if v.digest((output / name).read_bytes()) != checksum:
            raise ValueError('Demo integrity failure')
    return v.read(output / 'manifest.json')


def serve(output=OUT, port=8769):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    output = Path(output)
    verify(output)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}' or self.path != '/':
                self.send_error(404)
                return
            verify(output)
            body = (output / 'index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', port), Handler)
    print(f'GOLD-PROVIDED DEMO ONLY: http://127.0.0.1:{server.server_port}/', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Build separate gold-provided demo; no API')
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--port', type=int, default=8769)
    args = parser.parse_args()
    if args.serve:
        serve(args.output, args.port)
    else:
        print(verify(args.output) if args.verify else build(args.output))
