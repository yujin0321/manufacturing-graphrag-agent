"""Audit the seven specified iMAKS defects; never rewrite ground truth."""
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile
import pandas as pd
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent


def records(df):
    return json.loads(df.to_json(orient='records'))


def main():
    with ZipFile(ROOT / 'iMAKS_dataset.zip') as z:
        sources = ['sensors/timeseries_raw.csv', 'sensors/timeseries_annotated.csv',
                   'kg_seed/ground_truth.csv', 'kg_seed/nodes.csv', 'kg_seed/nodes_factory.csv',
                   'kg_seed/edges.csv', 'human/access_events.csv', 'human/alarm_response_log.csv']
        data = {p: pd.read_csv(z.open(p), low_memory=False) for p in sources}
        hashes = {p: hashlib.sha256(z.read(p)).hexdigest() for p in sources}
        pdfs = {}
        for name in ['rules/SOP_001_OperatingProcedures.pdf', 'rules/SOP_002_AlarmThresholds.pdf']:
            blob = z.read(name)
            pdfs[name] = [p.extract_text() for p in PdfReader(io.BytesIO(blob)).pages]
            hashes[name] = hashlib.sha256(blob).hexdigest()
    raw = data['sensors/timeseries_raw.csv']
    gt = data['kg_seed/ground_truth.csv']
    nodes = data['kg_seed/nodes.csv']
    edges = data['kg_seed/edges.csv']
    access = data['human/access_events.csv']
    responses = data['human/alarm_response_log.csv']
    annotated = data['sensors/timeseries_annotated.csv']
    ts = pd.to_datetime(raw.timestamp)
    out = ROOT / 'preprocessed' / 'audit'
    out.mkdir(parents=True, exist_ok=True)
    findings = []
    # Expected values manually confirmed against SOP-002 p.1; raw agrees.
    expected = {
        'RULE-ST04-03': {'critLo': 0.85},
        'RULE-THR-ST03-SPD-CRIT': {'critLo': 0.65, 'warnLo': 0.75, 'warnHi': 0.95},
        'RULE-THR-ST04-SPD-CRIT': {'critLo': 0.85},
    }
    errors = []
    for rule_id, fields in expected.items():
        row = gt[gt.ruleId.eq(rule_id)]
        assert len(row) == 1
        for field, expected_value in fields.items():
            actual = float(row.iloc[0][field])
            assert actual != expected_value
            errors.append({'ruleId': rule_id, 'field': field, 'original': actual,
                           'proposed': expected_value, 'evidence': 'SOP-002 p.1 and raw sensor settings'})
    findings.append({'id': 'B01', 'name': 'ground_truth SPD 3 rows',
                     'affected_rules': len(expected), 'incorrect_cells': errors})
    time_findings = {}
    for source in ['sensors/timeseries_raw.csv', 'sensors/timeseries_annotated.csv']:
        df = data[source]
        times = pd.to_datetime(df.timestamp)
        calendar_day = (times.dt.normalize() - ts.min().normalize()).dt.days + 1
        clock_shift = pd.Series('OFF_SHIFT', index=df.index)
        clock_shift.loc[times.dt.hour.between(6, 13)] = 'Morning'
        clock_shift.loc[times.dt.hour.between(14, 21)] = 'Afternoon'
        time_findings[source] = {
            'day_mismatch_vs_calendar': int(df.day.ne(calendar_day).sum()),
            'shift_mismatch_vs_clock_policy': int(df['shift'].ne(clock_shift).sum()),
            'off_shift_rows': int(clock_shift.eq('OFF_SHIFT').sum()),
            'example': records(df.loc[df.day.ne(calendar_day) | df['shift'].ne(clock_shift),
                                    ['timestamp', 'day', 'shift', 'batch_id']].head(2))}
    findings.append({'id': 'B02', 'name': 'shift/day inconsistent with timestamps',
                     'comparison_policy': 'Calendar day from Jan 6; Morning 06-14, Afternoon 14-22, otherwise OFF_SHIFT. This is an explicit audit policy, not an inferred repair.',
                     'files': time_findings, 'split_source': 'timestamp only'})
    factory = data['kg_seed/nodes_factory.csv']
    collisions = factory.merge(nodes[['nodeId', 'name', 'label']], on='nodeId', suffixes=('_factory', '_main'))
    collisions = collisions[collisions.name_factory.ne(collisions.name_main)]
    findings.append({'id': 'B03', 'name': 'nodes_factory excluded', 'factory_rows': len(factory),
                     'id_name_collisions': records(collisions[['nodeId', 'name_factory', 'name_main']]),
                     'canonical_source': 'kg_seed/nodes.csv', 'physically_deleted': False})
    monitors = edges[edges.type.eq('monitors')]
    pairs = {(r.fromId, r.toId) for r in monitors.itertuples()}
    inverse_pairs = {tuple(sorted((a, b))) for a, b in pairs if (b, a) in pairs}
    findings.append({'id': 'B04', 'name': 'bidirectional monitors', 'source_edges': len(monitors),
                     'inverse_pairs': len(inverse_pairs),
                     'canonical_policy': 'Sensor -> monitors -> Station; or inverse Station -> has_sensor -> Sensor. Keep one canonical relation and source mapping.'})
    access_ts = pd.to_datetime(access.timestamp)
    in_range = access_ts.between(ts.min(), ts.max())
    unknown = access.person_id.eq('UNKNOWN')
    findings.append({'id': 'B05', 'name': 'access out of range and UNKNOWN',
                     'sensor_range': [str(ts.min()), str(ts.max())],
                     'access_range': [str(access_ts.min()), str(access_ts.max())],
                     'total': len(access), 'out_of_range': int((~in_range).sum()),
                     'unknown_records': records(access.loc[unknown].assign(in_sensor_range=in_range[unknown])),
                     'policy': 'Preserve source; exclude out-of-range records from joint sensor-window evaluation. UNKNOWN remains unknown; never merge all unknown visitors into one person.'})
    bad_refs = responses[responses.action_taken.str.contains('SOP-001 §5', regex=False, na=False)]
    sop001 = '\n'.join(pdfs['rules/SOP_001_OperatingProcedures.pdf'])
    assert '§5' not in sop001 and '\n5.' not in sop001
    findings.append({'id': 'B06', 'name': 'alarm response unsupported SOP references',
                     'records': records(bad_refs[['response_id', 'gt_id', 'action_taken']]),
                     'evidence': 'Provided SOP-001 has 2 pages, sections 1 and 2 (through 2.9), no section 5.',
                     'policy': 'Preserve action_taken as reported history; mark reference invalid. Do not treat it as SOP-grounded truth or silently substitute another reference.'})
    event = nodes[nodes.gtId.eq('GT-0007')].iloc[0]
    event_rows = annotated[annotated.sensor_id.eq('ST01_FILLING_FLW') &
                           annotated.timestamp.between(event.startTs, event.endTs)]
    critical = event_rows.value.lt(event_rows.crit_lo) | event_rows.value.gt(event_rows.crit_hi)
    findings.append({'id': 'B07', 'name': 'GT-0007 severity vs critical threshold',
                     'node_severity': event.severity,
                     'response_severity': responses.loc[responses.gt_id.eq('GT-0007'), 'severity'].tolist(),
                     'event_rows': records(event_rows[['timestamp', 'value', 'severity', 'warn_lo', 'crit_lo']]),
                     'critical_crossing_rows': int(critical.sum()),
                     'policy': 'Keep dataset_severity=WARNING; store rule-derived severity separately. Report the conflict rather than overwriting evaluation labels.'})
    report = {'source_sha256': hashes, 'scope': 'Seven defects audited and policies specified; source and existing preprocessed artifacts not repaired in this step.',
              'findings': findings}
    (out / 'known_defects_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    pd.DataFrame(errors).to_csv(out / 'spd_threshold_proposed_corrections.csv', index=False, encoding='utf-8-sig')
    print(json.dumps(findings, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
