#!/usr/bin/env python3
"""Same-origin FRAME server with isolated subprocess-based optional experts."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlsplit
import uuid

from registry import BASE, RUNTIME, EXPERTS, expert_dir, python_path
from validation import MAX_BODY, multipart, validate
from hardware import memory_check

ROOT = BASE.parent
sys.path.insert(0,str(ROOT/'native_cpu'))
spec = importlib.util.spec_from_file_location('frame_native_server',ROOT/'native_cpu'/'server.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
JOB_RE = re.compile(r'^/api/experts/jobs/([a-f0-9]{32})(?:/(cancel|[a-z0-9_-]+\.(?:png|mp4|txt)))?$')
_status_cache = {}
_status_lock = threading.Lock()

def installation_manifest(expert):
    """Prefer a valid runtime manifest; otherwise accept a separate weights receipt."""
    for name in ('install-manifest.json', 'weights-manifest.json'):
      try:
        path = expert_dir(expert)/name
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if manifest.get('expert') != expert or not manifest.get('files') or not manifest.get('models'):
            raise ValueError('Incomplete installation manifest')
        for item in manifest['files']:
            target = (expert_dir(expert)/item['path']).resolve()
            if not target.is_relative_to(expert_dir(expert)) or not target.is_file() or target.stat().st_size != item['bytes']:
                raise ValueError('Missing or changed installed model file; run installer --verify')
        return manifest
      except (OSError,ValueError,KeyError,TypeError):
        continue
    raise ValueError('No valid installation manifest')

def installation(expert):
    """Require a manifest and every recorded file, not a model directory alone."""
    try:
        installation_manifest(expert)
        return True, None
    except ValueError:
        return False, f'Install {expert} explicitly with advanced_service/install.py; weights are not bundled.'

def status(expert):
    info = EXPERTS[expert]
    installed, reason = installation(expert)
    ready, details = False, {}
    memory = memory_check(expert)
    python = python_path(expert)
    try:
        weights_only = installation_manifest(expert).get('install_mode') == 'weights-only'
    except ValueError:
        weights_only = False
    if installed and weights_only:
        reason = ('Weights downloaded only / 權重已下載；尚未安裝可執行環境。'
            'Install the inference runtime on a compatible host to generate. '
            'The modern v5 torch 2.6 profiles cannot be installed natively on Intel macOS; downloading again will not change that.')
        details = {'ready':False, 'missing':['Inference runtime not installed by weights-only download']}
    elif installed and not memory['ready']:
        # Even importing several independent Torch runtimes can consume RAM. Do
        # not spawn those checks when the expert is already memory-blocked.
        reason = memory['warning']
        details = {'missing':['Runtime import check deferred until memory preflight succeeds']}
    elif installed and python.is_file():
        stamp = (python.stat().st_mtime_ns,(expert_dir(expert)/'install-manifest.json').stat().st_mtime_ns)
        with _status_lock:
            cache = _status_cache.get(expert)
        if cache and cache['stamp'] == stamp and time.monotonic()-cache['time'] < 60:
            details = cache['details']
        else:
            try:
                result = subprocess.run([str(python),str(BASE/'worker.py'),'--check',expert],capture_output=True,
                    text=True,timeout=90,env=worker_env())
                details = json.loads(result.stdout) if result.returncode == 0 else {'ready':False,'missing':['Runtime import check failed']}
            except (OSError,ValueError,subprocess.TimeoutExpired):
                details = {'ready':False,'missing':['Runtime import check failed or timed out']}
            with _status_lock:
                _status_cache[expert] = dict(stamp=stamp,time=time.monotonic(),details=details)
        ready = details.get('ready') is True
        if not ready:
            reason = 'Dependency check blocked: '+', '.join(details.get('missing',[]))
    elif installed:
        reason = 'Expert Python environment missing; rerun its installer.'
    if installed and ready and not memory['ready']:
        reason = memory['warning']
    return {key:info[key] for key in ('label','kind','requires_image','requires_driving','cpu_note','defaults')} | dict(
        id=expert,installed=installed,weights_downloaded=installed,install_mode=('weights-only' if weights_only else 'runtime') if installed else 'none',
        dependencies_ready=ready,available=installed and ready and memory['ready'],
        memory=memory,hardware_ready=memory['ready'],
        blocked_reason=reason,dependencies=details.get('versions',{}),integrity='manifest file sizes; --verify rehashes SHA-256')

def worker_env():
    env = os.environ.copy()
    env.update(FRAME_EXPERT_HOME=str(RUNTIME),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
        HF_HUB_DISABLE_TELEMETRY='1',CUDA_VISIBLE_DEVICES='',TOKENIZERS_PARALLELISM='false')
    # Model workers need no credentials; never inherit commonly used provider tokens.
    for name in list(env):
        if name.endswith(('_API_KEY','_ACCESS_TOKEN')) or name in {'HF_TOKEN','HUGGING_FACE_HUB_TOKEN','OPENAI_API_KEY','ANTHROPIC_API_KEY'}:
            env.pop(name,None)
    return env

class JobManager:
    def __init__(self, command_builder=None, job_root=None, keep_outputs=False):
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1,thread_name_prefix='frame-expert')
        self.jobs = {}
        self.active = None
        self.job_root = Path(job_root or RUNTIME/'jobs')
        self.keep_outputs = keep_outputs
        # Internal injection is used only by stdlib tests. There is no command input in the API.
        self.command_builder = command_builder or (lambda expert,request:[str(python_path(expert)),str(BASE/'worker.py'),'--request',str(request)])

    @property
    def busy(self):
        with self.lock:
            return self.active is not None

    def public(self, job):
        result = {key:value for key,value in job.items() if key not in {'directory','process','cancel'}}
        try:
            progress = json.loads((job['directory']/'progress.json').read_text())
            if result['status'] == 'running':
                result['phase'] = progress.get('phase',result['phase'])
        except (OSError,ValueError):
            pass
        return result

    def submit(self, request, files):
        with self.lock:
            if self.active is not None:
                raise RuntimeError('An expert is already running. Wait or cancel it first.')
            while len(self.jobs) >= 8:
                oldest = next(iter(self.jobs))
                old = self.jobs.pop(oldest)
                if not self.keep_outputs:
                    shutil.rmtree(old['directory'],ignore_errors=True)
            identifier = uuid.uuid4().hex
            directory = self.job_root/identifier
            directory.mkdir(parents=True,mode=0o700)
            request = dict(request)
            for key,data in files.items():
                target = directory/('input-image' if key == 'image' else 'driving.mp4')
                target.write_bytes(data)
                request[key+'_path'] = str(target.resolve())
            request_path = directory/'request.json'
            request_path.write_text(json.dumps(request,ensure_ascii=False),encoding='utf-8')
            job = dict(id=identifier,expert=request['expert'],status='queued',phase='Queued',
                created=time.time(),directory=directory,process=None,cancel=threading.Event(),outputs=[])
            self.jobs[identifier] = job
            self.active = identifier
            self.pool.submit(self._run,identifier,request_path)
            return self.public(job)

    def _run(self, identifier, request_path):
        with self.lock:
            job = self.jobs[identifier]
            if job['cancel'].is_set():
                job.update(status='cancelled',phase='Cancelled',finished=time.time())
                self.active = None
                return
            job.update(status='running',phase='Starting isolated expert process',started=time.time())
        try:
            with (job['directory']/'worker.log').open('wb') as log:
                command = self.command_builder(job['expert'],request_path)
                with self.lock:
                    if job['cancel'].is_set():
                        raise InterruptedError('Cancelled')
                    process = subprocess.Popen(command,stdout=log,stderr=log,env=worker_env(),
                        cwd=str(BASE),start_new_session=(os.name != 'nt'))
                    job['process'] = process
                code = process.wait()
            if job['cancel'].is_set():
                raise InterruptedError('Cancelled')
            if code:
                raise RuntimeError(f'Expert process exited with code {code}. See its local worker.log for dependency, memory or model errors.')
            result = json.loads((job['directory']/'result.json').read_text(encoding='utf-8'))
            outputs = []
            for item in result['outputs']:
                name = item['name']
                if not re.fullmatch(r'[a-z0-9_-]+\.(png|mp4|txt)',name) or item['kind'] not in {'image','video','text'}:
                    raise ValueError('Invalid result manifest')
                target = job['directory']/name
                if not target.is_file() or target.is_symlink() or not target.stat().st_size:
                    raise ValueError('Missing or empty generated output')
                outputs.append(dict(item,url=f'/api/experts/jobs/{identifier}/{name}'))
            if not outputs:
                raise ValueError('No output from expert')
            with self.lock:
                if job['cancel'].is_set():
                    raise InterruptedError('Cancelled')
                metadata = result.get('metadata',{})
                job.update(status='completed',phase='Complete',outputs=outputs,metadata=metadata)
                if 'result_text' in metadata:
                    job['result_text'] = metadata['result_text']
        except InterruptedError:
            with self.lock:
                job.update(status='cancelled',phase='Cancelled')
        except Exception as exc:
            with self.lock:
                job.update(status='failed',phase='Failed',error=f'{type(exc).__name__}: {exc}')
        finally:
            with self.lock:
                job.update(finished=time.time(),process=None)
                self.active = None

    def get(self,identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            return self.public(job) if job else None

    def cancel(self,identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            if job and job['status'] in {'queued','running'}:
                job['cancel'].set()
                job['phase'] = 'Cancelling'
                process = job['process']
                if process and process.poll() is None:
                    threading.Thread(target=self._stop_process,args=(process,),daemon=True).start()
            return self.public(job) if job else None

    @staticmethod
    def _stop_process(process):
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,check=False)
            else:
                os.killpg(process.pid,signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == 'nt':
                    process.kill()
                else:
                    os.killpg(process.pid,signal.SIGKILL)
        except (OSError,subprocess.TimeoutExpired):
            if process.poll() is None:
                process.kill()

    def output(self,identifier,name):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job or job['status'] != 'completed':
                return None
            item = next((item for item in job['outputs'] if item['name'] == name),None)
            if not item:
                return None
            return job['directory']/name,item['mime']

    def close(self):
        with self.lock:
            for identifier in self.jobs:
                self.cancel(identifier)
        self.pool.shutdown(wait=True,cancel_futures=True)
        if not self.keep_outputs:
            for job in self.jobs.values():
                shutil.rmtree(job['directory'],ignore_errors=True)

class Handler(native.Handler):
    server_version = 'FRAME-Experts/5.0'

    def _static(self,head=False,guarded=False):
        target = (ROOT/unquote(urlsplit(self.path).path).lstrip('/')).resolve()
        if target.is_relative_to(RUNTIME):
            self.respond(404,{'error':'File not available'})
            return
        super()._static(head=head,guarded=guarded)

    def do_GET(self):
        path = urlsplit(self.path).path
        if not path.startswith('/api/experts/'):
            return super().do_GET()
        if not self.guarded():
            return
        if path == '/api/experts/status':
            with ThreadPoolExecutor(max_workers=7) as checks:
                experts = list(checks.map(status,EXPERTS))
            self.respond(200,dict(version='5.0',mode='local-cpu',experts=experts,
                busy=self.server.experts.busy or self.server.jobs.busy,one_job_at_a_time=True))
            return
        match = JOB_RE.fullmatch(path)
        if match:
            identifier,action = match.groups()
            if action is None:
                job = self.server.experts.get(identifier)
                self.respond(200 if job else 404,job or {'error':'Unknown or expired expert job'})
                return
            if action != 'cancel':
                output = self.server.experts.output(identifier,action)
                if output:
                    file,mime = output
                    self.send_response(200)
                    self.send_header('Content-Type',mime)
                    self.send_header('Content-Length',str(file.stat().st_size))
                    self.end_headers()
                    with file.open('rb') as stream:
                        shutil.copyfileobj(stream,self.wfile)
                    return
        self.respond(404,{'error':'Unknown or expired expert output'})

    def do_POST(self):
        path = urlsplit(self.path).path
        if not path.startswith('/api/experts/'):
            with self.server.admission_lock:
                if path == '/api/jobs' and self.server.experts.busy:
                    self.respond(409,{'error':'An advanced expert is using the CPU. Wait or cancel it first.'})
                    return
                return super().do_POST()
        if not self.guarded():
            return
        match = JOB_RE.fullmatch(path)
        if match and match.group(2) == 'cancel':
            job = self.server.experts.cancel(match.group(1))
            self.respond(200 if job else 404,job or {'error':'Unknown expert job'})
            return
        if path != '/api/experts/jobs':
            self.respond(404,{'error':'Unknown expert API path'})
            return
        try:
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('Chunked uploads are not supported')
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= MAX_BODY:
                self.respond(413,{'error':'Upload body must be 1 byte–80 MiB'})
                return
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError('Incomplete upload')
            fields,files = multipart(self.headers.get('Content-Type',''),body)
            request = validate(fields,files)
            readiness = status(request['expert'])
            if not readiness['available']:
                self.respond(409,{'error':readiness['blocked_reason']})
                return
            with self.server.admission_lock:
                if self.server.jobs.busy:
                    raise RuntimeError('The native image expert is using the CPU. Wait or cancel it first.')
                self.respond(202,self.server.experts.submit(request,files))
        except (ValueError,UnicodeError) as exc:
            self.respond(400,{'error':str(exc)})
        except RuntimeError as exc:
            self.respond(409,{'error':str(exc)})
        except (OSError,TimeoutError):
            self.close_connection = True

def make_server(port=8787,experts=None,jobs=None):
    server = native.ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads = True
    server.jobs = jobs or native.JobManager()
    server.experts = experts or JobManager()
    server.admission_lock = threading.RLock()
    return server

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8787)
    parser.add_argument('--keep-outputs',action='store_true',help='Retain local job inputs and outputs after shutdown')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('--port must be 1024–65535')
    server = make_server(args.port,experts=JobManager(keep_outputs=args.keep_outputs))
    print(f'FRAME v5: http://127.0.0.1:{server.server_port}/ (CPU, loopback only)')
    print('Optional expert weights and environments must be installed explicitly. Ctrl+C stops jobs.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.experts.close()
        server.jobs.close()

if __name__ == '__main__':
    main()
