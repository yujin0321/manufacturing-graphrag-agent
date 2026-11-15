from copy import deepcopy
import io
import json
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from imaks_kg.rag import sensor_analysis as a, analysis_archive as archive, comparison as c, vector as v
from tests.test_sensor_analysis import csv_data, SID


class AsyncQueueTests(unittest.TestCase):
    def setUp(self):
        root=v.REPO_ROOT/'kg_build/analysis_v2_tests';root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root)
        self.service=a.AnalysisService(Path(self.temp.name),max_pending=1)
        self.started=threading.Event();self.release=threading.Event();self.calls=[]
        def controlled(raw,kind,aid,**kwargs):
            self.calls.append(aid);self.service._state(aid,'processing','detecting');self.started.set()
            if not self.release.wait(5):raise AssertionError('Controlled test gate was not released')
            raise a.InputError('controlled_failure','검사용 실패')
        self.mock=patch.object(self.service,'_execute',side_effect=controlled);self.mock.start()

    def tearDown(self):
        self.release.set();self.service.close();self.mock.stop();self.temp.cleanup()

    def test_submit_returns_id_while_worker_is_still_running_and_results_are_not_ready(self):
        result=self.service.submit(b'controlled','historical_replay')
        self.assertEqual(result['status'],'queued');self.assertTrue(self.started.wait(2))
        state=self.service.summary(result['analysis_id'])
        self.assertEqual(state['phase'],'detecting')
        self.assertNotIn('percent',state)
        with self.assertRaises(a.InputError) as caught:self.service.store(result['analysis_id'])
        self.assertEqual(caught.exception.code,'analysis_not_ready')
        self.assertEqual(len(self.calls),1)

    def test_queue_is_bounded_and_bad_submission_does_not_consume_a_slot(self):
        with self.assertRaises(a.InputError):self.service.submit(b'')
        first=self.service.submit(b'valid')
        self.assertTrue(self.started.wait(2))
        with self.assertRaises(a.InputError) as caught:self.service.submit(b'another')
        self.assertEqual(caught.exception.code,'analysis_queue_full')
        self.assertEqual(len(list(self.service.root.glob('ana-*'))),1)

    def test_failed_worker_is_recorded_once_without_automatic_retry(self):
        result=self.service.submit(b'valid');self.assertTrue(self.started.wait(2))
        self.release.set();self.service.close()
        state=self.service.summary(result['analysis_id'])
        self.assertEqual(state['status'],'failed');self.assertEqual(state['error']['code'],'controlled_failure')
        self.assertEqual(len(self.calls),1)

    def test_startup_marks_abandoned_jobs_interrupted_but_not_current_jobs(self):
        abandoned=self.service._reserve(b'old','historical_replay')
        active=self.service.submit(b'active');self.assertTrue(self.started.wait(2))
        self.assertEqual(self.service.recover_interrupted(),[abandoned])
        self.assertEqual(self.service.summary(abandoned)['status'],'interrupted')
        self.assertEqual(self.service.summary(active['analysis_id'])['status'],'processing')

    def test_closed_service_refuses_new_jobs(self):
        self.service.close()
        with self.assertRaises(a.InputError) as caught:self.service.submit(b'valid')
        self.assertEqual(caught.exception.code,'service_closed')


class IntervalPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.metadata=a.schema(c.load_graph())

    def prepare(self,raw,start='2026-01-08T12:26:00',end='2026-01-08T12:35:00'):
        groups,_,_=a.parse_csv(raw,self.metadata)
        return a.prepare_intervals(groups,self.metadata,start,end)

    def test_future_values_do_not_enter_processing_and_warmup_is_preserved(self):
        original=csv_data();groups,normalized,_,intervals=self.prepare(original)
        changed=original.replace(b'2026-01-08T12:40:00,Production Area,ST02_SEALING,ST02_SEALING_TMP,TMP,184',
                                  b'2026-01-08T12:40:00,Production Area,ST02_SEALING,ST02_SEALING_TMP,TMP,999')
        self.assertNotEqual(original,changed)
        self.assertEqual(normalized,self.prepare(changed)[1])
        self.assertEqual(len(groups[SID]),71)
        self.assertEqual(intervals['sensors'][SID]['warmup_samples'],52)
        self.assertEqual(intervals['sensors'][SID]['analysis_samples'],19)
        self.assertEqual(intervals['excluded_after_analysis_end_rows'],19)

    def test_history_gap_resets_boundary_readiness(self):
        _,_,_,intervals=self.prepare(csv_data(gap=True),start='2026-01-08T12:11:00',end='2026-01-08T12:35:00')
        self.assertEqual(intervals['sensors'][SID]['contiguous_prior_samples_at_first_target'],0)

    def test_invalid_or_unobserved_target_is_rejected(self):
        for start,end in [('2026-01-08T11:00:00','2026-01-08T12:35:00'),
                          ('2026-01-08T12:30:00','2026-01-08T13:00:00')]:
            with self.assertRaises(a.InputError):self.prepare(csv_data(),start,end)
        with self.assertRaises(a.InputError):self.prepare(csv_data(gap=True),'2026-01-08T12:10:00','2026-01-08T12:10:30')


class PortableAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=v.REPO_ROOT/'kg_build/analysis_v2_tests';root.mkdir(parents=True,exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(dir=root)
        cls.source=a.AnalysisService(Path(cls.temp.name)/'source')
        cls.result=cls.source.create(csv_data(),'historical_replay',analysis_start='2026-01-08T12:26:00',analysis_end='2026-01-08T12:35:00')
        cls.aid=cls.result['analysis_id'];cls.blob=cls.source.export_bundle(cls.aid)
        cls.target=a.AnalysisService(Path(cls.temp.name)/'target')
        cls.target.import_bundle(cls.blob)

    @classmethod
    def tearDownClass(cls):cls.source.close();cls.target.close();cls.temp.cleanup()

    def test_real_phases_and_ongoing_incident_are_reported(self):
        self.assertEqual([p['phase'] for p in self.result['job']['phase_history']],
                         ['queued','validating','preparing_rules','detecting','validating_graph','sealing','complete'])
        self.assertEqual(self.result['incidents'],1)
        self.assertEqual(self.result['incident_items'][0]['window_scope'],'started_before_analysis')
        self.assertTrue(any(row['sample_history_ready'] for row in self.result['coverage']['start_boundary_checks']))

    def test_series_defaults_to_target_and_explicitly_allows_warmup(self):
        normal=self.source.series(self.aid,SID)
        history=self.source.series(self.aid,SID,include_warmup=True)
        self.assertEqual(normal['total'],19);self.assertEqual(history['total'],71)
        self.assertTrue(all(point['timestamp']>='2026-01-08T12:26:00' for point in normal['points']))
        self.assertFalse(any(point['timestamp']>'2026-01-08T12:35:00' for point in history['points']))
        with self.assertRaises(a.InputError):self.source.series(self.aid,SID,start='2026-01-08T12:00:00')

    def test_finished_history_incident_is_hidden_from_target_but_remains_available_as_context(self):
        result=self.source.create(csv_data(),'historical_replay',analysis_start='2026-01-08T12:30:00',analysis_end='2026-01-08T12:35:00')
        self.assertEqual(result['incidents'],0)
        self.assertEqual(result['processing_incidents'],1)
        self.assertEqual(len(result['history_incident_ids']),1)
        detail=self.source.detail(result['analysis_id'],result['history_incident_ids'][0])
        self.assertEqual(detail['window_scope'],'warmup_only')

    def test_restore_retains_all_artifact_bytes_and_resolves_local_input_for_XAI(self):
        _,files=archive.read_bundle(self.blob)
        for name,raw in files.items():self.assertEqual((self.target.folder(self.aid)/name).read_bytes(),raw)
        detail=self.target.detail(self.aid,self.result['incident_items'][0]['id'])
        self.assertEqual(detail['agent_status'],'complete')
        self.assertEqual(detail['xai']['decision_evidence']['status'],'consistent')
        self.assertIn('/target/',detail['input_source']['file'])
        self.assertIn('/source/',detail['origin_input_source']['file'])
        self.assertEqual(detail['input_source']['sha256'],detail['origin_input_source']['sha256'])
        self.assertEqual(detail['window_scope'],'started_before_analysis')

    def test_repeated_import_is_idempotent_and_never_overwrites_different_data(self):
        self.assertEqual(self.target.import_bundle(self.blob)['status'],'already_present')
        file=self.target.folder(self.aid)/'input.csv';old=file.read_bytes()
        try:
            file.write_bytes(old+b'changed')
            with self.assertRaises(a.InputError) as caught:self.target.import_bundle(self.blob)
            self.assertEqual(caught.exception.code,'analysis_conflict')
            self.assertEqual(file.read_bytes(),old+b'changed')
        finally:file.write_bytes(old)

    def rewrite(self,mutate=None,extra=None,symlink=False):
        manifest,files=archive.read_bundle(self.blob)
        if mutate:mutate(manifest,files)
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(archive.MANIFEST,json.dumps(manifest))
            for name,raw in files.items():
                if symlink and name=='input.csv':
                    info=zipfile.ZipInfo(name);info.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(info,raw)
                else:z.writestr(name,raw)
            if extra:z.writestr(extra,b'outside')
        return out.getvalue()

    def test_tampered_checksum_dependency_and_unsafe_entries_are_rejected(self):
        def tamper(manifest,files):files['input.csv']+=b'changed'
        with self.assertRaises(a.InputError):self.target.import_bundle(self.rewrite(tamper))
        def dependency(manifest,files):manifest['dependencies']['kg_sha256']='0'*64
        with self.assertRaises(a.InputError) as caught:self.target.import_bundle(self.rewrite(dependency))
        self.assertEqual(caught.exception.code,'dependency_mismatch')
        for raw in (self.rewrite(extra='../outside.txt'),self.rewrite(symlink=True)):
            with self.assertRaises(a.InputError):self.target.import_bundle(raw)
        self.assertFalse(list(self.target.root.glob('.restore-*')))

    def test_incomplete_or_oversized_bundle_is_rejected(self):
        with self.assertRaises(a.InputError):archive.read_bundle(b'not a zip')
        with patch.object(archive,'MAX_ZIP_BYTES',1),self.assertRaises(a.InputError):archive.read_bundle(self.blob)
        with patch.object(archive,'MAX_EXPANDED_BYTES',1),self.assertRaises(a.InputError):archive.read_bundle(self.blob)


if __name__=='__main__':unittest.main()
