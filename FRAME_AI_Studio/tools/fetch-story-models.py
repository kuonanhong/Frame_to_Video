#!/usr/bin/env python3
"""Fetch pinned, public FRAME CPU narration/voice assets. Stdlib only; no API key."""
import argparse, concurrent.futures, hashlib, json, pathlib, urllib.request, time
ROOT=pathlib.Path(__file__).resolve().parents[1]
MODELS=ROOT/'story/models'
CHUNK=40*1024*1024
SMOL='https://huggingface.co/onnx-community/SmolLM2-135M-Instruct-ONNX-MHA/resolve/5b6682c7c9df18f004bfb7e635cba3f3d98537d8/'
PIPER='https://huggingface.co/rhasspy/piper-voices/resolve/c10ece1aade47bb51c153c893d14e5bf8e5b7117/'
VOICES={
 'zh_CN-huayan-medium':'zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx',
 'en_US-amy-low':'en/en_US/amy/low/en_US-amy-low.onnx',
 'en_GB-alan-low':'en/en_GB/alan/low/en_GB-alan-low.onnx',
 'fr_FR-siwis-low':'fr/fr_FR/siwis/low/fr_FR-siwis-low.onnx',
 'de_DE-eva_k-x_low':'de/de_DE/eva_k/x_low/de_DE-eva_k-x_low.onnx',
 'es_ES-carlfm-x_low':'es/es_ES/carlfm/x_low/es_ES-carlfm-x_low.onnx',
}
def targets(voices):
 out=[(SMOL+x,'smollm2/'+x) for x in ['config.json','generation_config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json','README.md','onnx/model_quantized.onnx']]
 out.append(('https://www.apache.org/licenses/LICENSE-2.0.txt','smollm2/LICENSE'))
 for voice in voices:
  path=VOICES[voice]
  out.extend([(PIPER+path,'piper/'+voice+'.onnx'),(PIPER+path+'.json','piper/'+voice+'.onnx.json'),(PIPER+path.rsplit('/',1)[0]+'/MODEL_CARD','piper/'+voice+'.MODEL_CARD')])
 for suffix in ['wasm','data']:
  out.append(('https://cdn.jsdelivr.net/npm/@diffusionstudio/piper-wasm@1.0.0/build/piper_phonemize.'+suffix,'phonemizer/piper_phonemize.'+suffix))
 return out

def get(item):
 url,rel=item; path=MODELS/rel;path.parent.mkdir(parents=True,exist_ok=True)
 cached=path.with_suffix(path.suffix+'.parts.json')
 if cached.exists():
  record=json.loads(cached.read_text())
  if all((path.parent/p['name']).exists() and (path.parent/p['name']).stat().st_size==p['bytes'] for p in record['pieces']):return record
 for attempt in range(3):
  try:
   if not path.exists():
    tmp=path.with_suffix(path.suffix+'.download')
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'FRAME-CPU-Asset-Downloader/1.0'}),timeout=90) as r,tmp.open('wb') as f:
     while True:
      b=r.read(1024*1024)
      if not b:break
      f.write(b)
    tmp.replace(path)
   data=path.read_bytes();record={'url':url,'path':rel,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
   if len(data)>CHUNK:
    record['pieces']=[]
    for i,start in enumerate(range(0,len(data),CHUNK)):
     piece=data[start:start+CHUNK];name=path.name+f'.part{i:03d}';(path.parent/name).write_bytes(piece)
     record['pieces'].append({'name':name,'bytes':len(piece),'sha256':hashlib.sha256(piece).hexdigest()})
    cached.write_text(json.dumps(record,indent=2));path.unlink()
   print('OK',rel,len(data),flush=True);return record
  except Exception as e:
   print('Retry',rel,attempt+1,str(e),flush=True)
   if attempt==2:return {'url':url,'path':rel,'error':str(e)}
   time.sleep(1)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--voices',nargs='*',default=['zh_CN-huayan-medium','en_US-amy-low','en_GB-alan-low']);ap.add_argument('--all-small-voices',action='store_true');args=ap.parse_args()
 voices=list(VOICES) if args.all_small_voices else args.voices
 if any(v not in VOICES for v in voices):raise SystemExit('Unknown voice. See VOICES in this script.')
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:assets=list(pool.map(get,targets(voices)))
 manifest={'schema':1,'checkedOn':'2026-10-09','models':{'narration':{'id':'SmolLM2-135M-Instruct-ONNX-MHA','revision':'5b6682c7c9df18f004bfb7e635cba3f3d98537d8','license':'Apache-2.0','language':['en'],'dtype':'q8'},'piper':{'id':'rhasspy/piper-voices','revision':'c10ece1aade47bb51c153c893d14e5bf8e5b7117','voices':voices,'license':'See each voice MODEL_CARD'}},'assets':assets}
 (MODELS/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 failures=[x for x in assets if 'error'in x]
 print('Complete:',len(assets)-len(failures),'/',len(assets),'logical assets. Total bytes:',sum(x.get('bytes',0)for x in assets),flush=True)
 if failures:raise SystemExit(1)
if __name__=='__main__':main()
