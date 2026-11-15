from copy import deepcopy
import csv
from datetime import datetime, timedelta
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from rdflib import RDF, Literal
from imaks_kg.rag import sensor_analysis as a, comparison as c, demo, vector as v, window_evidence as w

SID='ST02_SEALING_TMP'


def csv_data(values=None, start=datetime(2026,1,8,12), gap=False):
    values=values if values is not None else [212 if 50<=i<55 else [184,186,185,187,183][i%5] for i in range(90)]
    meta=a.schema(c.load_graph())[SID]
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=a.rules.FIELDS);writer.writeheader()
    for i,value in enumerate(values):
        writer.writerow({'timestamp':(start+timedelta(seconds=30*i+(60 if gap and i>=20 else 0))).isoformat(),
                         'sensor_id':SID,'value':str(value),**meta})
    return stream.getvalue().encode()


class CSVValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.metadata=a.schema(c.load_graph())

    def test_unknown_sensor_and_wrong_metadata_are_rejected(self):
        good=csv_data([184,186])
        for raw in (good.replace(SID.encode(),b'ST99_UNKNOWN_TMP'),good.replace('°C'.encode(),b'F'),
                    good.replace(b'Production Area',b'Wrong Zone'),good.replace(b',TMP,',b',CUR,')):
            with self.subTest(raw=raw[:40]),self.assertRaises(a.InputError):a.parse_csv(raw,self.metadata)

    def test_extra_label_columns_and_missing_cells_are_rejected(self):
        for raw in (csv_data([184]).replace(b'value,unit',b'value,unit,ground_truth'),
                    csv_data([184]).replace(b',184,',b',,'),b''):
            with self.assertRaises(a.InputError):a.parse_csv(raw,self.metadata)

    def test_invalid_time_numbers_duplicates_and_limits_are_rejected(self):
        for raw in (csv_data(['NaN']),csv_data(['1e1000']),csv_data([184]).replace(b'T12:00:00',b'T12:00:01'),
                    csv_data([184]).replace(b'T12:00:00',b'T12:00:00+09:00')):
            with self.assertRaises(a.InputError):a.parse_csv(raw,self.metadata)
        data=csv_data([184,186]).replace(b'T12:00:30',b'T12:00:00')
        with self.assertRaises(a.InputError):a.parse_csv(data,self.metadata)
        with patch.object(a,'MAX_ROWS',1),self.assertRaises(a.InputError):a.parse_csv(csv_data([184,186]),self.metadata)

    def test_gaps_are_recorded_without_filling_samples(self):
        groups,_,quality=a.parse_csv(csv_data([184,186,185]*10,gap=True),self.metadata)
        self.assertEqual(len(groups[SID]),30)
        self.assertEqual(quality['gaps'][0]['missing_slots'],2)
        self.assertEqual(quality['longest_contiguous_samples'][SID],20)


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=v.REPO_ROOT/'kg_build/analysis_tests';root.mkdir(parents=True,exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(dir=root)
        cls.service=a.AnalysisService(Path(cls.temp.name))
        cls.original_input=v.digest((v.REPO_ROOT/a.rules.INPUT).read_bytes())
        cls.original_seal=v.digest((a.team_runtime.store().run_dir/'complete.json').read_bytes())
        with patch.object(v,'api_call',side_effect=AssertionError('No paid API')):
            cls.positive=cls.service.create(csv_data(),'historical_replay')
            cls.normal=cls.service.create(csv_data([[184,186,185,187,183][i%5] for i in range(90)]))
            cls.duplicate=cls.service.create(csv_data(),'historical_replay')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_new_input_detail_has_scoped_provenance_and_no_model_calls(self):
        result=self.positive;self.assertGreater(result['incidents'],0)
        detail=self.service.detail(result['analysis_id'],result['incident_items'][0]['id'])
        self.assertEqual(detail['agent_status'],'complete')
        self.assertEqual(detail['new_api_calls'],0)
        self.assertEqual(detail['explanation_mode'],'deterministic_evidence_summary_no_LLM')
        self.assertEqual(detail['xai']['decision_evidence']['status'],'consistent')
        self.assertIn(result['analysis_id'],detail['xai']['decision_evidence']['input_file'])
        self.assertTrue(detail['claims'])
        for claim in detail['claims']:
            self.assertIn(claim['evidence_paths']['status'],('complete','scope_only'))
        store=self.service.store(result['analysis_id'])
        filenames=[str(o) for prov in store.overlay.subjects(c.IM.sourceKind,Literal('timeseries'))
                   for o in store.overlay.objects(prov,c.IM.fileName)]
        self.assertTrue(filenames)
        self.assertTrue(all(result['analysis_id'] in name for name in filenames))

    def test_same_csv_twice_is_separate_and_never_reuses_another_overlay(self):
        first,second=self.positive['analysis_id'],self.duplicate['analysis_id']
        self.assertNotEqual(first,second)
        sa,sb=self.service.store(first),self.service.store(second)
        self.assertFalse(set(sa.overlay.subjects(RDF.type,c.IM.Spike)) & set(sb.overlay.subjects(RDF.type,c.IM.Spike)))
        with self.assertRaises(a.InputError):self.service.detail(self.normal['analysis_id'],self.positive['incident_items'][0]['id'])
        self.assertEqual(v.digest((v.REPO_ROOT/a.rules.INPUT).read_bytes()),self.original_input)
        self.assertEqual(v.digest((a.team_runtime.store().run_dir/'complete.json').read_bytes()),self.original_seal)

    def test_healthy_window_has_zero_events_without_a_health_certificate(self):
        self.assertEqual(self.normal['incidents'],0)
        self.assertGreater(self.normal['coverage']['eligible_rules'],0)
        self.assertTrue(any('정상 인증' in text for text in self.normal['warnings']))

    def test_series_is_exact_paged_and_filtered(self):
        aid=self.positive['analysis_id'];store=self.service.store(aid);rows,_=store.observation_rows(SID)
        result=self.service.series(aid,SID,offset=1,limit=2)
        self.assertEqual(result['total'],90);self.assertEqual(result['next_offset'],3)
        self.assertEqual(result['points'],[{'timestamp':row['timestamp'],'value':row['value']} for row in rows[1:3]])
        self.assertEqual(result['thresholds']['critHi'],210)
        self.assertEqual(len(self.service.series(aid,SID,start=rows[50]['timestamp'],end=rows[54]['timestamp'])['points']),5)
        with self.assertRaises(a.InputError):self.service.series(aid,SID,limit=10001)
        with self.assertRaises(a.InputError):self.service.series(aid,SID,start=rows[-1]['timestamp'],end=rows[0]['timestamp'])
        with self.assertRaises(a.InputError):self.service.series(aid,'ST99_UNKNOWN')

    def test_uploaded_values_do_not_fit_or_replace_baseline_sigma(self):
        store=self.service.store(self.positive['analysis_id'])
        params=v.read(store.run_dir/'params.json')
        rows,_=store.observation_rows(SID)
        check=w.calibration_for_store(rows,params['config'],params['sigma_by_sensor'][SID],rows[0]['timestamp'],store,SID)
        self.assertEqual(check['state'],'consistent')
        self.assertGreater(check['train_samples'],len(rows))
        self.assertNotEqual(check['reference']['input_file'],store.input_source['file'])

    def test_early_window_does_not_use_future_calibration(self):
        early=self.service.create(csv_data(start=datetime(2026,1,6,12)))
        skipped=early['coverage']['skipped_rules']
        self.assertTrue(any(row['reason']=='baseline_unavailable_before_selected_window' for row in skipped))
        store=self.service.store(early['analysis_id'])
        self.assertFalse(any(rule['executor']=='slope' for rule in v.read(store.run_dir/'ir.json')['rules']))

    def test_tampering_and_path_traversal_are_rejected(self):
        folder=self.service.folder(self.positive['analysis_id']);file=folder/'input.csv';before=file.read_bytes()
        try:
            file.write_bytes(before+b'corrupt')
            with self.assertRaises(ValueError):self.service.store(folder.name)
        finally:file.write_bytes(before)
        for name in ('../outside','ana-'+('0'*32)+'/../outside','unknown'):
            with self.assertRaises(a.InputError):self.service.folder(name)


class AnalysisHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=v.REPO_ROOT/'kg_build/analysis_tests';root.mkdir(parents=True,exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(dir=root);cls.service=a.AnalysisService(Path(cls.temp.name))
        def never(*args,**kwargs):raise AssertionError('No model may run')
        cls.server=demo.make_server(0,generation_enabled=False,analysis_service=cls.service,agent_answer=never)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.port=cls.server.server_port

    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()

    def request(self,method,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=60)
        connection.request(method,path,body,headers or {});response=connection.getresponse()
        status,data=response.status,json.loads(response.read());connection.close();return status,data

    def test_free_upload_series_and_scoped_XAI_work_with_generation_disabled(self):
        _,session=self.request('GET','/api/session')
        self.assertFalse(session['generation_enabled']);self.assertTrue(session['analysis_enabled'])
        headers={'Content-Type':'text/csv','X-Demo-Token':session['csrf_token'],'X-Input-Kind':'historical_replay'}
        status,result=self.request('POST','/api/analyses',csv_data(),headers)
        self.assertEqual(status,201);aid=result['analysis_id'];self.assertEqual(result['new_api_calls'],0)
        status,series=self.request('GET',f'/api/analyses/{aid}/series?sensor_id={SID}&limit=2')
        self.assertEqual(status,200);self.assertEqual(len(series['points']),2)
        iid=result['incident_items'][0]['id']
        status,detail=self.request('GET',f'/api/analyses/{aid}/incidents/{iid}')
        self.assertEqual(status,200);self.assertEqual(detail['agent_status'],'complete')
        status,_=self.request('POST','/api/agent',json.dumps({'question':'new question'}),headers)
        self.assertEqual(status,503)

    def test_auth_mime_size_and_invalid_query_are_rejected(self):
        _,session=self.request('GET','/api/session')
        status,_=self.request('POST','/api/analyses',b'test',{'Content-Type':'text/csv'})
        self.assertEqual(status,403)
        headers={'X-Demo-Token':session['csrf_token'],'Content-Type':'application/octet-stream'}
        self.assertEqual(self.request('POST','/api/analyses',b'test',headers)[0],415)
        headers['Content-Length']=str(a.MAX_BYTES+1)
        self.assertEqual(self.request('POST','/api/analyses',b'',headers)[0],413)
        self.assertEqual(self.request('GET','/api/analyses/..%2Foutside')[0],400)


if __name__=='__main__':unittest.main()
