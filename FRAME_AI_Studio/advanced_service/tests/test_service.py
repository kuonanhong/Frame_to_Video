"""Stdlib contract tests. Fake subprocesses verify plumbing, never model quality."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from install import selected_files
from validation import validate, multipart

def wait(manager,identifier):
    deadline = time.monotonic()+8
    while time.monotonic()<deadline:
        job = manager.get(identifier)
        if job['status'] not in {'queued','running'}:
            return job
        time.sleep(.025)
    raise AssertionError('Test subprocess did not finish')

class ValidationTests(unittest.TestCase):
    def test_unknown_expert_and_command_rejected(self):
        for fields in ({'expert':'shell','prompt':'x'},{'expert':'qwen-text','prompt':'x','command':'sh'}):
            with self.assertRaises(ValueError):
                validate(fields,{})

    def test_required_media_and_dimensions(self):
        with self.assertRaises(ValueError):
            validate({'expert':'liveportrait'},{'image':b'x'})
        with self.assertRaises(ValueError):
            validate({'expert':'flux-klein','prompt':'x'},{})
        with self.assertRaises(ValueError):
            validate({'expert':'ltx-video','prompt':'x','frames':'10'},{'image':b'x'})
        with self.assertRaises(ValueError):
            validate({'expert':'qwen-text','prompt':'x','guidance':'nan'},{})
        valid = validate({'expert':'qwen-text','prompt':'hello'},{})
        self.assertEqual(valid['max_tokens'],256)

    def test_multipart_duplicates_and_unknown_names(self):
        for name in ('command','expert'):
            body = (f'--B\r\nContent-Disposition: form-data; name="expert"\r\n\r\nqwen-text\r\n'
                f'--B\r\nContent-Disposition: form-data; name="{name}"\r\n\r\nx\r\n--B--\r\n').encode()
            with self.assertRaises(ValueError):
                multipart('multipart/form-data; boundary=B',body)

    def test_only_pipeline_safe_weights_selected(self):
        paths = ['model_index.json','flux2-klein.safetensors','transformer/diffusion_pytorch_model.safetensors',
            'unet/diffusion_pytorch_model.fp16.safetensors','unet/diffusion_pytorch_model.bin',
            'tokenizer/spiece.model','README.md']
        result = selected_files('flux-klein',{'repo':'test','name':'model'},paths)
        self.assertIn('transformer/diffusion_pytorch_model.safetensors',result)
        self.assertNotIn('flux2-klein.safetensors',result)
        self.assertNotIn('unet/diffusion_pytorch_model.bin',result)

class JobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.managers = []

    def tearDown(self):
        for manager in self.managers:
            manager.close()
        self.temp.cleanup()

    def manager(self,code):
        manager = server.JobManager(command_builder=lambda expert,path:[sys.executable,'-c',code,str(path)],job_root=self.root)
        self.managers.append(manager)
        return manager

    def test_completed_result_manifest(self):
        code = "import sys,json;from pathlib import Path;p=Path(sys.argv[1]).parent;(p/'result.txt').write_text('TEST HARNESS');(p/'result.json').write_text(json.dumps({'outputs':[{'kind':'text','name':'result.txt','mime':'text/plain'}],'metadata':{'result_text':'TEST HARNESS'}}))"
        manager = self.manager(code)
        identifier = manager.submit({'expert':'qwen-text'}, {})['id']
        job = wait(manager,identifier)
        self.assertEqual(job['status'],'completed')
        self.assertEqual(job['result_text'],'TEST HARNESS')
        self.assertTrue(job['outputs'][0]['url'].startswith('/api/experts/jobs/'))
        self.assertIsNone(manager.output(identifier,'request.json'))

    def test_failure_never_becomes_output(self):
        manager = self.manager('raise SystemExit(7)')
        identifier = manager.submit({'expert':'qwen-text'}, {})['id']
        job = wait(manager,identifier)
        self.assertEqual(job['status'],'failed')
        self.assertEqual(job['outputs'],[])

    def test_cancellation_and_one_job_limit(self):
        manager = self.manager('import time;time.sleep(30)')
        identifier = manager.submit({'expert':'qwen-text'}, {})['id']
        with self.assertRaises(RuntimeError):
            manager.submit({'expert':'qwen-text'}, {})
        manager.cancel(identifier)
        self.assertEqual(wait(manager,identifier)['status'],'cancelled')

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.http = server.make_server(0)
        self.thread = threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.port = self.http.server_port

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.http.experts.close()
        self.http.jobs.close()

    def request(self,path,headers=None):
        connection = http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        connection.request('GET',path,headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status,data

    def test_expert_status_has_seven_explicit_blocked_states(self):
        with patch.object(server,'installation',return_value=(False,'Not installed')):
            status,data = self.request('/api/experts/status')
        self.assertEqual(status,200)
        experts = json.loads(data)['experts']
        self.assertEqual(len(experts),7)
        self.assertTrue(all(not x['available'] and x['blocked_reason'] for x in experts))

    def test_same_origin_guard(self):
        status,_ = self.request('/api/experts/status',{'Origin':'https://example.com'})
        self.assertEqual(status,403)
        status,_ = self.request('/api/experts/status',{'Host':'attacker.test'})
        self.assertEqual(status,403)

    def test_runtime_not_static_and_native_api_remains(self):
        status,_ = self.request('/advanced_service/.runtime/qwen-text/install-manifest.json')
        self.assertEqual(status,404)
        status,data = self.request('/api/status')
        self.assertEqual(status,200)
        self.assertIn('models',json.loads(data))

if __name__ == '__main__':
    unittest.main()
