"""Contract/security/math tests. These tests do NOT run pretrained neural inference."""
from contextlib import contextmanager
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request as HTTPRequest, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog
import inference
import server
import setup_native
from PIL import Image


def picture(size=(320, 200), value='navy', mode='RGB'):
    out = io.BytesIO()
    Image.new(mode, size, value).save(out, format='PNG')
    return out.getvalue()


def request(expert='sd-turbo', **fields):
    return inference.validate_request({'expert': expert, 'prompt': 'A sunny room', **fields},
                                      {'image': picture(), **({'mask': picture(value=255, mode='L')} if expert == 'sd-inpaint' else {})})


class Inputs(unittest.TestCase):
    def test_invalid_numeric_and_model_input(self):
        for changes in ({'strength': 'nan'}, {'steps': '10000'}, {'max_side': '2048'},
                        {'expert': '../../other'}, {'prompt': ''}, {'steps': '1', 'strength': '.5'}):
            with self.subTest(changes=changes), self.assertRaises(inference.InputError):
                request(**changes)

    def test_frontend_turbo_form_allows_zero_guidance(self):
        req = request('sd-turbo', steps='4', strength='0.75', guidance='0', image_guidance='1.5', seed='42', max_side='512')
        self.assertEqual(req.guidance, 0)
        self.assertEqual(req.steps, 4)
        with self.assertRaises(inference.InputError):
            request('instruct-pix2pix', guidance='0')

    def test_inpaint_requires_nonempty_matching_mask(self):
        for files in ({'image': picture()}, {'image': picture(), 'mask': picture((200, 200), 255, 'L')},
                      {'image': picture(), 'mask': picture(value=0, mode='L')}):
            with self.subTest(files=list(files)), self.assertRaises(inference.InputError):
                req = inference.validate_request({'expert': 'sd-inpaint', 'prompt': 'wooden chair'}, files)
                inference.prepare_images(req)

    def test_aspect_preservation_and_limits(self):
        req = inference.validate_request({'expert': 'sd-turbo', 'prompt': 'trees'}, {'image': picture((1600, 1000))})
        image, mask = inference.prepare_images(req)
        self.assertEqual(image.size, (512, 320))
        self.assertIsNone(mask)

    def test_multipart_does_not_use_filename_as_path(self):
        body = (b'--X\r\nContent-Disposition: form-data; name="expert"\r\n\r\nsd-turbo\r\n'
                b'--X\r\nContent-Disposition: form-data; name="image"; filename="../../private.png"\r\n'
                b'Content-Type: image/png\r\n\r\nABC\r\n--X--\r\n')
        fields, files = server.multipart('multipart/form-data; boundary=X', body)
        self.assertEqual(fields, {'expert': 'sd-turbo'})
        self.assertEqual(files, {'image': b'ABC'})

    def test_missing_weights_never_load_or_download(self):
        with tempfile.TemporaryDirectory() as path, patch.object(inference, 'load_pipeline') as loader:
            with self.assertRaises(inference.InputError):
                inference.run(request(), threading.Event(), lambda *_: None, Path(path))
            loader.assert_not_called()


class SetupContracts(unittest.TestCase):
    def test_platform_torch_selection(self):
        self.assertEqual(setup_native.torch_install('Darwin', 'x86_64'), ['torch==2.2.2'])
        self.assertEqual(setup_native.torch_install('Darwin', 'arm64'), ['torch==2.6.0'])
        for system in ['Windows', 'Linux']:
            self.assertEqual(setup_native.torch_install(system, 'AMD64'), ['torch==2.6.0', '--index-url', 'https://download.pytorch.org/whl/cpu'])
        with self.assertRaisesRegex(RuntimeError, 'No verified wheel'):
            setup_native.torch_install('Windows', 'arm64')


class FakeGenerator:
    def __init__(self, device):
        assert device == 'cpu'
    def manual_seed(self, seed):
        return self


@contextmanager
def fake_context():
    yield


class FakePipeline:
    def __init__(self):
        self.received = None
    def __call__(self, callback_on_step_end=None, callback_on_step_end_tensor_inputs=None, **kwargs):
        self.received = kwargs
        callback_on_step_end(self, 0, 0, {'latents': 'mock'})
        return SimpleNamespace(images=[Image.new('RGB', kwargs['image'].size, 'red')], nsfw_content_detected=[False])


class AdapterContracts(unittest.TestCase):
    def test_adapters_arguments_and_mask_preservation(self):
        torch = SimpleNamespace(Generator=FakeGenerator, set_num_threads=lambda _: None, inference_mode=fake_context)
        for expert in catalog.CATALOG:
            with self.subTest(expert=expert):
                pipeline = FakePipeline()
                req = request(expert)
                if expert == 'sd-inpaint':
                    mask = Image.new('L', (320, 200), 0)
                    mask.paste(255, (160, 0, 320, 200))
                    out = io.BytesIO()
                    mask.save(out, format='PNG')
                    req = inference.validate_request({'expert': expert, 'prompt': 'wooden chair'}, {'image': picture(), 'mask': out.getvalue()})
                with patch.dict(sys.modules, {'torch': torch}), patch.object(inference, 'model_status', return_value={'installed': True}), patch.object(inference, 'load_pipeline', return_value=pipeline):
                    data, meta = inference.run(req, threading.Event(), lambda *_: None)
                self.assertEqual(meta['device'], 'cpu')
                self.assertEqual(meta['output_kind'], 'still-image')
                self.assertEqual(pipeline.received['num_images_per_prompt'], 1)
                if expert == 'sd-turbo':
                    self.assertEqual(pipeline.received['guidance_scale'], 0.0)
                elif expert == 'instruct-pix2pix':
                    self.assertEqual(pipeline.received['image_guidance_scale'], 1.5)
                else:
                    image = Image.open(io.BytesIO(data))
                    self.assertEqual(pipeline.received['width'], 320)
                    self.assertEqual(pipeline.received['height'], 200)
                    self.assertEqual(image.getpixel((10, 10)), (0, 0, 128))
                    self.assertEqual(image.getpixel((200, 10)), (255, 0, 0))

    def test_inpaint_refuses_misaligned_model_output(self):
        class WrongSize(FakePipeline):
            def __call__(self, callback_on_step_end=None, callback_on_step_end_tensor_inputs=None, **kwargs):
                return SimpleNamespace(images=[Image.new('RGB', (512, 512))], nsfw_content_detected=[False])
        torch = SimpleNamespace(Generator=FakeGenerator, set_num_threads=lambda _: None, inference_mode=fake_context)
        with patch.dict(sys.modules, {'torch': torch}), patch.object(inference, 'model_status', return_value={'installed': True}), patch.object(inference, 'load_pipeline', return_value=WrongSize()):
            with self.assertRaisesRegex(RuntimeError, 'dimensions'):
                inference.run(request('sd-inpaint'), threading.Event(), lambda *_: None)

    def test_cancellation_is_checked_at_step_boundary(self):
        event = threading.Event()
        pipeline = FakePipeline()
        torch = SimpleNamespace(Generator=FakeGenerator, set_num_threads=lambda _: None, inference_mode=fake_context)
        def progress(value, phase):
            if phase == 'denoising':
                event.set()
        with patch.dict(sys.modules, {'torch': torch}), patch.object(inference, 'model_status', return_value={'installed': True}), patch.object(inference, 'load_pipeline', return_value=pipeline):
            with self.assertRaises(inference.Cancelled):
                inference.run(request(), event, progress)


class JobContracts(unittest.TestCase):
    def test_one_job_and_cancel(self):
        entered = threading.Event()
        release = threading.Event()
        def runner(req, cancel, progress):
            entered.set()
            release.wait(2)
            if cancel.is_set():
                raise inference.Cancelled()
            return b'PNG', {}
        jobs = server.JobManager(runner)
        try:
            first = jobs.submit(request())
            self.assertTrue(entered.wait(1))
            with self.assertRaises(RuntimeError):
                jobs.submit(request())
            jobs.cancel(first['id'])
            release.set()
            for _ in range(100):
                if not jobs.busy:
                    break
                time.sleep(.01)
            self.assertEqual(jobs.get(first['id'])['status'], 'cancelled')
            self.assertIsNone(jobs.result(first['id']))
        finally:
            release.set()
            jobs.close()


class HTTPContracts(unittest.TestCase):
    def setUp(self):
        self.server = server.make_server(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.jobs.close()

    def fetch(self, path, headers=None, data=None):
        req = HTTPRequest(self.origin + path, headers=headers or {}, data=data)
        try:
            with urlopen(req, timeout=2) as response:
                return response.status, response.read(), response.headers
        except HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    def test_status_reports_missing_actual_weights(self):
        code, body, headers = self.fetch('/api/status')
        self.assertEqual(code, 200)
        state = json.loads(body)
        self.assertEqual(state['mode'], 'local-cpu')
        self.assertEqual(len(state['models']), 3)
        self.assertTrue(all(not item['weights_bundled'] for item in state['models']))
        self.assertEqual(headers['Cache-Control'], 'no-store')

    def test_cross_origin_and_host_rejected(self):
        for headers in ({'Origin': 'https://example.com'}, {'Host': 'evil.example'}, {'Sec-Fetch-Site': 'cross-site'}):
            with self.subTest(headers=headers):
                code, _, _ = self.fetch('/api/status', headers)
                self.assertEqual(code, 403)

    def test_no_native_weights_dotfiles_or_traversal(self):
        for path in ('/native_cpu/models/model.safetensors', '/.env', '/%2e%2e/%2e%2e/etc/passwd', '/native_cpu/'):
            with self.subTest(path=path):
                self.assertEqual(self.fetch(path)[0], 404)

    def test_successful_http_job_and_result_with_mock_inference(self):
        self.server.jobs.close()
        self.server.jobs = server.JobManager(lambda req, cancel, progress: (picture(), {'output_kind': 'still-image'}))
        body = (b'--Y\r\nContent-Disposition: form-data; name="expert"\r\n\r\nsd-turbo\r\n'
                b'--Y\r\nContent-Disposition: form-data; name="prompt"\r\n\r\nA sunny room\r\n'
                b'--Y\r\nContent-Disposition: form-data; name="guidance"\r\n\r\n0\r\n'
                b'--Y\r\nContent-Disposition: form-data; name="image"; filename="room.png"\r\n'
                b'Content-Type: image/png\r\n\r\n' + picture() + b'\r\n--Y--\r\n')
        with patch.object(server, 'model_status', return_value={'installed': True}), patch.object(server, 'dependencies', return_value={'torch': 'mock'}):
            code, value, _ = self.fetch('/api/jobs', {'Content-Type': 'multipart/form-data; boundary=Y'}, body)
        self.assertEqual(code, 202)
        job = json.loads(value)
        for _ in range(100):
            _, value, _ = self.fetch('/api/jobs/' + job['id'])
            job = json.loads(value)
            if job['status'] == 'completed':
                break
            time.sleep(.01)
        self.assertEqual(job['status'], 'completed')
        code, png, headers = self.fetch(job['result_url'])
        self.assertEqual(code, 200)
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertEqual(Image.open(io.BytesIO(png)).size, (320, 200))

    def test_malformed_request_and_missing_weight_error(self):
        self.assertEqual(self.fetch('/api/jobs', {'Content-Type': 'application/json'}, b'{}')[0], 400)
        parts = []
        for name, value in [('expert', 'sd-turbo'), ('prompt', 'sunny')]:
            parts.append(f'--X\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(b'--X\r\nContent-Disposition: form-data; name="image"; filename="x.png"\r\nContent-Type: image/png\r\n\r\n' + picture() + b'\r\n--X--\r\n')
        with patch.object(server, 'model_status', return_value={'installed': False}):
            code, body, _ = self.fetch('/api/jobs', {'Content-Type': 'multipart/form-data; boundary=X'}, b''.join(parts))
        self.assertEqual(code, 409)
        self.assertIn('not installed', json.loads(body)['error'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
