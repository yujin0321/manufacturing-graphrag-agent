"""Remove alarm labels and quality metadata from MQTT detector input."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
REMOVED_KEYS = frozenset({'alarms', 'status', 'quality'})


def sanitize(value, counts):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in REMOVED_KEYS:
                counts[key] += 1
            else:
                result[key] = sanitize(item, counts)
        return result
    if isinstance(value, list):
        return [sanitize(item, counts) for item in value]
    return value


def verify_preserved(original, cleaned):
    """Independently compare every retained value, list order, and dict key order."""
    if isinstance(original, dict):
        expected_keys = [key for key in original if key not in REMOVED_KEYS]
        assert isinstance(cleaned, dict) and list(cleaned) == expected_keys
        for key in expected_keys:
            verify_preserved(original[key], cleaned[key])
    elif isinstance(original, list):
        assert isinstance(cleaned, list) and len(original) == len(cleaned)
        for before, after in zip(original, cleaned):
            verify_preserved(before, after)
    else:
        assert type(original) is type(cleaned) and original == cleaned


def main():
    archive = ROOT / 'iMAKS_dataset.zip'
    source = 'sensors/mqtt_payloads.json'
    with ZipFile(archive) as z:
        source_bytes = z.read(source)
    original = json.loads(source_bytes)
    if not isinstance(original, list) or not all(isinstance(item, dict) for item in original):
        raise ValueError('Expected an array of MQTT message objects.')
    if not all('status' in item and 'alarms' in item for item in original):
        raise ValueError('Source schema changed: status/alarms missing.')
    counts = Counter()
    cleaned = sanitize(original, counts)
    verify_preserved(original, cleaned)
    out = ROOT / 'preprocessed' / 'sensors'
    out.mkdir(parents=True, exist_ok=True)
    target = out / 'mqtt_stream_input.json'
    target.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    # Validate the actual saved artifact, including JSON types and message order.
    saved = json.loads(target.read_text(encoding='utf-8'))
    verify_preserved(original, saved)
    leftovers = Counter()
    sanitize(saved, leftovers)
    assert not leftovers
    report = {
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'source': f'{archive.name}:{source}',
        'source_sha256': hashlib.sha256(source_bytes).hexdigest(),
        'output': str(target.relative_to(ROOT)),
        'output_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'messages_before': len(original),
        'messages_after': len(saved),
        'source_status_counts': dict(Counter(item['status'] for item in original)),
        'source_messages_with_nonempty_alarms': sum(bool(item['alarms']) for item in original),
        'removed_key_occurrences': dict(counts),
        'remaining_removed_key_occurrences': dict(leftovers),
        'remaining_top_level_keys': list(saved[0]) if saved else [],
        'verification': 'Every retained value/type and message/list/key order matches source after JSON reload.',
        'policy': 'Both rule and ML stream inputs exclude alarms/status/quality; source ZIP preserved.',
        'scope': 'Removal of alarms/status and inherited quality exclusion only; other fields not audited.',
    }
    (out / 'mqtt_removal_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
