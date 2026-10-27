"""Two-project workflow acceptance using the public core and HTTP boundaries."""
import contextlib
import copy
import io
import json
import tempfile
import threading
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

from rws.core import Store
from rws.server import create_server
from tools.seed_demo import seed


class TwoProjectWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / 'acceptance.sqlite3')
        with contextlib.redirect_stdout(io.StringIO()):
            self.seed = seed(self.db)
        self.store = Store(self.db)
        self.server = create_server(self.db, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:%d' % self.server.server_address[1]
        self.http = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
        self.counter = 0

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.temp.cleanup()

    def get(self, path):
        with self.http.open(self.base + path, timeout=5) as response:
            return json.load(response)

    def call(self, op, args, human=False):
        headers = {'Content-Type':'application/json', 'Origin':self.base}
        if human:
            headers['X-RWS-CSRF'] = self.get('/api/session')['csrfToken']
        data = json.dumps({'name':op, 'arguments':args}).encode()
        request = Request(self.base + ('/api/human/call' if human else '/api/call'), data=data, headers=headers)
        try:
            with self.http.open(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def mutate(self, op, pid, human=False, **kwargs):
        self.counter += 1
        kwargs.update(projectId=pid, expectedRevision=self.store.snapshot(pid)['revision'], requestId='workflow-%s'%self.counter)
        return self.call(op, kwargs, human)

    def test_review_apply_restart_and_immutable_report(self):
        pid = 'trial-training'
        project = next(p for p in self.store.snapshot(pid)['projects'] if p['id']==pid)
        report_ref = {'projectId':pid,'type':'report','id':'RP1','version':1}
        report = copy.deepcopy(self.store.call('rws_record_get', {'ref':report_ref})['result'])
        draft = project['draft']
        args = dict(proposalRef=draft['proposalRef'],baseRevision=draft['baseRevision'])
        status, result = self.mutate('rws_overview_apply', pid, **args)
        self.assertEqual(status,403)
        self.assertEqual(result['error']['code'],'approval_required')
        status, result = self.mutate('rws_overview_apply', pid, human=True, **args)
        self.assertEqual(status,200)
        self.assertEqual(result['result']['foundation']['revision'],2)
        restarted = Store(self.db)
        self.assertEqual(restarted.call('rws_record_get',{'ref':report_ref})['result'],report)
        exp = restarted.call('rws_record_get',{'ref':{'projectId':pid,'type':'experiment','id':'E1'}})['result']
        self.assertEqual(exp['record']['foundationRevision'],1)
        context = restarted.call('rws_get_context',{'projectId':pid,'experimentRef':exp['ref']})['result']
        self.assertEqual(context['foundation']['revision'],1)
        self.assertEqual(context['latestFoundationRevision'],2)

    def test_revoke_cross_project_usage_retains_producer_and_report(self):
        pid = 'trial-training'
        source = {'projectId':'trial-image-edit','type':'artifact','id':'A0','version':1}
        before = self.store.call('rws_record_get',{'ref':source})['result']
        report_ref = {'projectId':pid,'type':'report','id':'RP1','version':1}
        report = self.store.call('rws_record_get',{'ref':report_ref})['result']
        usage = self.seed['crossProjectUsage']['ref']
        status, _ = self.mutate('rws_usage_remove',pid,id=usage['id'])
        self.assertEqual(status,200)
        self.assertEqual(self.store.call('rws_record_get',{'ref':source})['result'],before)
        self.assertEqual(self.store.call('rws_record_get',{'ref':report_ref})['result'],report)
        self.assertTrue(self.store.call('rws_record_get',{'ref':dict(usage,version=2)})['result']['record']['revoked'])
        source_run=self.store.call('rws_record_get',{'ref':before['record']['producerRef']})['result']
        self.assertEqual(source_run['record']['codeRef']['id'],'C0')

    def test_all_result_kinds_remain_typed_and_context_has_no_forced_hypothesis(self):
        ev=self.store.call('rws_record_get',{'ref':{'projectId':'trial-image-edit','type':'evaluation','id':'EV1'}})['result']['record']
        self.assertEqual({r['kind'] for r in ev['results']},{'metric','table','image-set','attachment'})
        self.assertEqual(ev['pairs'][0]['predictionRef']['id'],'A1')
        self.assertEqual(ev['pairs'][0]['referenceRef']['id'],'A0')
        source=self.store.call('rws_record_get',{'ref':{'projectId':'trial-training','type':'artifact','id':'A0'}})['result']['record']
        self.assertEqual(source['content']['kind'],'series')
        self.assertEqual(source['content']['points'][0],{'x':0,'y':1.2})
        research=self.store.call('rws_record_get',{'ref':{'projectId':'trial-training','type':'research','id':'H1'}})['result']['record']
        self.assertNotIn('hypothesis',research)
        self.assertNotIn('judgment',research)
        snapshot=self.get('/api/state?projectId=trial-training')
        self.assertTrue(any(e['ref']['projectId']=='trial-image-edit' for e in snapshot['references']))


if __name__=='__main__':
    unittest.main()
