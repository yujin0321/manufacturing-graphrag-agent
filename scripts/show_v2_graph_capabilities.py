"""Offline v2 queries, provenance checks and isolated fault injection; preserve QA results."""
import json
import zipfile
from pathlib import Path
from unittest.mock import patch
from rdflib import Graph, Literal, Namespace, RDF
from pyshacl import validate
from imaks_kg.rag import vector as v, comparison as c

ROOT = v.REPO_ROOT
OUT = ROOT / 'kg_build/v2_capabilities_20261028'
IM = c.IM
SH = Namespace('http://www.w3.org/ns/shacl#')
PREFIX = 'PREFIX im: <https://example.org/imaks/v1#>\n'
QUERIES = {
    'stop_targets': '''SELECT ?ruleId ?condition ?action ?targetId WHERE {
      ?rule im:identifier "candidate-SOP-001::RULE-ST02-02"; im:identifier ?ruleId;
            im:conditionText ?condition; im:responseText ?action; im:actionTarget ?target.
      ?target im:identifier ?targetId.
    } ORDER BY ?targetId''',
    'sensor_rules': '''SELECT DISTINCT ?ruleId ?docId WHERE {
      ?station im:identifier "SRV01_SERVERROOM"; im:hasSensor ?sensor.
      ?sensor im:sensorType "TMP".
      ?rule im:appliesToSensor ?sensor; im:identifier ?ruleId; im:sourceDocument ?doc.
      ?doc im:identifier ?docId.
    } ORDER BY ?ruleId ?docId''',
    'rule_provenance': '''SELECT ?ruleId ?docId ?page ?quote ?sha WHERE {
      VALUES ?ruleId { "candidate-SOP-001::RULE-ST02-02" "candidate-SOP-003::MAINT-05" }
      ?rule im:identifier ?ruleId; im:sourceDocument ?doc; im:hasProvenance ?prov.
      ?doc im:identifier ?docId.
      ?prov im:sourceKind "document"; im:page ?page; im:sourceQuote ?quote; im:textSha256 ?sha.
    } ORDER BY ?ruleId''',
}


def source_check(graph, prov, corpus):
    quote = str(graph.value(prov, IM.sourceQuote) or '')
    sha = str(graph.value(prov, IM.textSha256) or '')
    file_sha = str(graph.value(prov, IM.fileSha256) or '')
    page = str(graph.value(prov, IM.page) or '')
    matches = [r['chunk_id'] for r in corpus if r['source_file_sha256'] == file_sha
               and str(r['page']) == page and quote and quote in r['text']]
    return {'quote_hash_matches': v.digest(quote.encode()) == sha,
            'matching_chunks': matches, 'ok': bool(matches) and v.digest(quote.encode()) == sha}


def main():
    run = ROOT / 'kg_build/stored_edge_answers_20261028'
    review = ROOT / 'evaluation/stored_edge_answers_20261028'
    for p, h in v.read(run / 'complete.json')['files'].items():
        assert v.digest((run / p).read_bytes()) == h
    for p, h in v.read(review / 'review_seal.json')['hashes'].items():
        assert v.digest((ROOT / p).read_bytes()) == h
    assert v.digest((run / 'complete.json').read_bytes()) == v.read(review / 'review_seal.json')['api_generation_complete_sha256']
    baseline = [p for folder in [run, review] for p in folder.rglob('*') if p.is_file()]
    baseline += [ROOT / 'reports/stored_edge_answers_20261028_verify.md']
    protected = baseline + [ROOT / c.KG_REL, ROOT / 'ontology_v1/ontology.ttl', ROOT / 'ontology_v1/shapes.ttl']
    hashes = {p.relative_to(ROOT).as_posix(): v.digest(p.read_bytes()) for p in protected}
    OUT.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(OUT / 'qa_baseline.zip', 'x', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(baseline): z.write(p, p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(OUT / 'qa_baseline.zip') as z:
        assert z.testzip() is None
        assert all(v.digest(z.read(n)) == hashes[n] for n in z.namelist())
    v.write(OUT / 'baseline_manifest.json', {'hashes': hashes, 'archive_files': len(baseline),
            'archive_sha256': v.digest((OUT / 'qa_baseline.zip').read_bytes())})
    with patch('socket.socket', side_effect=AssertionError('Network forbidden')):
        graph = c.load_graph(); corpus, _ = v.source_records()
        ontology = Graph().parse(ROOT / 'ontology_v1/ontology.ttl')
        shapes = Graph().parse(ROOT / 'ontology_v1/shapes.ttl')
        results = {}
        for name, query in QUERIES.items():
            query = PREFIX + query
            (OUT / (name + '.rq')).write_text(query, encoding='utf-8')
            results[name] = [{str(k): str(val) for k, val in row.asdict().items()} for row in graph.query(query)]
            assert results[name]
        assert {r['targetId'] for r in results['stop_targets']} == {'ST02_SEALING', 'ST03_LABELLING', 'ST04_PACKAGING'}
        assert len(results['rule_provenance']) == 2
        rule = next(graph.subjects(IM.identifier, Literal('candidate-SOP-001::RULE-ST02-02')))
        prov = next(graph.objects(rule, IM.hasProvenance))
        provenance = []
        for label in ['candidate-SOP-001::RULE-ST02-02', 'candidate-SOP-003::MAINT-05']:
            node = next(graph.subjects(IM.identifier, Literal(label)))
            for p in graph.objects(node, IM.hasProvenance):
                check = source_check(graph, p, corpus)
                assert check['ok']
                provenance.append({'rule': label, 'provenance': str(p), **check})
        sensor = next(graph.subjects(IM.identifier, Literal('ST02_SEALING_CUR')))
        parent = next(graph.subjects(IM.hasSensor, sensor))
        cases = {}
        for name in ['original', 'sensor_without_station', 'rule_without_document',
                     'action_target_is_sensor', 'provenance_without_page', 'well_formed_wrong_hash']:
            trial = Graph()
            for triple in graph: trial.add(triple)
            if name == 'sensor_without_station': trial.remove((parent, IM.hasSensor, sensor))
            elif name == 'rule_without_document': trial.remove((rule, IM.sourceDocument, None))
            elif name == 'action_target_is_sensor': trial.add((rule, IM.actionTarget, sensor))
            elif name == 'provenance_without_page': trial.remove((prov, IM.page, None))
            elif name == 'well_formed_wrong_hash': trial.set((prov, IM.textSha256, Literal('0' * 64)))
            ok, report_graph, report = validate(trial, shacl_graph=shapes, ont_graph=ontology, inference='none')
            messages = sorted({str(m) for m in report_graph.objects(None, SH.resultMessage)})
            cases[name] = {'shacl_conforms': bool(ok), 'messages': messages,
                           'source_check': source_check(trial, prov, corpus)}
            (OUT / (name + '_shacl.txt')).write_text(report, encoding='utf-8')
            assert bool(ok) == (name in ['original', 'well_formed_wrong_hash'])
        assert not cases['well_formed_wrong_hash']['source_check']['ok']
        assert cases['original']['source_check']['ok']
    assert all(v.digest((ROOT / p).read_bytes()) == h for p, h in hashes.items())
    summary = {'api_calls': 0, 'gold_loaded': False, 'base_triples': len(graph), 'queries': results,
               'provenance_checks': provenance, 'validation_cases': cases,
               'protected_files_unchanged': True, 'script_sha256': v.digest(Path(__file__).read_bytes())}
    v.write(OUT / 'summary.json', summary)
    v.write(OUT / 'complete.json', {'hashes': {p.name: v.digest(p.read_bytes()) for p in OUT.iterdir() if p.is_file()}})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
