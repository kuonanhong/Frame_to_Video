"""Regenerate standalone expert docs with the bundled standard-library renderer."""
from pathlib import Path
import importlib.util
import re
BASE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('frame_docs_renderer',BASE.parent/'native_cpu/render_readme.py')
renderer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)
style=re.search(r'<style>(.*?)</style>',(BASE.parent/'V5_START.html').read_text('utf-8'),re.S).group(1)
for stem in ('README','VALIDATION'):
    body=renderer.render((BASE/(stem+'.md')).read_text('utf-8'))
    intro='<p><a href="../V5_START.html">繁體中文完整操作教學</a> · <a href="../index.html">工作台</a> · <a href="../MODEL_REALITY_GUIDE.html">模型與論文</a></p>'
    if stem=='README':
        intro+='<p class="note">先安裝所選模型，再啟動本機服務。本頁保留完整技術原文；繁體中文的安裝順序與各模型用途，請見上方「完整操作教學」。大型模型權重不隨網頁包預載，首次安裝需網路與磁碟空間；完成後使用本機檔案推論。</p>'
    (BASE/(stem+'.html')).write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FRAME v5 experts '+stem+'</title><style>'+style+'</style><body>'+intro+body+'</body></html>','utf-8')
