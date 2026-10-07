"""Build a static RDF graph, exercise five SHACL groups, and answer CQs."""
from pathlib import Path
import json
import pandas as pd
from rdflib import Graph, Namespace, Literal, RDF, XSD
from pyshacl import validate

ROOT=Path(__file__).resolve().parent
EX=Namespace('https://example.org/imaks/')
SH=Namespace('http://www.w3.org/ns/shacl#')

def run():
    reports=ROOT/'reports'; reports.mkdir(exist_ok=True)
    shapes=Graph().parse(ROOT/'shapes.ttl')
    # No RDFS domain/range inference: do not infer away missing explicit types.
    Graph().parse(ROOT/'ontology.ttl')
    base=Graph().parse(ROOT/'sample_valid.ttl')
    cases={'valid':base}
    sensor=EX.ST02_SEALING_CUR; ev=EX.DEMO_EVENT
    for name,predicate in [('missing_sensor_id',EX.sensorId),('missing_station',EX.installedAt),
                           ('missing_start',EX.startTime),('missing_sensor_link',EX.affectsSensor)]:
        g=Graph()+base
        g.remove((sensor if name.startswith('missing_s') and name in ['missing_sensor_id','missing_station'] else ev,predicate,None))
        cases[name]=g
    g=Graph()+base; g.set((ev,EX.endTime,Literal('2026-01-06T06:00:00',datatype=XSD.dateTime))); cases['end_before_start']=g
    g=Graph()+base; g.remove((ev,EX.endTime,None)); cases['open_event']=g
    g=Graph()+base; g.set((ev,EX.affectsSensor,EX.UNKNOWN_SENSOR)); cases['unknown_sensor']=g
    cases['missing_start'].serialize(ROOT/'sample_invalid.ttl',format='turtle')
    fixture_dir=ROOT/'examples'; fixture_dir.mkdir(exist_ok=True)
    for name,g in cases.items():
        g.serialize(fixture_dir/f'{name}.ttl',format='turtle')
    static=Graph(); static.bind('ex',EX)
    meta=pd.read_csv(ROOT/'data/processed/sensor_metadata.csv')
    for row in meta.itertuples():
        s=EX[row.sensor_id]; station=EX[row.station_id]
        static.add((s,RDF.type,EX.Sensor)); static.add((s,EX.sensorId,Literal(row.sensor_id)))
        static.add((s,EX.installedAt,station)); static.add((s,EX.unit,Literal(row.unit)))
        static.add((station,RDF.type,EX.Station)); static.add((station,EX.stationId,Literal(row.station_id)))
    nodes=pd.read_csv(ROOT/'data/processed/static_nodes.csv').set_index('nodeId')
    edges=pd.read_csv(ROOT/'data/processed/static_edges.csv')
    for row in edges[edges.type.eq('feeds_into')].itertuples():
        static.add((EX[nodes.loc[row.fromId,'name']],EX.feedsInto,EX[nodes.loc[row.toId,'name']]))
    static.serialize(ROOT/'data/processed/static_graph.ttl',format='turtle')
    cases['static_graph']=static
    results=[]
    expected_shapes={'missing_sensor_id':EX.SensorIdProperty,'missing_station':EX.StationProperty,
        'missing_start':EX.StartProperty,'missing_sensor_link':EX.AffectedSensorProperty,
        'end_before_start':EX.EventOrderShape,'unknown_sensor':EX.AffectedSensorProperty}
    for name,g in cases.items():
        conforms,report,text=validate(g,shacl_graph=shapes,inference='none',meta_shacl=True)
        expected=name in ['valid','open_event','static_graph']
        sources=set(report.objects(None,SH.sourceShape))
        assert bool(conforms)==expected,(name,text)
        if not expected:
            assert expected_shapes[name] in sources,(name,sources)
        (reports/f'shacl_{name}.txt').write_text(text,encoding='utf-8')
        results.append({'case':name,'expected_conforms':expected,'actual_conforms':bool(conforms),
            'violations':len(list(report.subjects(RDF.type,SH.ValidationResult))),'test_passed':True})
    pd.DataFrame(results).to_csv(reports/'shacl_summary.csv',index=False,encoding='utf-8-sig')
    queries={
        'CQ1_sensor_station':'SELECT ?station WHERE { ex:ST02_SEALING_CUR ex:installedAt ?station }',
        'CQ2_event_time':'SELECT ?start ?end WHERE { ex:DEMO_EVENT ex:startTime ?start . OPTIONAL { ex:DEMO_EVENT ex:endTime ?end } }',
        'CQ3_inspection_evidence':'''SELECT ?step ?text ?file ?page WHERE {
            ?rule ex:appliesToSensor ex:ST02_SEALING_CUR ; ex:hasInspectionStep ?step .
            ?step ex:text ?text ; ex:supportedBy ?e . ?e ex:inDocument ?d ; ex:page ?page . ?d ex:sourceFile ?file . }'''}
    answers={}
    for name,q in queries.items():
        full='PREFIX ex: <https://example.org/imaks/>\n'+q
        answers[name]={'query':full,'rows':[[str(v) for v in row] for row in base.query(full)],'scope':'manually constructed example; not retrieval performance'}
        assert answers[name]['rows'], name
    (reports/'competency_queries.json').write_text(json.dumps(answers,ensure_ascii=False,indent=2),encoding='utf-8')
    return results

if __name__=='__main__':
    print(json.dumps(run(),indent=2))
