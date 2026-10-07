from pathlib import Path
import json, sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.deps'))
from rdflib import Graph,Namespace,RDF,Literal,XSD
from pyshacl import validate
M=Namespace('https://example.org/imaks/')
out=ROOT/'data/processed'; reports=ROOT/'reports'
raw=pd.read_csv(out/'sensor_observations.csv',low_memory=False)
assert raw.groupby('sensor_id')[['unit','nominal','warn_hi','crit_hi','warn_lo','crit_lo']].nunique().le(1).all().all(), 'Inconsistent sensor metadata'
assert not raw.duplicated(['timestamp','sensor_id']).any()
assert raw.loc[raw.gap_flag,'past_mean_10'].isna().all(), 'Feature crosses a gap'
assert not {'anomaly_label','severity','alarm_flag'}.intersection(raw.columns)
conflicts=[
 {'id':'C01','source_a':'SOP-002','source_b':'DS-THERM-2200','subject':'ST02_SEALING_TMP','issue':'critical high 210 C exceeds continuous sensor rating 200 C','policy':'Keep process threshold; require engineering review or alternate sensor.'},
 {'id':'C02','source_a':'SOP-002','source_b':'DS-ELEC-3300','subject':'ST02_SEALING_CUR','issue':'critical high 15 A exceeds continuous sensor rating 14 A','policy':'Keep process threshold; separate sustained overload constraint.'},
 {'id':'C03','source_a':'SOP-001 RULE-CHM01-03','source_b':'SOP-004 authorization matrix','subject':'Chemical Storage/security','issue':'security authorized in matrix but not in SOP-001 hazmat role list','policy':'Use registry as declared access; no inferred hazmat qualification.'},
 {'id':'C04','source_a':'SOP-002','source_b':'SOP-002','subject':'OUT_OF_RANGE','issue':'duration >10 min versus 20+ readings; dataset cadence is one minute','policy':'Temporal detection requires an explicit reviewed duration convention.'},
 {'id':'C05','source_a':'SOP-002','source_b':'SOP-002','subject':'DRIFT','issue':'definition >15 minutes versus slope on 5+ readings','policy':'Preserve both criteria; do not silently equate them.'},
 {'id':'C06','source_a':'SOP-002','source_b':'DS-MECH-4400','subject':'ST01_FILLING_PRS','issue':'upper warning offset 0.4 bar is less than recommended 0.5 bar','policy':'Engineering advisory; keep source alarm setting.'}
]
person=pd.read_csv(out/'person_registry.csv'); response=pd.read_csv(out/'alarm_response_log.csv')
limits={'operator':(15,3),'technician':(10,2),'supervisor':(5,1),'manager':(15,5),'security':(20,5)}
for r in response.to_dict('records'):
 limit=limits[r['responder_role']][r['severity']=='CRITICAL']
 if r['max_allowed_min']!=limit:
  conflicts.append({'id':r['response_id'],'subject':'acknowledgment SLA','source_a':'alarm_response_log.csv','source_b':'SOP-004','issue':f"source max {r['max_allowed_min']} vs role-specific {limit} minutes",'policy':'KG SLA uses SOP-004 and recomputed timestamp delay; original columns preserved.'})
unknown=pd.read_csv(out/'access_events.csv').query('person_id == "UNKNOWN"')
conflicts.append({'id':'C07','source_a':'access_events.csv','source_b':'person_registry.csv','subject':'UNKNOWN','issue':f'{len(unknown)} events have no registered person','policy':'Preserve UnknownActor and SHACL reference violations; do not invent person identity.'})
factory=pd.read_csv(out/'nodes_factory.csv'); nodes=pd.read_csv(out/'nodes.csv')
factory_sensors=set(factory.loc[factory.label=='Sensor','name']); actual_sensors=set(nodes.loc[nodes.label=='Sensor','name'])
for name in sorted(factory_sensors-actual_sensors):
 conflicts.append({'id':'FACTORY-'+name,'source_a':'nodes_factory.csv','source_b':'nodes.csv/timeseries_raw.csv',
                   'subject':name,'issue':'Factory-only sensor absent from full seed and telemetry',
                   'policy':'Full nodes.csv and telemetry are authoritative for this build; preserve partial factory seed separately.'})
json.dump(conflicts,(reports/'source_conflicts.json').open('w',encoding='utf-8'),ensure_ascii=False,indent=2)
# Meaningful mutation tests: constraints must reject incorrect graph content.
schema=Graph().parse(ROOT/'ontology/manufacturing.ttl'); shapes=Graph().parse(ROOT/'ontology/shapes.ttl')
g=Graph().parse(out/'knowledge_graph.ttl')
# Safe retrieval view for future detector development: event labels and historical
# outcomes cannot act as evidence for predicting those same events.
excluded=set()
for cls in ['AnomalyEvent','SafetyEvent','AlarmResponse','AccessEvent','OccupancySnapshot']:
 excluded.update(g.subjects(RDF.type,M[cls]))
retrieval=Graph()
retrieval.bind('m',M)
for a,b,c in g:
 if a not in excluded and c not in excluded: retrieval.add((a,b,c))
retrieval.serialize(out/'retrieval_graph.ttl',format='turtle')
json.dump({'excluded_classes':['AnomalyEvent','SafetyEvent','AlarmResponse','AccessEvent','OccupancySnapshot'],
           'triples':len(retrieval),'purpose':'Static context without ground-truth events or future record outcomes'},
          (reports/'retrieval_policy.json').open('w',encoding='utf-8'),indent=2)
tests=[]
def test(name, graph, expected):
 ok,_,_=validate(graph,shacl_graph=shapes,ont_graph=schema,allow_warnings=True)
 tests.append({'name':name,'expected_conforms':expected,'actual_conforms':bool(ok),'passed':bool(ok)==expected})
# Minimal valid sensor + station closure, independent of operational violations in source graph.
sensor=next(g.subjects(RDF.type,M.Sensor)); station=g.value(sensor,M.monitors)
fixture=Graph()
for u in [sensor,station]:
 for t in g.triples((u,None,None)): fixture.add(t)
zone=g.value(station,M.locatedIn); fixture.add((zone,RDF.type,M.Zone))
test('valid sensor hierarchy',fixture,True)
bad=Graph()+fixture; bad.set((sensor,M.critHi,Literal(-100.,datatype=XSD.double))); test('inverted thresholds',bad,False)
bad=Graph()+fixture; bad.remove((sensor,M.monitors,None)); test('missing sensor station',bad,False)
obs=M.TestObservation
valid=Graph()+fixture
for p,v in [(RDF.type,M.Observation),(M.observedBy,sensor),(M.timestamp,Literal('2026-01-06T06:00:00',datatype=XSD.dateTime)),(M.value,Literal(22.,datatype=XSD.double)),(M.unit,g.value(sensor,M.unit)),(M.quality,Literal('GOOD'))]: valid.add((obs,p,v))
test('valid observation',valid,True)
bad=Graph()+valid; bad.set((obs,M.unit,Literal('wrong'))); test('unit mismatch',bad,False)
bad=Graph()+valid; bad.set((obs,M.value,Literal('not numeric'))); test('non numeric observation',bad,False)
event=M.TestEvent; event_graph=Graph()
for p,v in [(RDF.type,M.AnomalyEvent),(M.startTs,Literal('2026-01-06T07:00:00',datatype=XSD.dateTime)),(M.endTs,Literal('2026-01-06T06:00:00',datatype=XSD.dateTime)),(M.anomalyType,Literal('SPIKE'))]: event_graph.add((event,p,v))
test('event ends before start',event_graph,False)
person_node=M.TestPerson; zone_node=M.TestZone; access=M.TestAccess
access_graph=Graph()
for p,v in [(RDF.type,M.Person),(M.personId,Literal('test')),(M.role,Literal('operator')),(M.authorized_for,zone_node)]: access_graph.add((person_node,p,v))
access_graph.add((zone_node,RDF.type,M.Zone))
for p,v in [(RDF.type,M.AccessEvent),(M.person,person_node),(M.zone,zone_node),(M.timestamp,Literal('2026-01-06T06:00:00',datatype=XSD.dateTime)),(M.authorized,Literal('NO')),(M.event_type,Literal('ENTRY'))]: access_graph.add((access,p,v))
test('authorization flag contradicts registry',access_graph,False)
response_node=M.TestResponse
sla=Graph()+access_graph; sla.remove((access,None,None))
sla.add((event,RDF.type,M.AnomalyEvent)); sla.add((event,M.startTs,Literal('2026-01-06T06:00:00',datatype=XSD.dateTime))); sla.add((event,M.endTs,Literal('2026-01-06T07:00:00',datatype=XSD.dateTime))); sla.add((event,M.anomalyType,Literal('SPIKE')))
for p,v in [(RDF.type,M.AlarmResponse),(M.event,event),(M.person,person_node),(M.ackDelay,Literal(4.,datatype=XSD.double)),(M.maxAllowed,Literal(3.,datatype=XSD.double))]: sla.add((response_node,p,v))
test('late alarm acknowledgment',sla,False)
json.dump(tests,(reports/'mutation_tests.json').open('w',encoding='utf-8'),indent=2)
assert all(t['passed'] for t in tests), tests
print(json.dumps(tests,indent=2)); print('Source conflicts:',len(conflicts))
summary_file=reports/'validation_summary.json'
if summary_file.exists():
 summary=json.loads(summary_file.read_text(encoding='utf-8'))
 SH=Namespace('http://www.w3.org/ns/shacl#'); vg=Graph().parse(reports/'shacl_report.ttl')
 summary['results']=len(list(vg.subjects(RDF.type,SH.ValidationResult)))
 summary['violations']=len(list(vg.subjects(SH.resultSeverity,SH.Violation)))
 summary['warnings']=len(list(vg.subjects(SH.resultSeverity,SH.Warning)))
 summary['mutation_tests_passed']=len(tests); summary['source_conflicts']=len(conflicts)
 json.dump(summary,summary_file.open('w',encoding='utf-8'),indent=2)
