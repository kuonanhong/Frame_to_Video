#!/usr/bin/env python3
"""Opt-in REAL Qwen CPU smoke through the HTTP API; never uses a test double."""
import argparse
import json
from pathlib import Path
import platform
import threading
import time
from urllib.request import Request,urlopen
import server
from registry import expert_dir

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir',type=Path,required=True)
    parser.add_argument('--language',choices=('en','zh'),default='en')
    args = parser.parse_args()
    http = server.make_server(0)
    thread = threading.Thread(target=http.serve_forever,daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{http.server_port}'
    prompt = ('請用繁體中文，為清晨湖邊的照片寫兩句旁白，不要標題。' if args.language == 'zh' else
        'Write two brief sentences describing a quiet cinematic scene beside a lake at sunrise. Use plain English.')
    fields = dict(expert='qwen-text',prompt=prompt,max_tokens='96',seed='42')
    boundary = 'FRAME_REAL_QWEN_TEST'
    body = ''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
        for key,value in fields.items()).encode()+f'--{boundary}--\r\n'.encode()
    started = time.time()
    try:
        request = Request(base+'/api/experts/jobs',data=body,headers={'Content-Type':f'multipart/form-data; boundary={boundary}'})
        with urlopen(request,timeout=120) as response:
            job = json.load(response)
        deadline = time.monotonic()+180
        while job['status'] in {'queued','running'} and time.monotonic()<deadline:
            time.sleep(.25)
            with urlopen(base+'/api/experts/jobs/'+job['id'],timeout=10) as response:
                job = json.load(response)
        if job['status'] != 'completed':
            raise RuntimeError(f'Real Qwen smoke failed: {job}')
        with urlopen(base+job['outputs'][0]['url'],timeout=10) as response:
            output = response.read().decode('utf-8')
        if not output.strip() or output != job['result_text']:
            raise RuntimeError('Missing or inconsistent real text output')
        manifest = json.loads((expert_dir('qwen-text')/'install-manifest.json').read_text())
        report = dict(test='real Qwen GGUF CPU HTTP inference; no mocks',platform=platform.platform(),
            machine=platform.machine(),python=platform.python_version(),prompt=prompt,output=output,
            elapsed_seconds=round(time.time()-started,3),job=job,
            model_revisions=manifest['models'],model_files=manifest['files'])
        args.evidence_dir.mkdir(parents=True,exist_ok=True)
        name = 'qwen-zh-real' if args.language == 'zh' else 'qwen-real'
        (args.evidence_dir/(name+'.json')).write_text(json.dumps(report,indent=2,ensure_ascii=False))
        (args.evidence_dir/(name+'.txt')).write_text(output,encoding='utf-8')
        print(json.dumps(dict(status='completed',elapsed_seconds=report['elapsed_seconds'],metadata=job['metadata'],output=output),indent=2))
    finally:
        http.shutdown()
        http.server_close()
        http.experts.close()
        http.jobs.close()

if __name__ == '__main__':
    main()
