"""Reproducible shared preprocessing, isolated from existing experiment outputs."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pdfplumber
from pypdf import PdfReader
import pypdfium2 as pdfium
from PIL import Image, ImageDraw

from preprocess_mqtt_input import sanitize, verify_preserved

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'preprocessed' / 'common_v1'
THRESHOLDS = ['nominal', 'warn_hi', 'crit_hi', 'warn_lo', 'crit_lo']
OBSERVATIONS = ['timestamp', 'zone', 'station_id', 'sensor_id', 'sensor_type', 'value', 'unit']
KEYS = ['sensor_id', 'timestamp']


def csv(df, name):
    target = OUT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(target, index=False, encoding='utf-8-sig', float_format='%.15g')
    return target


def js(value, name):
    target = OUT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str) + '\n', encoding='utf-8')


def rec(df):
    return json.loads(df.to_json(orient='records', force_ascii=False))


def split(times):
    return np.where(times < pd.Timestamp('2026-01-07'), 'train',
                    np.where(times < pd.Timestamp('2026-01-08'), 'validation', 'test'))


def sources(z):
    names = ['sensors/timeseries_raw.csv', 'sensors/timeseries_annotated.csv',
             'kg_seed/nodes.csv', 'kg_seed/edges.csv', 'kg_seed/ground_truth.csv',
             'human/access_events.csv', 'human/alarm_response_log.csv', 'human/person_registry.csv']
    return {name: pd.read_csv(z.open(name), low_memory=False) for name in names}


def prepare_sensors(d, z):
    raw = d['sensors/timeseries_raw.csv'].copy()
    ann = d['sensors/timeseries_annotated.csv']
    nodes = d['kg_seed/nodes.csv']
    edges = d['kg_seed/edges.csv']
    assert raw[KEYS].equals(ann[KEYS]) and raw.value.equals(ann.value)
    raw['source_row'] = np.arange(len(raw)) + 2  # One-based CSV line including header.
    ts = pd.to_datetime(raw.timestamp, errors='coerce')
    values = pd.to_numeric(raw.value, errors='coerce')
    duplicate_keys = raw.duplicated(KEYS, keep=False)
    bad_times = ts.isna()
    bad_values = values.isna() | ~np.isfinite(values)
    whitespace = {key: int(raw[key].ne(raw[key].astype(str).str.strip()).sum())
                  for key in ['sensor_id', 'station_id', 'sensor_type', 'unit']}
    sensor_nodes = nodes[nodes.label.eq('Sensor')]
    assert not nodes.nodeId.duplicated().any()
    assert not sensor_nodes.name.duplicated().any()
    id_lookup = nodes.set_index('nodeId')
    mappings = []
    for edge in edges[edges.type.eq('monitors')].itertuples():
        a, b = id_lookup.loc[edge.fromId], id_lookup.loc[edge.toId]
        if a.label == 'Component' and b.label == 'Sensor':
            mappings.append({'sensor_id': b['name'], 'sensor_node_id': edge.toId,
                             'station_id': a['name'], 'station_node_id': edge.fromId,
                             'sensor_type': b.sensorType, 'unit': b.unit})
    mapping = pd.DataFrame(mappings).sort_values('sensor_id').reset_index(drop=True)
    assert len(mapping) == 22 and not mapping.sensor_id.duplicated().any()
    joined = raw[['sensor_id', 'station_id', 'sensor_type', 'unit']].drop_duplicates().merge(
        mapping, on='sensor_id', how='outer', suffixes=('_csv', '_kg'), indicator=True, validate='one_to_one')
    unmapped = joined['_merge'].ne('both')
    mismatched = pd.Series(False, index=joined.index)
    for c in ['station_id', 'sensor_type', 'unit']:
        mismatched |= joined[f'{c}_csv'].ne(joined[f'{c}_kg'])
    csv(mapping, 'metadata/sensor_id_mapping.csv')
    csv(joined.loc[unmapped | mismatched], 'audit/sensor_mapping_issues.csv')
    invalid = raw.loc[bad_times | bad_values | duplicate_keys].copy()
    csv(invalid, 'audit/invalid_sensor_rows.csv')
    profile = pd.DataFrame([{'column': c, 'dtype': str(raw[c].dtype),
                             'missing': int(raw[c].isna().sum()), 'unique': int(raw[c].nunique())}
                            for c in raw.columns if c != 'source_row'])
    csv(profile, 'audit/sensor_column_profile.csv')
    summary = {'rows': len(raw), 'sensors': int(raw.sensor_id.nunique()),
               'invalid_timestamps': int(bad_times.sum()), 'invalid_or_nonfinite_values': int(bad_values.sum()),
               'duplicate_sensor_timestamp_rows': int(duplicate_keys.sum()),
               'id_or_unit_whitespace': whitespace, 'mapping_issue_rows': int((unmapped | mismatched).sum()),
               'units': rec(raw[['sensor_type', 'unit']].drop_duplicates()),
               'start': str(ts.min()), 'end': str(ts.max()), 'timezone': 'Unspecified in source; preserved without UTC conversion.'}
    js(summary, 'audit/sensor_quality.json')
    if bad_times.any() or bad_values.any() or duplicate_keys.any() or (unmapped | mismatched).any() or any(whitespace.values()):
        raise ValueError('Sensor integrity issue requires explicit resolution; see audit files.')
    # Stable keyed order, without resampling, interpolation or modifying observations.
    ordered = raw.sort_values(KEYS, kind='stable').reset_index(drop=True)
    ordered_ts = pd.to_datetime(ordered.timestamp)
    delta = ordered_ts.groupby(ordered.sensor_id).diff().dt.total_seconds()
    ordered['_delta'] = delta
    csv(ordered.groupby(['sensor_id', '_delta']).size().rename('count').reset_index().rename(columns={'_delta': 'interval_seconds'}),
        'audit/sampling_intervals.csv')
    csv(ordered.loc[delta.notna() & delta.ne(30), ['sensor_id', 'timestamp', 'source_row', '_delta']],
        'audit/sampling_gaps.csv')
    stats = ordered.groupby(['sensor_id', 'unit']).agg(rows=('value', 'size'), start=('timestamp', 'min'),
                end=('timestamp', 'max'), minimum=('value', 'min'), maximum=('value', 'max')).reset_index()
    csv(stats, 'audit/sensor_summary.csv')
    clock = np.where(ordered_ts.dt.hour.between(6, 13), 'Morning',
                     np.where(ordered_ts.dt.hour.between(14, 21), 'Afternoon', 'OFF_SHIFT'))
    metadata = ordered[KEYS + ['source_row', 'day', 'shift', 'batch_id']].rename(
        columns={'day': 'original_day', 'shift': 'original_shift', 'batch_id': 'original_batch_id'})
    metadata['calendar_date'] = ordered_ts.dt.strftime('%Y-%m-%d')
    metadata['calendar_day_index'] = (ordered_ts.dt.normalize() - ts.min().normalize()).dt.days + 1
    metadata['clock_shift'] = clock
    metadata['split'] = split(ordered_ts)
    metadata['segment_id'] = ((delta.isna() | delta.ne(30)) | metadata['split'].ne(metadata['split'].shift())).cumsum()
    csv(metadata, 'metadata/sensor_time_metadata.csv')
    # Time labels and source-row identifiers are excluded from ML feature files.
    csv(ordered[OBSERVATIONS], 'inputs/sensors/timeseries_ml_input.csv')
    csv(ordered[OBSERVATIONS + THRESHOLDS], 'inputs/sensors/timeseries_rule_input.csv')
    js({'allowed_model_features': ['value'], 'grouping_keys': ['sensor_id', 'timestamp'],
        'other_columns': 'Metadata only; feature expansion must be documented.',
        'threshold_columns_allowed_for_rule_only': THRESHOLDS,
        'forbidden_for_both': ['quality', 'anomaly_label', 'severity', 'alarm_flag', 'gt_id'],
        'clock_shift_policy': 'Morning [06:00,14:00), Afternoon [14:00,22:00), else OFF_SHIFT.',
        'windowing': 'No common normalization/windows/features. Each experiment records parameters and uses trailing windows reset at sensor/gap/split boundaries.'},
        'metadata/input_policy.json')
    payloads = json.loads(z.read('sensors/mqtt_payloads.json'))
    removed = Counter()
    clean = sanitize(payloads, removed)
    verify_preserved(payloads, clean)
    js(clean, 'inputs/sensors/mqtt_stream_input.json')
    js({'messages': len(clean), 'removed': dict(removed), 'ordering': 'Original stream order preserved; not reordered to match CSV.',
        'csv_alignment': 'MQTT and CSV are independent observation files; key/value alignment is audited, not assumed.'}, 'audit/mqtt_summary.json')
    mqtt_rows = [{'sensor_id': f"{m['device']['id']}_{code}", 'timestamp': m['timestamp'], 'mqtt_value': reading['value']}
                 for m in clean for code, reading in m['readings'].items()]
    mq = pd.DataFrame(mqtt_rows)
    aligned = mq.merge(raw[['sensor_id', 'timestamp', 'value']], on=KEYS, how='left', validate='many_to_one')
    js({'mqtt_readings': len(mq), 'matched_sensor_times': int(aligned.value.notna().sum()),
        'same_values': int(aligned.mqtt_value.eq(aligned.value).sum()),
        'different_values': int((aligned.value.notna() & aligned.mqtt_value.ne(aligned.value)).sum()),
        'policy': 'Do not concatenate as duplicate measurements or overwrite CSV values. Report stream and CSV experiments separately.'},
        'audit/mqtt_csv_alignment.json')
    summary['non_30s_intervals'] = int((delta.notna() & delta.ne(30)).sum())
    summary['observation_values_changed'] = 0
    return raw, metadata, mapping, summary


def prepare_documents(z):
    manifest, pages, tables, words = [], [], [], []
    glyph_changes = []
    # Exact-cell corrections checked against pypdf text and rendered source.
    glyph_fixes = {
        ('SOP-002:p2:table6', 1, 1): ('Transient deviation >3s, <5\nmin', 'Transient deviation >3σ, <5\nmin'),
        ('SOP-002:p2:table6', 2, 2): ('Slope >0.1s/min for 5+\nreadings', 'Slope >0.1σ/min for 5+\nreadings'),
        ('SOP-003:p1:table2', 1, 0): ('ST02_SEALING-CUR›\nfi ST04_PACKAGING-\nSPDfl', 'ST02_SEALING-CUR↑\n→ ST04_PACKAGING-\nSPD↓'),
        ('SOP-003:p1:table2', 2, 0): ('SRV01-TMP› fi\nSCADA latency›', 'SRV01-TMP↑ →\nSCADA latency↑'),
        ('SOP-003:p1:table2', 2, 2): ('Increased scan time fi\napparent STUCK\nreadings', 'Increased scan time →\napparent STUCK\nreadings'),
        ('SOP-003:p1:table2', 3, 0): ('WRH01-TMP› fi QC\nHOLD', 'WRH01-TMP↑ → QC\nHOLD'),
    }
    tiles = []
    for source in sorted(p for p in z.namelist() if p.endswith('.pdf') and p.startswith(('rules/', 'datasheets/'))):
        blob = z.read(source)
        doc_id = re.search(r'SOP_(\d+)', source)
        doc_id = f'SOP-{doc_id.group(1)}' if doc_id else Path(source).stem.upper()
        target = OUT / 'documents' / 'originals' / Path(source).name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        reader = PdfReader(io.BytesIO(blob))
        renderer = pdfium.PdfDocument(blob)
        with pdfplumber.open(io.BytesIO(blob)) as plumber:
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ''
                assert text.strip(), f'No extracted text: {source} p{i+1}'
                page_id = f'{doc_id}:p{i+1}'
                # Original pypdf text is retained; layout variant preserves table spacing.
                plain = OUT / 'documents' / 'text' / f'{doc_id}_p{i+1}.txt'
                plain.parent.mkdir(parents=True, exist_ok=True)
                plain.write_text(text, encoding='utf-8')
                layout = page.extract_text(extraction_mode='layout') or ''
                plain.with_name(f'{doc_id}_p{i+1}_layout.txt').write_text(layout, encoding='utf-8')
                offset, lines = 0, []
                for number, line in enumerate(text.splitlines(keepends=True), 1):
                    lines.append({'line': number, 'start': offset, 'end': offset+len(line), 'text': line.rstrip('\r\n')})
                    offset += len(line)
                assert offset == len(text)
                pages.append({'doc_id': doc_id, 'page_id': page_id, 'source': source, 'page': i+1,
                              'text': text, 'lines': lines, 'width': float(page.mediabox.width),
                              'height': float(page.mediabox.height), 'text_path': str(plain.relative_to(OUT))})
                p = plumber.pages[i]
                page_words = p.extract_words()
                words.append({'page_id': page_id, 'words': page_words, 'text_status': 'Raw pdfplumber words; glyphs may differ from pypdf. Use pages text or corrected table cells for retrieval.', 'coordinate_system': 'PDF points; x from left, top/bottom from top'})
                for j, table in enumerate(p.find_tables(), 1):
                    table_id = f'{page_id}:table{j}'
                    raw_cells = table.extract()
                    cells = [list(row) for row in raw_cells]
                    for (target_id, row, col), (before, after) in glyph_fixes.items():
                        if table_id == target_id:
                            assert cells[row][col] == before
                            assert re.sub(r'\s+', '', after) in re.sub(r'\s+', '', text)
                            cells[row][col] = after
                            glyph_changes.append({'table_id': table_id, 'row_zero_based': row,
                                                  'column_zero_based': col, 'before': before, 'after': after,
                                                  'evidence': 'Same-page pypdf text and rendered PDF'})
                    tables.append({'table_id': table_id, 'page_id': page_id,
                                   'doc_id': doc_id, 'page': i+1, 'bbox': list(table.bbox),
                                   'cells_raw_pdfplumber': raw_cells, 'cells': cells,
                                   'continues_table': 'SOP-002:p1:table5' if table_id == 'SOP-002:p2:table1' else None})
                image = renderer[i].render(scale=1.4).to_pil().convert('RGB')
                image_dir = OUT / 'documents' / 'renders'
                image_dir.mkdir(parents=True, exist_ok=True)
                image.save(image_dir / f'{doc_id}_p{i+1}.png')
                image.thumbnail((420, 594))
                tile = Image.new('RGB', (440, 625), 'white')
                tile.paste(image, (10, 25))
                ImageDraw.Draw(tile).text((10, 5), page_id, fill='black')
                tiles.append(tile)
        renderer.close()
        manifest.append({'doc_id': doc_id, 'source': source, 'pages': len(reader.pages),
                         'sha256': hashlib.sha256(blob).hexdigest(),
                         'pdf_path': str(target.relative_to(OUT)), 'source_header': pages[-len(reader.pages)]['text'].splitlines()[:2]})
    assert len(manifest) == 7
    assert len(glyph_changes) == len(glyph_fixes)
    js(manifest, 'documents/document_manifest.json')
    js(pages, 'documents/pages.json')
    js(tables, 'documents/tables.json')
    js(words, 'documents/words.json')
    js(glyph_changes, 'audit/document_glyph_corrections.json')
    sheet = Image.new('RGB', (440*3, 625*((len(tiles)+2)//3)), '#dddddd')
    for j, tile in enumerate(tiles):
        sheet.paste(tile, ((j%3)*440, (j//3)*625))
    sheet.save(OUT / 'documents' / 'contact_sheet.png')
    return {'documents': len(manifest), 'pages': len(pages), 'tables': len(tables),
            'table_cells_glyph_corrected': len(glyph_changes)}, pages


def prepare_graph(d, mapping):
    nodes, edges = d['kg_seed/nodes.csv'].copy(), d['kg_seed/edges.csv'].copy()
    assert not nodes.nodeId.duplicated().any()
    ids = set(nodes.nodeId)
    orphan = ~edges.fromId.isin(ids) | ~edges.toId.isin(ids)
    csv(edges.loc[orphan], 'audit/orphan_edges.csv')
    assert not orphan.any(), 'Unresolved edge endpoint; no silent deletion.'
    # Preserve full evaluation graph separately. Exclude dynamic event/maintenance history from inputs.
    csv(nodes, 'evaluation/kg/nodes_original.csv')
    csv(edges, 'evaluation/kg/edges_original.csv')
    duplicates = edges.duplicated(['fromId', 'toId', 'type', 'ruleRef'])
    csv(edges[duplicates], 'audit/exact_duplicate_edges.csv')
    allowed_labels = {'System', 'Zone', 'Component', 'Sensor', 'Person'}
    static = nodes[nodes.label.isin(allowed_labels)].copy()
    # Explicit static fields: no GT/severity/causedBy/threshold data can enter through nodes.
    fields = ['nodeId', 'label', 'name', 'stationType', 'sensorType', 'unit', 'zone', 'line', 'personId', 'role', 'dept', 'csiSubject']
    static = static[fields]
    static_ids = set(static.nodeId)
    canonical, lineage, excluded = [], [], []
    sensor_by_pair = {(r.station_node_id, r.sensor_node_id) for r in mapping.itertuples()}
    seen = {}
    for source_index, edge in edges.iterrows():
        original = {'source_row': int(source_index+2), **edge.to_dict()}
        if edge.fromId not in static_ids or edge.toId not in static_ids:
            excluded.append({**original, 'reason': 'Dynamic event/maintenance endpoint; evaluation only'})
            continue
        a, b, kind = edge.fromId, edge.toId, edge.type
        if kind == 'monitors':
            if (a, b) in sensor_by_pair:
                pass
            elif (b, a) in sensor_by_pair:
                a, b = b, a
            else:
                raise ValueError('Unexpected monitors endpoints')
            kind = 'has_sensor'
        rule = '' if pd.isna(edge.ruleRef) else edge.ruleRef
        key = (a, b, kind, rule)
        if key not in seen:
            seen[key] = f'E{len(canonical)+1:04d}'
            canonical.append({'edge_id': seen[key], 'fromId': a, 'toId': b, 'type': kind, 'ruleRef': rule})
        lineage.append({**original, 'canonical_edge_id': seen[key]})
    canonical = pd.DataFrame(canonical)
    assert set(canonical.fromId) <= static_ids and set(canonical.toId) <= static_ids
    assert int(canonical.type.eq('has_sensor').sum()) == 22
    csv(static, 'inputs/kg/nodes_static.csv')
    csv(canonical, 'inputs/kg/edges_static.csv')
    csv(pd.DataFrame(lineage), 'audit/edge_lineage.csv')
    csv(pd.DataFrame(excluded), 'audit/excluded_dynamic_edges.csv')
    csv(nodes[~nodes.label.isin(allowed_labels)], 'evaluation/kg/excluded_dynamic_nodes.csv')
    factory = d.get('kg_seed/nodes_factory.csv')
    js({'nodes_source': 'kg_seed/nodes.csv', 'excluded_source': 'kg_seed/nodes_factory.csv',
        'reason': 'Legacy conflicting IDs; do not merge.',
        'component_mapping': 'Original Component label preserved; station-level semantics documented for later ontology mapping.',
        'monitor_direction': 'Station-level Component -> has_sensor -> Sensor',
        'correlation': 'Existing correlates_with relation has SOP ruleRef; preserved as document-backed prior, not discovery evidence.',
        'raw_thresholds': 'Removed from static node view. ML must not retrieve thresholds from rules/docs/graph as features.'}, 'metadata/graph_policy.json')
    return {'original_nodes': len(nodes), 'original_edges': len(edges), 'static_nodes': len(static),
            'static_edges': len(canonical), 'dynamic_nodes_separated': len(nodes)-len(static),
            'dynamic_edges_separated': len(excluded), 'duplicate_monitor_edges_collapsed': 22,
            'orphan_edges': int(orphan.sum()), 'exact_duplicate_edges': int(duplicates.sum())}


def prepare_truth(d, raw, metadata, pages):
    ann, nodes, edges = d['sensors/timeseries_annotated.csv'], d['kg_seed/nodes.csv'], d['kg_seed/edges.csv']
    labels = ann[KEYS + ['anomaly_label', 'severity', 'alarm_flag']].rename(columns={'severity': 'dataset_severity'})
    labels = labels.merge(metadata[KEYS + ['source_row', 'split']], on=KEYS, validate='one_to_one')
    csv(labels.sort_values(KEYS), 'evaluation/row_labels.csv')
    event_nodes = nodes[nodes.label.eq('AnomalyEvent')]
    records = []
    for event in event_nodes.itertuples():
        links = edges[edges.type.eq('triggers') & edges.toId.eq(event.nodeId)]
        assert len(links) == 1
        sensor = nodes.loc[nodes.nodeId.eq(links.iloc[0].fromId), 'name'].iloc[0]
        start, end = pd.Timestamp(event.startTs), pd.Timestamp(event.endTs)
        for boundary in [pd.Timestamp('2026-01-07'), pd.Timestamp('2026-01-08')]:
            assert not start < boundary <= end, 'Event split by boundary'
        rows = raw[raw.sensor_id.eq(sensor) & raw.timestamp.between(event.startTs, event.endTs)]
        severe = rows.value.lt(rows.crit_lo) | rows.value.gt(rows.crit_hi)
        warning = rows.value.lt(rows.warn_lo) | rows.value.gt(rows.warn_hi)
        rule_severity = 'CRITICAL' if severe.any() else ('WARNING' if warning.any() else 'NORMAL')
        labelled = ann[ann.sensor_id.eq(sensor) & ann.timestamp.between(event.startTs, event.endTs)]
        assert len(rows) and labelled.anomaly_label.eq(event.anomalyType).all()
        assert labelled.severity.eq(event.severity).all()
        records.append({'event_id': event.gtId, 'node_id': event.nodeId, 'sensor_id': sensor,
                        'start': event.startTs, 'end': event.endTs, 'anomaly_type': event.anomalyType,
                        'dataset_severity': event.severity, 'rule_severity': rule_severity,
                        'severity_conflict': event.severity != rule_severity, 'critical_rows': int(severe.sum()),
                        'event_rows': len(rows), 'split': split(pd.Series([start]))[0]})
    events = pd.DataFrame(records).sort_values('start')
    assert len(events) == 14 and not events.event_id.duplicated().any()
    assert int(events.event_rows.sum()) == int(ann.anomaly_label.ne('NORMAL').sum())
    csv(events, 'evaluation/anomaly_events.csv')
    csv(events[events.severity_conflict], 'audit/severity_conflicts.csv')
    gt = d['kg_seed/ground_truth.csv'].copy()
    csv(gt, 'evaluation/rules_ground_truth_original.csv')
    corrected = gt.copy()
    changes = []
    expected = {'RULE-ST04-03': {'critLo': .85},
                'RULE-THR-ST03-SPD-CRIT': {'critLo': .65, 'warnLo': .75, 'warnHi': .95},
                'RULE-THR-ST04-SPD-CRIT': {'critLo': .85}}
    for rule, fields in expected.items():
        selected = corrected.ruleId.eq(rule)
        assert selected.sum() == 1
        for field, value in fields.items():
            changes.append({'ruleId': rule, 'field': field, 'before': float(corrected.loc[selected, field].iloc[0]),
                            'after': value, 'source': 'SOP-002 p.1; verified against raw sensor settings'})
            corrected.loc[selected, field] = value
    assert len(gt) == len(corrected) == 86
    csv(corrected, 'evaluation/rules_ground_truth_spd_corrected.csv')
    csv(pd.DataFrame(changes), 'audit/rule_correction_log.csv')
    # Extracted reference rules remain entirely outside the retrieval corpus.
    access = d['human/access_events.csv'].copy()
    within = pd.to_datetime(access.timestamp).between(pd.to_datetime(raw.timestamp).min(), pd.to_datetime(raw.timestamp).max())
    access['in_sensor_range'] = within
    access['person_resolution'] = np.where(access.person_id.eq('UNKNOWN'), 'unresolved', 'registered')
    access['unknown_event_key'] = np.where(access.person_id.eq('UNKNOWN'), access.event_id, '')
    registry = set(d['human/person_registry.csv'].person_id)
    assert set(access.loc[access.person_resolution.eq('registered'), 'person_id']) <= registry
    csv(access[within], 'evaluation/human/access_in_sensor_range.csv')
    csv(access[~within], 'evaluation/human/access_outside_sensor_range.csv')
    csv(access[access.person_id.eq('UNKNOWN')], 'audit/unknown_access_events.csv')
    responses = d['human/alarm_response_log.csv'].copy()
    assert set(responses.gt_id) <= set(events.event_id)
    invalid_ref = responses.action_taken.str.contains('SOP-001 §5', regex=False, na=False)
    responses['sop_reference_status'] = np.where(invalid_ref, 'invalid_section',
              np.where(responses.action_taken.str.contains('SOP-', na=False), 'document_only_unverified', 'no_reference'))
    responses['sop_reference_valid'] = pd.array([False if bad else pd.NA for bad in invalid_ref], dtype='boolean')
    csv(responses, 'evaluation/human/alarm_response_log_reviewed.csv')
    csv(responses[invalid_ref], 'audit/invalid_sop_references.csv')
    js({'event_endpoints': 'inclusive', 'severity': 'Dataset labels unchanged; rule_severity is maximum strict raw-threshold violation during event.',
        'rule_score': 'Report original and SPD-corrected rule reference results separately.',
        'split': 'Existing timestamp split retained: train Jan 6; validation Jan 7; test Jan 8-9. No official event split assumed.',
        'labels': 'Evaluation only; never load evaluation/ or audit/ into detector, GraphRAG corpus or Agent observation input.',
        'human': 'Post-event responses and annotated access outcomes are reference/evaluation only.',
        'imputation': 'None; normal-row empty severity is intentional.'}, 'evaluation/evaluation_policy.json')
    csv(pd.DataFrame([{'split': name, 'rows': int(metadata['split'].eq(name).sum()),
                       'events': int(events['split'].eq(name).sum())} for name in ['train','validation','test']]),
        'evaluation/split_summary.csv')
    return {'row_labels': len(labels), 'anomaly_rows': int(ann.anomaly_label.ne('NORMAL').sum()),
            'events': len(events), 'rules': len(gt), 'spd_corrected_cells': len(changes),
            'access_in_range': int(within.sum()), 'access_out_of_range': int((~within).sum()),
            'unknown_access_events': int(access.person_id.eq('UNKNOWN').sum()),
            'invalid_sop_references': int(invalid_ref.sum()), 'severity_conflict_events': int(events.severity_conflict.sum()),
            'events_by_split': events['split'].value_counts().to_dict()}


def verify_outputs(raw, summary):
    ml = pd.read_csv(OUT / 'inputs/sensors/timeseries_ml_input.csv')
    rule = pd.read_csv(OUT / 'inputs/sensors/timeseries_rule_input.csv')
    original = raw.sort_values(KEYS, kind='stable').reset_index(drop=True)
    assert list(ml) == OBSERVATIONS and list(rule) == OBSERVATIONS + THRESHOLDS
    assert len(ml) == len(rule) == len(raw)
    pd.testing.assert_frame_equal(ml[OBSERVATIONS], original[OBSERVATIONS], check_dtype=False, check_exact=True)
    pd.testing.assert_frame_equal(rule[OBSERVATIONS+THRESHOLDS], original[OBSERVATIONS+THRESHOLDS], check_dtype=False, check_exact=True)
    for frame in [ml, rule]:
        assert not {'quality','anomaly_label','severity','alarm_flag','gt_id','day','shift','batch_id'} & set(frame)
    payloads = json.loads((OUT / 'inputs/sensors/mqtt_stream_input.json').read_text(encoding='utf-8'))
    counts = Counter()
    sanitize(payloads, counts)
    assert not counts
    assert summary['evaluation']['events'] == 14 and summary['evaluation']['rules'] == 86
    static = pd.read_csv(OUT / 'inputs/kg/nodes_static.csv')
    assert not static.label.isin(['AnomalyEvent','SafetyEvent','Maintenance']).any()
    assert not {'gtId','causedBy','severity','sourceRule','startTs','endTs','nominalValue','warnHi','critHi','warnLo','critLo'} & set(static)
    return {'saved_sensor_values_equal_source': True, 'row_count_preserved': True,
            'ml_threshold_columns_absent': True, 'mqtt_forbidden_keys_absent': True,
            'dynamic_graph_nodes_and_attributes_absent': True, 'evaluation_counts_verified': True}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    archive = ROOT / 'iMAKS_dataset.zip'
    before = hashlib.sha256(archive.read_bytes()).hexdigest()
    with ZipFile(archive) as z:
        d = sources(z)
        print('1/4 sensors', flush=True)
        raw, metadata, mapping, sensor_summary = prepare_sensors(d, z)
        print('2/4 documents', flush=True)
        document_summary, pages = prepare_documents(z)
        print('3/4 static KG', flush=True)
        graph_summary = prepare_graph(d, mapping)
        print('4/4 evaluation references', flush=True)
        evaluation_summary = prepare_truth(d, raw, metadata, pages)
        source_hashes = {p: hashlib.sha256(z.read(p)).hexdigest() for p in z.namelist()
                         if not p.endswith('/') and not p.startswith('csi/') and '.DS_Store' not in p}
    summary = {'sensors': sensor_summary, 'documents': document_summary,
               'kg': graph_summary, 'evaluation': evaluation_summary}
    summary['verification'] = verify_outputs(raw, summary)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == before
    js(summary, 'summary.json')
    hashes = {str(p.relative_to(OUT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in OUT.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    js({'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'source_archive_sha256': before,
        'source_files_sha256': source_hashes, 'output_files_sha256': hashes,
        'observations_modified': False, 'existing_outputs_overwritten': False,
        'execution': 'python prepare_common_data.py'}, 'manifest.json')
    print(json.dumps(summary, ensure_ascii=True, indent=2), flush=True)


if __name__ == '__main__':
    main()
