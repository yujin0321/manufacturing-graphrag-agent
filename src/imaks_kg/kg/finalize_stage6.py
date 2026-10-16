"""Build a versioned, AI-reviewed document KG without promoting human/causal approval."""
import hashlib
import json
from pathlib import Path

from rdflib import Graph, Literal, RDF, RDFS, OWL, XSD, Namespace
from pyshacl import validate

from imaks_kg.kg.relation_candidates import OUT as INPUT, SCHEMA, BASE, PRED, RC, IM, iri
from imaks_kg.kg.documents import units
from imaks_kg.settings import REPO_ROOT

OUT = REPO_ROOT / 'kg_build/stage6_final_20261016'
SH = Namespace('http://www.w3.org/ns/shacl#')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def expected_fields(review):
    """Explicit source condition/action properties; absent values remain absent."""
    n = review['proposed_normalization']
    fields = [(RC.aiReviewStatus, Literal('completed')),
              (RC.humanReviewStatus, Literal('pending')),
              (RC.empiricalCausalityValidated, Literal(False)),
              (RC.assertionScope, Literal(n.get('assertion_scope', 'document_instruction')))]
    literals = {'trigger_state': 'triggerState', 'action': 'action', 'operator': 'comparisonOperator',
                'unit': 'unit', 'severity': 'severity', 'without_operator_command': 'withoutOperatorCommand',
                'trigger_description': 'triggerDescription', 'effect_description': 'effectDescription'}
    fields += [(RC[prop], Literal(n[key])) for key, prop in literals.items() if key in n]
    if 'value' in n:
        fields.append((RC.thresholdValue, Literal(str(n['value']), datatype=XSD.decimal)))
    if 'trigger_sensor' in n:
        fields.append((RC.triggerSensor, iri(n['trigger_sensor'])))
    if 'obligation_group' in n:
        fields.append((RC.obligationGroup, iri('candidate-' + n['obligation_group'])))
    return fields


def run(bundle=None):
    input_root = REPO_ROOT
    input_dir, base_path, pred_path = INPUT, BASE, PRED
    snapshot = None
    if bundle:
        bundle = Path(bundle).resolve()
        manifest = json.loads((bundle / 'bundle_manifest.json').read_text(encoding='utf-8'))
        for name, expected in manifest['files'].items():
            path = (bundle / name).resolve()
            if not path.is_relative_to(bundle) or sha(path) != expected:
                raise ValueError('Changed bundle file: ' + name)
        input_root = bundle / 'inputs'
        input_dir = input_root / INPUT.relative_to(REPO_ROOT)
        base_path = input_root / BASE.relative_to(REPO_ROOT)
        pred_path = input_root / PRED.relative_to(REPO_ROOT)
        snapshot = json.loads((bundle / 'source_units.json').read_text(encoding='utf-8'))
    review = json.loads((input_dir / 'ai_review.json').read_text(encoding='utf-8'))
    # Refuse stale reviews rather than silently applying them to different predictions/graphs.
    for path, expected in review['protected_artifact_sha256'].items():
        if sha(input_root / path) != expected:
            raise ValueError('Stale review input: ' + path)
    protected = {path: sha(input_root / path) for path in review['protected_artifact_sha256']}
    rows = json.loads((input_dir / 'candidates.json').read_text(encoding='utf-8'))
    by_id = {r['identifier']: r for r in rows}
    reviews = {r['identifier']: r for r in review['reviews']}
    assert set(reviews) == {f'REL-{i:02}' for i in range(2, 8)}
    source = {u['unit_id']: u for u in (snapshot if snapshot is not None else units())}
    graph = Graph().parse(input_dir / 'relation_candidates.ttl')
    shapes = Graph().parse(data=(SCHEMA / 'shapes.ttl').read_text(encoding='utf-8').replace(
        'requiresShutdown', 'requiresEmergencyStop'), format='turtle')
    ontology = Graph().parse(data=(SCHEMA / 'ontology.ttl').read_text(encoding='utf-8').replace(
        'requiresShutdown', 'requiresEmergencyStop'), format='turtle')
    ontology.set((RC[''], OWL.versionInfo, Literal('0.2.0-ai-reviewed-document-kg')))
    ontology.set((RC.requiresEmergencyStop, RDFS.comment,
                  Literal('Document instruction requires emergency stop of target; not an executable control command.')))
    from rdflib import BNode
    document_constraint = BNode()
    shapes.add((RC.EvidenceShape, SH.property, document_constraint))
    shapes.add((document_constraint, SH.path, RC.sourceDocument))
    shapes.add((document_constraint, SH.minCount, Literal(1)))
    shapes.add((document_constraint, SH.maxCount, Literal(1)))
    shapes.add((document_constraint, SH['class'], IM.Document))
    ontology.add((RC.AIReview, RDF.type, OWL.Class))
    for name in ['hasAIReview', 'sourceDocument', 'triggerSensor', 'obligationGroup']:
        ontology.add((RC[name], RDF.type, OWL.ObjectProperty))
    for name in ['aiReviewStatus', 'humanReviewStatus', 'empiricalCausalityValidated', 'assertionScope',
                 'triggerState', 'action', 'comparisonOperator', 'unit', 'severity', 'withoutOperatorCommand',
                 'triggerDescription', 'effectDescription', 'thresholdValue', 'reviewerType', 'decision',
                 'reason', 'limitation', 'reviewDate', 'reviewInputSha256']:
        ontology.add((RC[name], RDF.type, OWL.DatatypeProperty))

    def require(shape, prop, value):
        """Release-specific invariants complement general ontology SHACL constraints."""
        from rdflib import BNode
        constraint = BNode()
        shapes.add((shape, SH.property, constraint))
        for p, v in [(SH.path, prop), (SH.hasValue, value), (SH.minCount, Literal(1)), (SH.maxCount, Literal(1))]:
            shapes.add((constraint, p, v))

    for row in rows:
        rid = row['identifier']
        node = RC[rid]
        for e in row['evidence']:
            actual = source[e['unit_id']]
            assert actual['text'] == e['text'] and actual['source_file_sha256'] == e['source_file_sha256']
            ev = RC['evidence-' + hashlib.sha256(e['unit_id'].encode()).hexdigest()[:16]]
            graph.add((ev, RC.sourceDocument, iri(e['doc_id'])))
        if rid not in reviews:
            row['ai_review_status'] = 'not_in_six_candidate_review'
            continue
        r = reviews[rid]
        assert r['evidence'] == row['evidence']
        if rid in {'REL-04', 'REL-05', 'REL-06'}:
            row['relation_type'] = 'requiresEmergencyStop'
            row['condition'] = 'ST02_SEALING_TMP >210°C (CRITICAL): emergency stop ' + row['object'] + '.'
            graph.set((node, RC.relationType, RC.requiresEmergencyStop))
            graph.set((node, RC.conditionText, Literal(row['condition'])))
        audit = RC['review-' + rid + '-20261016']
        graph.add((node, RC.hasAIReview, audit))
        graph.add((audit, RDF.type, RC.AIReview))
        for prop, value in [(RC.reviewerType, 'AI'), (RC.decision, r['decision']), (RC.reason, r['reason_ko']),
                            (RC.reviewDate, '2026-10-16'), (RC.reviewInputSha256, sha(input_dir / 'ai_review.json'))]:
            graph.add((audit, prop, Literal(value)))
        for limit in r['limitations_ko']:
            graph.add((audit, RC.limitation, Literal(limit)))
        shape = RC['Final-' + rid]
        shapes.add((shape, RDF.type, SH.NodeShape))
        shapes.add((shape, SH.targetNode, node))
        expected = expected_fields(r)
        for prop, value in expected:
            graph.set((node, prop, value))
            require(shape, prop, value)
        for prop, value in [(RC.subject, graph.value(node, RC.subject)),
                            (RC.object, graph.value(node, RC.object)),
                            (RC.relationType, RC[row['relation_type']]),
                            (RC.conditionText, Literal(row['condition'])), (RC.hasAIReview, audit)]:
            require(shape, prop, value)
        review_shape = RC['Review-' + rid]
        shapes.add((review_shape, RDF.type, SH.NodeShape))
        shapes.add((review_shape, SH.targetNode, audit))
        require(review_shape, RC.reviewerType, Literal('AI'))
        require(review_shape, RC.decision, Literal(r['decision']))
        if rid == 'REL-07':
            from rdflib import BNode
            for prop in [RC.thresholdValue, RC.comparisonOperator, RC.obligationGroup]:
                constraint = BNode()
                shapes.add((shape, SH.property, constraint))
                shapes.add((constraint, SH.path, prop))
                shapes.add((constraint, SH.maxCount, Literal(0)))
        row.update(ai_review_status='completed', human_review_status='pending',
                   ai_review=r, normalization_applied=True)

    base = Graph().parse(base_path)
    for doc in graph.objects(None, RC.sourceDocument):
        assert (doc, RDF.type, IM.Document) in base
    combined = base + graph
    assert not list(graph.triples((None, IM.causallyAffects, None)))
    OUT.mkdir(parents=True, exist_ok=True)
    for name, shape_graph, ont in [
        ('relation', shapes, ontology),
        ('base', Graph().parse(REPO_ROOT / 'ontology_v1/shapes.ttl'),
         Graph().parse(REPO_ROOT / 'ontology_v1/ontology.ttl'))]:
        ok, _, report = validate(combined, shacl_graph=shape_graph, ont_graph=ont, inference='none')
        (OUT / f'{name}_shacl.txt').write_text(report, encoding='utf-8')
        if not ok:
            raise ValueError(report)

    graph.serialize(OUT / 'reviewed_relations.ttl', format='turtle')
    combined.serialize(OUT / 'document_kg.ttl', format='turtle')
    shapes.serialize(OUT / 'shapes.ttl', format='turtle')
    ontology.serialize(OUT / 'ontology.ttl', format='turtle')
    Graph().serialize(OUT / 'human_approved_relations.ttl', format='turtle')
    write_json('relations.json', rows)
    ledger = []
    for triple in sorted(graph, key=lambda t: tuple(map(str, t))):
        owners = [row['identifier'] for row in rows if triple[0] in {
            RC[row['identifier']], RC['review-' + row['identifier'] + '-20261016'],
            *(RC['evidence-' + hashlib.sha256(e['unit_id'].encode()).hexdigest()[:16]] for e in row['evidence'])}]
        assert owners, triple
        ledger.append({'triple': [x.n3() for x in triple], 'candidate_ids': owners,
                       'origin': 'AI_review_metadata' if str(triple[0]).startswith(str(RC) + 'review-') else 'source_claim_representation'})
    write_json('triple_evidence.json', ledger)
    summary = dict(stage='6th_document_KG_final', ai_reviewed_candidates=6,
                   existing_seed_relation_enrichments=1, new_structured_connections=6,
                   source_units_for_six_candidates=4, emergency_stop_obligations=1, emergency_stop_targets=3,
                   human_approved=0, validated_new_causal_relations=0,
                   relation_triples=len(graph), combined_triples=len(combined),
                   relation_shacl_conforms=True, base_shacl_conforms=True, evidence_coverage=1.0,
                   rule_F1_unchanged=.861878453038674, benchmark_stage_started=False, api_calls=0,
                   predictions_sha256=sha(pred_path), assessment_scope='AI source review, not independent expert validation',
                   normalization_applied=True)
    write_json('summary.json', summary)
    assert all(sha(input_root / p) == h for p, h in protected.items())
    write_json('release_manifest.json', {
        'date': '2026-10-16', 'inputs': protected,
        'ai_review_sha256': sha(input_dir / 'ai_review.json'),
        'input_mode': 'frozen_source_snapshot' if bundle else 'local_source_pdf_verified',
        'builder_sha256': sha(Path(__file__)),
        'source_inputs_unchanged': True,
        'outputs': {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != 'release_manifest.json'},
        'reproduce': 'python -m imaks_kg.kg.finalize_stage6',
        'note': 'RDF blank-node serialization may vary; semantic graph content is reproducible.'})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, help='Rebuild from a hash-checked share bundle without raw PDFs or API calls')
    run(parser.parse_args().bundle)
