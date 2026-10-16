"""Audit graph provenance and source table fields, without evaluation answers."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from rdflib import Graph, Namespace

from imaks_kg.common.io_utils import write_json, write_jsonl
from imaks_kg.kg_build.document_nodes import load_jsonl
from imaks_kg.kg_build.preprocessed_abox import PreprocessedLayout
from imaks_kg.kg_build.rdf_export import iri_name
from imaks_kg.kg_build.rule_extract import sop002_threshold_table_contexts
from imaks_kg.kg_build.structure_completion import audit_graph


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def run(build_dir, preprocessed=None):
    root = Path(build_dir)
    layout = PreprocessedLayout.detect(preprocessed)
    nodes = load_jsonl(root / 'nodes.jsonl')
    rels = load_jsonl(root / 'relationships.jsonl')
    rules = load_jsonl(root / 'rules_extracted.jsonl')
    preds = load_jsonl(root / 'predictions.jsonl')
    provs = load_jsonl(root / 'provenance.jsonl')
    docs = load_jsonl(root / 'documents.jsonl')
    tables = load_jsonl(layout.tables_jsonl)
    pages = load_jsonl(layout.pages_jsonl)
    station_ids = {n['id'] for n in nodes if 'Station' in n['labels']}
    contexts = sop002_threshold_table_contexts(tables, pages, station_ids)
    expected, source_units = {}, {}
    for ctx in contexts:
        for row_index, row in enumerate(ctx['rows'], 1 if ctx['continuation'] else 2):
            d = dict(zip(ctx['header'], row))
            sid = ctx['station'] + '_' + d['Sensor']
            source_units[sid] = f"{ctx['table_id']}:row{row_index}"
            expected[sid] = {dst: Decimal(d[src].split('±')[0].strip()) for src, dst in
                             [('Nominal', 'nominal'), ('WARN_LO', 'warnLo'), ('WARN_HI', 'warnHi'),
                              ('CRIT_LO', 'critLo'), ('CRIT_HI', 'critHi')]}
    numeric_rows = []
    for sensor, values in expected.items():
        sensor_linked = [r for r in preds if r['document_id'] == 'SOP-002' and r['class'] == 'ThresholdRule'
                         and sensor in r['sensors'] and any(r.get('numeric', {}).values())]
        # A rule may mention a second sensor in its response. Its numeric fields
        # belong to the cited threshold table row, not every mentioned sensor.
        found = [r for r in sensor_linked if source_units[sensor] in
                 {e['unit_id'] for e in r['evidence']}]
        issues = []
        if len(found) != 1:
            issues.append('expected_one_numeric_rule')
        for r in found:
            for field, value in values.items():
                actual = r.get('numeric', {}).get(field, '')
                try:
                    agrees = bool(actual) and Decimal(actual).is_finite() and Decimal(actual) == value
                except InvalidOperation:
                    agrees = False
                if not agrees:
                    issues.append(field)
        numeric_rows.append({'sensor': sensor, 'source_unit': source_units[sensor],
                             'prediction_ids': [r['identifier'] for r in found],
                             'other_linked_rule_ids': [r['identifier'] for r in sensor_linked if r not in found],
                             'source_fields': {k: str(v) for k, v in values.items()}, 'issues': issues})
    maint_rows = []
    for table in tables:
        if table['document_id'] != 'SOP-003' or 'Rule ID' not in table['rows'][0]:
            continue
        for row in table['rows'][1:]:
            d = dict(zip(table['rows'][0], row))
            found = [r for r in preds if r['document_id'] == 'SOP-003' and r['printed_rule_id'] == d['Rule ID']]
            sid = d['Station'] + '_' + d['Sensor']
            maint_rows.append({'printed_rule_id': d['Rule ID'], 'prediction_ids': [r['identifier'] for r in found],
                               'source_priority': d['Priority'],
                               'priority_agrees': bool(found) and all(r.get('priority') == d['Priority'] for r in found),
                               'sensor_agrees': bool(found) and all(sid in r['sensors'] for r in found)})
    # Every RDF triple has a source record in a separate ledger. CSV inventory facts
    # are not mislabeled as seedCsv or causal time-window evidence in the ontology.
    csv_hash = sha(layout.sensor_input)
    inventory = {}
    with layout.sensor_input.open(encoding='utf-8-sig', newline='') as f:
        for line, row in enumerate(csv.DictReader(f), 2):
            source = {'file': str(layout.sensor_input), 'sha256': csv_hash, 'line': line,
                      'station_id': row['station_id'], 'sensor_id': row['sensor_id']}
            inventory.setdefault(row['station_id'], source)
            inventory.setdefault(row['sensor_id'], source)
    im = Namespace('https://example.org/imaks/v1#')
    inst = Namespace('https://example.org/imaks/instance/')
    owner = {}
    for n in nodes:
        owner[str(inst[iri_name(n['id'])])] = [inventory[n['id']]]
    for d in docs:
        owner[str(inst[iri_name(d['id'])])] = [d['properties']]
    for p in provs:
        owner[str(inst[iri_name(p['id'])])] = [p['properties']]
    for r in rules:
        owner[str(inst[iri_name(r['ruleId'])])] = [{'provenance_id': p, 'document_id': r['document_id']}
                                                for p in r['provenanceIds']]
    special = {}
    for r in rels:
        key = (str(inst[iri_name(r['source'])]), str(im[r['type']]), str(inst[iri_name(r['target'])]))
        special[key] = ([{'provenance_id': p, 'document_id': r['sourceDocument']} for p in r['provenanceIds']]
                        if r.get('provenanceIds') else [inventory[r['target']]])
        for pid in r.get('provenanceIds', []):
            special[(key[0], str(im.hasProvenance), str(inst[iri_name(pid)]))] = [
                {'provenance_id': pid, 'document_id': r['sourceDocument']}]
    g = Graph().parse(root / 'kg.ttl')
    ledger = []
    for s, p, o in sorted(g, key=lambda t: tuple(map(str, t))):
        sources = special.get((str(s), str(p), str(o)), owner.get(str(s), []))
        if not sources:
            raise ValueError(f'Triple has no source ledger entry: {s} {p}')
        ledger.append({'subject': s.n3(), 'predicate': p.n3(), 'object': o.n3(), 'sources': sources})
    write_jsonl(root / 'triple_sources.jsonl', ledger)
    write_json(root / 'source_field_audit.local.json', {'numeric_rows': numeric_rows, 'maintenance_rows': maint_rows})
    summary = audit_graph(root)
    summary.update({'source_numeric_sensor_rows': len(numeric_rows),
                    'source_numeric_rows_exact': sum(not r['issues'] for r in numeric_rows),
                    'numeric_sensors_with_cross_row_references': sum(bool(r['other_linked_rule_ids']) for r in numeric_rows),
                    'source_maintenance_rows': len(maint_rows),
                    'source_maintenance_priority_agrees': sum(r['priority_agrees'] for r in maint_rows),
                    'source_maintenance_sensor_agrees': sum(r['sensor_agrees'] for r in maint_rows),
                    'ledger_entries': len(ledger), 'ledger_complete': len(ledger) == len(g),
                    'kg_sha256': sha(root / 'kg.ttl'), 'prediction_sha256': sha(root / 'predictions.jsonl')})
    write_json(root / 'kg_audit.json', summary)
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build-dir', required=True)
    p.add_argument('--preprocessed')
    args = p.parse_args()
    print(json.dumps(run(args.build_dir, args.preprocessed), ensure_ascii=False, indent=2))
