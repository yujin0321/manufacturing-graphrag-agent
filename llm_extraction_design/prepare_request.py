"""Offline request preparation only. No network client or API key access."""
import argparse
import hashlib
import json
from pathlib import Path

DOCUMENTS = ('SOP-001', 'SOP-002', 'SOP-003', 'SOP-004',
             'DS-ELEC-3300', 'DS-MECH-4400', 'DS-THERM-2200')
FILES = {d + '.json' for d in DOCUMENTS} | {'ontology.ttl', 'shapes.ttl'}
BASE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare(input_dir, document, model, max_output_tokens=16000):
    if document not in DOCUMENTS or not model.strip() or max_output_tokens <= 0:
        raise ValueError('Valid document, nonempty model and positive output limit required')
    root = Path(input_dir).resolve()
    manifest_bytes = (root / 'input_manifest.json').read_bytes()
    expected = json.loads(manifest_bytes)['sha256']
    if set(expected) != FILES:
        raise ValueError('Manifest must contain exactly the nine allowed source filenames')
    payloads = {}
    for name in sorted(FILES):
        path = (root / name).resolve()
        if path.parent != root:
            raise ValueError('Input file escapes the designated directory')
        data = path.read_bytes()
        if digest(data) != expected[name]:
            raise ValueError('SHA-256 mismatch: ' + name)
        payloads[name] = data
    doc = json.loads(payloads[document + '.json'])
    if doc['document_id'] != document or not isinstance(doc['units'], list):
        raise ValueError('Invalid document identity or units')
    unit_ids = [u['unit_id'] for u in doc['units']]
    if len(unit_ids) != len(set(unit_ids)):
        raise ValueError('Duplicate source unit ID')
    for u in doc['units']:
        if digest(u['text'].encode('utf-8')) != u['text_sha256']:
            raise ValueError('Unit text hash mismatch: ' + u['unit_id'])
    prompt_bytes = (BASE / 'extraction_prompt.txt').read_bytes()
    schema_bytes = (BASE / 'response_schema.json').read_bytes()
    source = {k: doc[k] for k in ('document_id', 'inventory', 'units')}
    request = {
        'model': model,
        'store': False,
        'max_output_tokens': max_output_tokens,
        'input': [
            {'role': 'developer', 'content': prompt_bytes.decode('utf-8-sig')},
            {'role': 'user', 'content': json.dumps(source, ensure_ascii=False)}],
        'text': {'format': {'type': 'json_schema', 'name': 'imaks_extraction',
                            'strict': True, 'schema': json.loads(schema_bytes)}}}
    encoded = (json.dumps(request, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    audit = {
        'mode': 'offline_request_preparation', 'api_called': False,
        'document_id': document, 'requested_model': model, 'actual_model': None,
        'unit_count': len(unit_ids), 'request_sha256': digest(encoded),
        'input_sha256': expected, 'manifest_sha256': digest(manifest_bytes),
        'prompt_sha256': digest(prompt_bytes), 'schema_sha256': digest(schema_bytes),
        'note': 'No token estimate, API compatibility test or extraction result.'}
    return encoded, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--document', choices=DOCUMENTS, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--max-output-tokens', type=int, default=16000)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    request, audit = prepare(args.input_dir, args.document, args.model, args.max_output_tokens)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / 'request.json').write_bytes(request)
    (args.output_dir / 'preparation.json').write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Prepared locally; no API call: ' + str(args.output_dir))


if __name__ == '__main__':
    main()
