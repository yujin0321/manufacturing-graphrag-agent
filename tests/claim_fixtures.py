"""Mock selector replies; never calls a model or reads answer keys."""
import json


def selected_claims(content, *, all_conditions=False, unknown=False):
    view = content['claim_catalog']
    chosen = []
    for kind in ('observation', 'condition', 'recommendation'):
        matches = [claim['claim_id'] for claim in view if claim['claim_type'] == kind]
        chosen.extend(matches if kind == 'condition' and all_conditions else matches[:1])
    if unknown:
        chosen.append('CLM-' + '0' * 16)
    return json.dumps({'claim_ids': chosen})
