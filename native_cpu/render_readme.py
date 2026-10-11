"""Build the standalone HTML guide with only Python's standard library."""
from pathlib import Path
import html
import re

ROOT = Path(__file__).resolve().parent


def inline(value):
    value = html.escape(value)
    value = re.sub(r'`([^`]+)`', r'<code>\1</code>', value)
    value = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', value)
    value = re.sub(r'(https?://[^\s<>]+)', r'<a href="\1" rel="noreferrer">\1</a>', value)
    return value


def render(markdown):
    lines = markdown.splitlines()
    output = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('```'):
            code = []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                code.append(lines[i]); i += 1
            output.append('<pre><code>' + html.escape('\n'.join(code)) + '</code></pre>')
        elif line.startswith('#'):
            match = re.match(r'^(#{1,6}) (.*)', line)
            if match:
                level = len(match.group(1))
                output.append(f'<h{level}>' + inline(match.group(2)) + f'</h{level}>')
        elif line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].startswith('|'):
                row = lines[i].strip('|').split('|')
                if not all(re.fullmatch(r'[ :\-]+', cell) for cell in row):
                    rows.append(row)
                i += 1
            cells = []
            for index, row in enumerate(rows):
                tag = 'th' if index == 0 else 'td'
                cells.append('<tr>' + ''.join(f'<{tag}>' + inline(cell.strip()) + f'</{tag}>' for cell in row) + '</tr>')
            output.append('<div class="table"><table>' + ''.join(cells) + '</table></div>')
            continue
        elif line.startswith('- '):
            items = []
            while i < len(lines) and lines[i].startswith('- '):
                items.append('<li>' + inline(lines[i][2:]) + '</li>'); i += 1
            output.append('<ul>' + ''.join(items) + '</ul>')
            continue
        elif line.strip():
            output.append('<p>' + inline(line) + '</p>')
        i += 1
    return '\n'.join(output)


if __name__ == '__main__':
    body = render((ROOT / 'README_ZH.md').read_text('utf-8'))
    page = '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FRAME 本機 CPU 圖片專家安裝指南</title>
<style>body{margin:0;background:#f4f7f6;color:#183332;font:17px/1.8 system-ui,-apple-system,sans-serif}main{max-width:980px;margin:auto;padding:36px 22px 80px}h1{font-size:2rem;line-height:1.35}h2{margin-top:2.5rem;border-top:1px solid #cedcda;padding-top:1.5rem}h3{margin-top:1.8rem}a{color:#006d69;overflow-wrap:anywhere}p,li{overflow-wrap:anywhere}code{font-family:ui-monospace,monospace;font-size:.9em;background:#e2eeeb;padding:2px 4px;border-radius:4px}pre{overflow:auto;background:#102b2a;color:#e8f8f4;padding:18px;border-radius:12px}pre code{background:none;padding:0;color:inherit}.table{overflow:auto}table{border-collapse:collapse;font-size:.9rem;width:100%}td,th{border:1px solid #b9ceca;padding:10px;text-align:left;min-width:110px}th{background:#d9eae5}strong{color:#0b5753}.top{font-size:.9rem}@media(max-width:600px){body{font-size:16px}main{padding:22px 15px}h1{font-size:1.7rem}}</style>
<main><p class="top"><a href="../index.html">← FRAME 主頁</a> · <a href="README_ZH.md">Markdown 原稿</a></p>''' + body + '</main></html>'
    (ROOT / 'README.html').write_text(page, 'utf-8')
