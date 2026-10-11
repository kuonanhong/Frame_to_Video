"""FRAME local static host, no inference server or data collection."""
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
import os,webbrowser
os.chdir(Path(__file__).resolve().parent)
class Handler(SimpleHTTPRequestHandler):
 extensions_map={**SimpleHTTPRequestHandler.extensions_map,'.mjs':'application/javascript','.wasm':'application/wasm','.json':'application/json'}
 def log_message(self,*args):pass
if __name__=='__main__':
 address=('127.0.0.1',8000)
 try:server=ThreadingHTTPServer(address,Handler)
 except OSError as e:
  print('Port 8000 is busy. Close the previous server, or use python3 -m http.server 8001 --bind 127.0.0.1.');raise SystemExit(1) from e
 print('FRAME Story: http://127.0.0.1:8000/  (Ctrl+C to stop)');webbrowser.open('http://127.0.0.1:8000/')
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()
