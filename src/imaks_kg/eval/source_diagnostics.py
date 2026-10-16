"""Post-score source/reference numeric diagnostics; never changes predictions or scores."""
import argparse
import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

from imaks_kg.common.io_utils import write_json
from imaks_kg.eval.team_protocol.gold import file_sha256, known_doc_ids, load_gold
from imaks_kg.kg_build.preprocessed_abox import PreprocessedLayout

FIELDS = {'CRIT_LO': 'critLo', 'WARN_LO': 'warnLo', 'NOMINAL': 'nominal',
          'WARN_HI': 'warnHi', 'CRIT_HI': 'critHi'}
NUMBER = r'[-+]?\d+(?:\.\d+)?'


def parse_threshold_fields(text):
    """Parse labeled numeric fields in either value(label) or label=value form."""
    values = {}
    for label, field in FIELDS.items():
        name = r'WARN_LO(?:W)?' if label == 'WARN_LO' else label
        forward = re.search(r'\b' + name + r'\s*=\s*(' + NUMBER + ')', text, re.I)
        backward = re.search(r'(' + NUMBER + r')(?:\s*±\s*' + NUMBER +
                             r')?\s*[^\d,;()]*\(' + name + r'\)', text, re.I)
        match = forward or backward
        if match:
            values[field] = Decimal(match[1])
    return values


def run(build_dir, evaluation_dir, gold_path):
    root, out, gold_path = Path(build_dir), Path(evaluation_dir), Path(gold_path)
    metrics = json.loads((out / 'metrics.json').read_text())
    lock = json.loads((out / 'pre_evaluation_lock.json').read_text())
    if file_sha256(root / 'predictions.jsonl') != lock['prediction_sha256']:
        raise ValueError('Frozen predictions changed')
    if file_sha256(gold_path) != metrics['inputs']['gold_sha256']:
        raise ValueError('Reference file changed')
    source = json.loads((root / 'source_field_audit.local.json').read_text())
    expected = {r['sensor']: r['source_fields'] for r in source['numeric_rows']}
    gold = load_gold(gold_path, known_doc_ids(PreprocessedLayout.detect(None).doc_manifest))
    details, incomplete = [], []
    rows = [g for g in gold if g.doc == 'SOP-002' and g.sensor in expected]
    for row in rows:
        values = parse_threshold_fields(row.condition)
        if len(values) != 5:
            incomplete.append(row.rule_id)
        for field, value in values.items():
            original = Decimal(expected[row.sensor][field])
            if value != original:
                details.append({'reference_id': row.rule_id, 'sensor': row.sensor, 'field': field,
                                'reference_value': str(value), 'source_value': str(original)})
    summary = {'phase': 'post_score_diagnostic_only', 'reference_sensor_rows': len(rows),
               'fully_parsed_rows': len(rows) - len(incomplete), 'differing_fields': len(details),
               'differing_rows': len({r['reference_id'] for r in details}),
               'differences_by_field': dict(Counter(r['field'] for r in details)),
               'prediction_sha256': lock['prediction_sha256'],
               'gold_sha256': metrics['inputs']['gold_sha256'],
               'diagnostic_code_sha256': file_sha256(Path(__file__)),
               'source_audit_sha256': file_sha256(root / 'source_field_audit.local.json'),
               'scores_and_predictions_modified': False}
    write_json(out / 'source_reference_diagnostic.local.json',
               {'summary': summary, 'differences': details, 'unparsed_reference_ids': incomplete})
    write_json(out / 'source_reference_summary.json', summary)
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build-dir', required=True)
    p.add_argument('--evaluation-dir', required=True)
    p.add_argument('--gold', required=True)
    args = p.parse_args()
    print(json.dumps(run(args.build_dir, args.evaluation_dir, args.gold), ensure_ascii=False, indent=2))
