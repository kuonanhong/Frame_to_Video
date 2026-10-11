#!/usr/bin/env python3
"""Loopback-only web server + one-at-a-time native CPU image-generation API."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from email import policy
from email.parser import BytesParser
import importlib.metadata
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import unquote, urlsplit
import uuid
from catalog import CATALOG, model_status
from inference import Cancelled, InputError, run, validate_request

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 25 * 1024 * 1024
JOB_RE = re.compile(r'^/api/jobs/([a-f0-9]{32})(?:/(cancel|result\.png))?$')
REQUIRED = ('torch', 'diffusers', 'transformers', 'accelerate', 'safetensors', 'Pillow')


def dependencies():
    result = {}
    for package in REQUIRED:
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = None
    return result


def multipart(content_type, body):
    if not content_type.startswith('multipart/form-data;') or '\r' in content_type or '\n' in content_type:
        raise InputError('Expected multipart/form-data')
    message = BytesParser(policy=policy.default).parsebytes(
        f'Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n'.encode('ascii') + body)
    if not message.is_multipart():
        raise InputError('Malformed multipart body')
    fields, files = {}, {}
    parts = list(message.iter_parts())
    if len(parts) > 16:
        raise InputError('Too many form fields')
    for part in parts:
        if part.is_multipart() or part.get_content_disposition() != 'form-data':
            raise InputError('Invalid multipart part')
        name = part.get_param('name', header='content-disposition')
        if name not in {'expert', 'prompt', 'image', 'mask', 'steps', 'strength', 'guidance', 'image_guidance', 'seed', 'max_side'}:
            raise InputError('Unknown form field')
        if name in fields or name in files:
            raise InputError('Duplicate form field')
        value = part.get_payload(decode=True) or b''
        if name in {'image', 'mask'}:
            files[name] = value
        else:
            if len(value) > 4096:
                raise InputError('Form value too long')
            try:
                fields[name] = value.decode('utf-8')
            except UnicodeDecodeError:
                raise InputError('Form fields must be UTF-8') from None
    return fields, files


class JobManager:
    def __init__(self, runner=run):
        self.runner = runner
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='frame-cpu')
        self.jobs = {}
        self.active = None

    @property
    def busy(self):
        with self.lock:
            return self.active is not None

    def public(self, job):
        return {key: value for key, value in job.items() if key not in {'cancel_event', 'png'}}

    def submit(self, request):
        with self.lock:
            if self.active is not None:
                raise RuntimeError('One CPU job is already running. Wait or cancel it first.')
            # Keep a bounded in-memory result history, not a disk copy of private uploads.
            while len(self.jobs) >= 8:
                del self.jobs[next(iter(self.jobs))]
            identifier = uuid.uuid4().hex
            job = {'id': identifier, 'status': 'queued', 'progress': 0, 'phase': 'queued',
                   'expert': request.expert, 'created': time.time(), 'cancel_event': threading.Event()}
            self.jobs[identifier] = job
            self.active = identifier
            self.pool.submit(self._run, identifier, request)
            return self.public(job)

    def _run(self, identifier, request):
        with self.lock:
            job = self.jobs[identifier]
            job.update(status='running', started=time.time())
        def progress(value, phase):
            with self.lock:
                job.update(progress=value, phase=phase)
        try:
            output, metadata = self.runner(request, job['cancel_event'], progress)
            with self.lock:
                if job['cancel_event'].is_set():
                    job.update(status='cancelled', phase='cancelled')
                else:
                    job.update(status='completed', phase='done', progress=100, png=output,
                               result_url=f'/api/jobs/{identifier}/result.png', metadata=metadata)
        except Cancelled:
            with self.lock:
                job.update(status='cancelled', phase='cancelled')
        except Exception as exc:
            with self.lock:
                # Expected input errors are safe to show. Arbitrary dependency messages may contain local paths.
                message = str(exc) if isinstance(exc, InputError) else f'{type(exc).__name__}: native inference failed. Check pinned dependencies, model integrity and available RAM.'
                job.update(status='failed', phase='failed', error=message)
        finally:
            with self.lock:
                job.update(finished=time.time())
                self.active = None

    def get(self, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            return self.public(job) if job else None

    def cancel(self, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            if job is None:
                return None
            if job['status'] in {'queued', 'running'}:
                job['cancel_event'].set()
                job.update(phase='cancelling')
            return self.public(job)

    def result(self, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            return job.get('png') if job and job['status'] == 'completed' else None

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                job['cancel_event'].set()
        self.pool.shutdown(wait=True, cancel_futures=True)


class Handler(SimpleHTTPRequestHandler):
    server_version = 'FRAME-Local-CPU/4.0'
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.mjs': 'text/javascript', '.wasm': 'application/wasm'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format, *args):
        # Do not log prompts, filenames, image content or request bodies.
        pass

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Cache-Control', 'no-store' if self.path.startswith('/api/') else 'no-cache')
        super().end_headers()

    def guarded(self):
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if port == 80:
            hosts |= {'127.0.0.1', 'localhost'}
        host = self.headers.get('Host', '')
        origin = self.headers.get('Origin')
        if host not in hosts or (origin is not None and origin != f'http://{host}'):
            self.respond(403, {'error': 'Use the same-origin local page at the printed loopback URL.'})
            return False
        if self.headers.get('Sec-Fetch-Site') in {'cross-site', 'same-site'}:
            self.respond(403, {'error': 'Cross-origin browser access is disabled.'})
            return False
        return True

    def respond(self, code, payload):
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_HEAD(self):
        if self.path.startswith('/api/'):
            self.respond(405, {'error': 'Use GET for API status'})
            return
        self._static(head=True)

    def do_GET(self):
        if not self.guarded():
            return
        path = urlsplit(self.path).path
        if path == '/api/status':
            deps = dependencies()
            self.respond(200, {'version': '5.0', 'mode': 'local-cpu', 'device': 'cpu',
                    'models': [model_status(key) for key in CATALOG], 'busy': self.server.jobs.busy,
                    'dependencies': deps, 'dependencies_ready': all(deps.values()),
                    'max_side': 512, 'one_job_at_a_time': True, 'output_kind': 'still-image'})
            return
        match = JOB_RE.fullmatch(path)
        if match:
            identifier, action = match.groups()
            if action == 'result.png':
                data = self.server.jobs.result(identifier)
                if data is None:
                    self.respond(404, {'error': 'Result is not ready or has expired'})
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if action is None:
                job = self.server.jobs.get(identifier)
                self.respond(200 if job else 404, job or {'error': 'Unknown or expired job'})
                return
        if path.startswith('/api/'):
            self.respond(404, {'error': 'Unknown API path'})
            return
        self._static(guarded=True)

    def _static(self, head=False, guarded=False):
        if not guarded and not self.guarded():
            return
        path = Path(unquote(urlsplit(self.path).path).lstrip('/'))
        target = (ROOT / path).resolve()
        # Never serve native weights, environments, dotfiles or files outside the project.
        resolved_parts = target.relative_to(ROOT).parts if target.is_relative_to(ROOT) else ()
        if (not target.is_relative_to(ROOT) or any(p.startswith('.') for p in path.parts + resolved_parts)
                or path.parts[:2] in {('native_cpu', 'models'), ('native_cpu', 'outputs')}
                or resolved_parts[:2] in {('native_cpu', 'models'), ('native_cpu', 'outputs')}
                or target.is_dir() and not (target / 'index.html').is_file()):
            self.respond(404, {'error': 'File not available'})
            return
        if head:
            super().do_HEAD()
        else:
            super().do_GET()

    def do_OPTIONS(self):
        self.respond(405, {'error': 'Cross-origin requests are not enabled'})

    def do_POST(self):
        if not self.guarded():
            return
        path = urlsplit(self.path).path
        match = JOB_RE.fullmatch(path)
        if match and match.group(2) == 'cancel':
            job = self.server.jobs.cancel(match.group(1))
            self.respond(200 if job else 404, job or {'error': 'Unknown job'})
            return
        if path != '/api/jobs':
            self.respond(404, {'error': 'Unknown API path'})
            return
        if self.server.jobs.busy:
            self.respond(409, {'error': 'CPU is busy. Wait or cancel the active job.'})
            return
        try:
            if self.headers.get('Transfer-Encoding'):
                raise InputError('Chunked uploads are not supported')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY:
                self.respond(413, {'error': 'Upload body must be 1 byte–25 MiB'})
                return
            body = self.rfile.read(length)
            if len(body) != length:
                raise InputError('Incomplete upload')
            fields, files = multipart(self.headers.get('Content-Type', ''), body)
            request = validate_request(fields, files)
            if not model_status(request.expert)['installed']:
                self.respond(409, {'error': f'Model {request.expert} is not installed. Download it explicitly with native_cpu/fetch_models.py.'})
                return
            if not all(dependencies().values()):
                self.respond(503, {'error': 'Install Python CPU dependencies first; see native_cpu/README_ZH.md.'})
                return
            self.respond(202, self.server.jobs.submit(request))
        except (InputError, ValueError, UnicodeError) as exc:
            self.respond(400, {'error': str(exc)})
        except RuntimeError as exc:
            self.respond(409, {'error': str(exc)})
        except (TimeoutError, OSError):
            self.close_connection = True


def make_server(port=8787, jobs=None):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.jobs = jobs or JobManager()
    return server


def main():
    parser = argparse.ArgumentParser(description='Serve FRAME and optional local CPU image-generation API on loopback only.')
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('--port must be 1024–65535')
    server = make_server(args.port)
    print(f'FRAME local CPU server: http://127.0.0.1:{server.server_port}/')
    print('Only this computer can connect. Weights are downloaded only by fetch_models.py. Ctrl+C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopping; an active job may take until the next model step to cancel.')
    finally:
        server.server_close()
        server.jobs.close()


if __name__ == '__main__':
    main()
