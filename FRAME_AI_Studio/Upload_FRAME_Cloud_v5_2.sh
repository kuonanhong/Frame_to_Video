#!/bin/bash
# macOS Bash 3.2 / Linux / Git Bash. All Git writes are isolated from the source.
set -eu
if [ -n "${FRAME_PYTHON:-}" ]; then
  PYTHON_BIN="$FRAME_PYTHON"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN=python3.11
else
  PYTHON_BIN=python3
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo '需要 Python 3.10 以上；建議使用現有 python3.11。可設定 FRAME_PYTHON。' >&2
  exit 2
fi
exec "$PYTHON_BIN" - "$0" "$@" <<'PYTHON'
import argparse, hashlib, json, os, pathlib, re, shutil, stat, subprocess, sys, tempfile, time

if sys.version_info < (3, 10):
    raise SystemExit("請使用 Python 3.10 以上，例如 FRAME_PYTHON=python3.11 bash Upload_FRAME_Cloud_v5_2.sh")

MiB = 1024 * 1024
DEFAULT_REMOTE = 'git@github.com:kuonanhong/Frame_to_Video.git'
PREFIX = 'FRAME_AI_Studio/'
SCRIPT = pathlib.Path(sys.argv.pop(1)).resolve()

class Stop(Exception):
    pass

def fail(message):
    raise Stop(message)

parser = argparse.ArgumentParser(description='FRAME v5.2：七模型檢查、SSH 差異上傳與完整後發布。預設預覽；--push 才推送。')
parser.add_argument('--source', help='FRAME_AI_Studio 資料夾；支援拖曳含空白的路徑')
mode = parser.add_mutually_exclusive_group()
mode.add_argument('--dry-run', action='store_true', help='比對雜湊、顯示計畫，不推送（預設）')
mode.add_argument('--audit-models', action='store_true', help='離線檢查七模型收據與檔案大小，不連 GitHub')
mode.add_argument('--verify-models', action='store_true', help='離線逐檔 SHA-256 驗證七模型；數十 GB 需要時間')
mode.add_argument('--push', action='store_true', help='分批推送暫存分支，再一次更新 main')
parser.add_argument('--stage-only', action='store_true', help='搭配 --push，只上傳暫存分支、不更新 main')
parser.add_argument('--state-dir', help='獨立 Git 快取位置；不可位於來源資料夾內')
parser.add_argument('--batch-mib', type=int, default=64, help='每批新檔案目標大小 MiB（1–256，預設 64）；單檔不拆開')
parser.add_argument('--name', help='此部署提交的作者姓名；預設讀取 Git user.name')
parser.add_argument('--email', help='此部署提交的作者 email；預設讀取 Git user.email')
parser.add_argument('--remote', default=DEFAULT_REMOTE, help='預設固定 GitHub SSH 網址；亦接受本機 bare Git 路徑供測試')
parser.add_argument('--report', help='模型檢查 JSON 報告位置；僅供 --audit-models/--verify-models')
args = parser.parse_args()

def original_config(key):
    p = subprocess.run(['git', 'config', '--get', key], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return p.stdout.decode('utf-8', 'replace').strip() if p.returncode == 0 else ''

def digest(data):
    return hashlib.sha256(data).hexdigest()

def source_root():
    def valid(p):
        return (p/'index.html').is_file() and (p/'story').is_dir()
    if args.source:
        p = pathlib.Path(args.source).expanduser().resolve()
        # Accept either the actual project or its single containing folder.
        if not valid(p) and valid(p/'FRAME_AI_Studio'):
            p = p/'FRAME_AI_Studio'
        if not valid(p):
            fail('--source 請指向含 index.html 與 story/ 的 FRAME_AI_Studio 資料夾。')
        return p
    cwd = pathlib.Path.cwd().resolve()
    if valid(cwd):
        return cwd
    candidates = []
    for parent in (SCRIPT.parent, SCRIPT.parent.parent, cwd, cwd.parent):
        for p in (parent, parent/'FRAME_AI_Studio'):
            p = p.resolve()
            if valid(p) and p not in candidates:
                candidates.append(p)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        fail('找到多份 FRAME 專案；請加 --source 明確指定：\n'+'\n'.join(str(p) for p in candidates))
    fail('找不到 FRAME_AI_Studio。請把此 .sh 放入該資料夾，或加 --source "完整/FRAME_AI_Studio"。')

"""Read-only FRAME model audit. Standard library only; safe to embed in an uploader.

No model is imported, executed, installed, or fetched. A complete receipt is
evidence of local recorded files, not evidence that inference works.
"""
import hashlib
import json
import os
import platform
import re
from pathlib import Path, PurePosixPath


_FRAME_EXPERT_IDS = (
    "qwen-text", "liveportrait", "controlnet-canny", "multidiffusion",
    "flux-klein", "ltx-video", "cogvideox",
)
_FRAME_INTEL_BLOCKED = {"liveportrait", "flux-klein", "ltx-video", "cogvideox"}
_FRAME_STATUS_ZH = {
    "missing": "未找到下載紀錄",
    "partial": "不完整或無法驗證",
    "weights-only": "權重完整；執行環境未確認",
    "runtime-present-unverified": "權重及環境檔存在；推論未驗證",
}


def _frame_read_json(path, limit=16 * 1024 * 1024):
    if path.stat().st_size > limit:
        raise ValueError("紀錄檔超過讀取上限")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("紀錄內容必須為 JSON 物件")
    return value


def _frame_safe_path(home, name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("不安全的紀錄路徑")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts or str(relative) != name:
        raise ValueError("不安全的紀錄路徑：" + name)
    result = home.joinpath(*relative.parts).resolve()
    if result == home.resolve() or not result.is_relative_to(home.resolve()):
        raise ValueError("紀錄路徑超出模型目錄：" + name)
    return result


def _frame_sha256(path, cache):
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key not in cache:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        cache[key] = digest.hexdigest()
    return cache[key]


def _frame_receipt(home, expert, name, verify, hash_cache):
    """Validate one receipt, tracking model and runtime artifacts separately."""
    result = dict(receipt=name, valid=False, weights_complete=False,
                  artifacts_complete=False, runtime_mode=False, model_files=0,
                  checked_model_files=0, recorded_model_bytes=0,
                  checked_model_bytes=0, issues=[])
    path = home / name
    if not path.is_file():
        return None
    try:
        manifest = _frame_read_json(path)
        if manifest.get("expert") != expert:
            raise ValueError("紀錄模型 ID 不符")
        if manifest.get("schema") not in (1, 2):
            raise ValueError("無法辨識紀錄格式版本")
        models, files = manifest.get("models"), manifest.get("files")
        if not isinstance(models, list) or not models or not isinstance(files, list) or not files:
            raise ValueError("models/files 紀錄為空或格式錯誤")
        mode = manifest.get("install_mode", "runtime" if name == "install-manifest.json" else "weights-only")
        if mode not in ("runtime", "weights-only"):
            raise ValueError("無法辨識安裝類型")
        expected, names = set(), set()
        for model in models:
            if not isinstance(model, dict):
                raise ValueError("模型元件紀錄格式錯誤")
            component = model.get("name")
            if not isinstance(component, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", component) or component in (".", "..") or component in names:
                raise ValueError("模型元件名稱錯誤或重複")
            names.add(component)
            if not isinstance(model.get("repo"), str) or not model["repo"].strip():
                raise ValueError("缺少模型來源紀錄")
            if not isinstance(model.get("revision"), str) or not re.fullmatch(r"[a-fA-F0-9]{40}", model["revision"]):
                raise ValueError("缺少固定模型版本 SHA")
            members = model.get("files")
            if not isinstance(members, list) or not members:
                raise ValueError("模型元件檔案清單為空")
            for member in members:
                if not isinstance(member, str):
                    raise ValueError("模型檔案路徑格式錯誤")
                rel = "models/" + component + "/" + member
                _frame_safe_path(home, rel)
                if rel in expected:
                    raise ValueError("模型檔案紀錄重複")
                expected.add(rel)
        records = {}
        for item in files:
            if not isinstance(item, dict):
                raise ValueError("檔案紀錄格式錯誤")
            rel = item.get("path")
            resolved = _frame_safe_path(home, rel)
            size = item.get("bytes")
            checksum = item.get("sha256")
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise ValueError("檔案容量紀錄錯誤")
            if not isinstance(checksum, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
                raise ValueError("檔案 SHA-256 紀錄缺少或格式錯誤")
            if rel in records:
                raise ValueError("檔案紀錄重複")
            records[rel] = (resolved, size, checksum.lower())
        recorded_models = {rel for rel in records if rel.startswith("models/")}
        if expected != recorded_models:
            raise ValueError("模型元件清單與檔案驗證紀錄不一致")
        result.update(valid=True, runtime_mode=mode == "runtime",
                      model_files=len(expected),
                      recorded_model_bytes=sum(records[rel][1] for rel in expected))
        bad_models, bad_artifacts = 0, 0
        for rel, (resolved, size, checksum) in records.items():
            error = None
            try:
                if not resolved.is_file():
                    error = "缺少檔案：" + rel
                elif resolved.stat().st_size != size:
                    error = "容量不符：" + rel
                elif verify and _frame_sha256(resolved, hash_cache) != checksum:
                    error = "SHA-256 不符：" + rel
            except (OSError, RuntimeError) as exc:
                error = "無法讀取：" + rel + " (" + str(exc) + ")"
            if error:
                result["issues"].append(error)
                if rel in expected:
                    bad_models += 1
                else:
                    bad_artifacts += 1
            elif rel in expected:
                result["checked_model_files"] += 1
                result["checked_model_bytes"] += size
        result["weights_complete"] = bad_models == 0
        result["artifacts_complete"] = bad_artifacts == 0
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        result["issues"].append(str(exc))
    return result


def audit_models(source: Path, verify=False):
    """Return JSON-serializable status of seven local experts; never run code.

    ``verify=False`` checks receipt structure and recorded file sizes. ``True``
    additionally streams SHA-256 for every recorded file in both receipts.
    Totals only cover the selected receipt's model files, excluding source,
    virtual environments, download caches, and unrecorded files.
    """
    source = Path(source).expanduser().resolve()
    configured = os.environ.get("FRAME_EXPERT_HOME")
    runtime_root = Path(configured).expanduser().resolve() if configured else source / "advanced_service" / ".runtime"
    intel_mac = platform.system() == "Darwin" and platform.machine().lower() in ("x86_64", "amd64")
    hash_cache, rows = {}, []
    for expert in _FRAME_EXPERT_IDS:
        home = runtime_root / expert
        receipts = [item for item in (
            _frame_receipt(home, expert, "install-manifest.json", verify, hash_cache),
            _frame_receipt(home, expert, "weights-manifest.json", verify, hash_cache),
        ) if item is not None]
        # Existence is all we check: a stale or fake executable is NOT readiness.
        venv_present = any(path.is_file() for path in (home / "venv" / "bin" / "python", home / "venv" / "Scripts" / "python.exe"))
        complete_runtime = [r for r in receipts if r["receipt"] == "install-manifest.json"
                            and r["valid"] and r["runtime_mode"] and r["weights_complete"]
                            and r["artifacts_complete"] and venv_present]
        complete_weights = sorted([r for r in receipts if r["valid"] and r["weights_complete"]],
                                  key=lambda r: r["receipt"] != "weights-manifest.json")
        selected = (complete_runtime or complete_weights or
                    sorted(receipts, key=lambda r: r["checked_model_files"], reverse=True) or [None])[0]
        directory_present = (home / "models").is_dir()
        weights_complete = bool(selected and selected["weights_complete"])
        status = ("runtime-present-unverified" if complete_runtime else "weights-only" if weights_complete
                  else "partial" if receipts or directory_present else "missing")
        recorded_check = None
        check_issue = None
        if (home / "runtime-check.json").is_file():
            try:
                check = _frame_read_json(home / "runtime-check.json", limit=128 * 1024)
                recorded_check = {"ready_recorded": check.get("ready"), "versions_recorded": check.get("versions"),
                                  "current_inference_verified": False}
            except (OSError, ValueError, TypeError) as exc:
                check_issue = "舊執行檢查紀錄無法讀取：" + str(exc)
        issues = list(selected["issues"]) if selected else []
        if check_issue:
            issues.append(check_issue)
        if selected and not selected["valid"]:
            issues.insert(0, "紀錄驗證失敗；未宣稱模型完整")
        rows.append(dict(
            id=expert, status=status, status_zh=_FRAME_STATUS_ZH[status],
            weights_status="complete" if weights_complete else "partial" if status == "partial" else "missing",
            weights_complete=weights_complete, receipt=selected["receipt"] if selected else None,
            model_files=selected["model_files"] if selected else 0,
            checked_model_files=selected["checked_model_files"] if selected else 0,
            recorded_model_bytes=selected["recorded_model_bytes"] if selected else 0,
            checked_model_bytes=selected["checked_model_bytes"] if selected else 0,
            integrity="sha256" if verify else "file-size", venv_present=venv_present,
            runtime_receipt_complete=bool(complete_runtime), runtime_check_recorded=recorded_check,
            inference_verified=False, platform_blocked=intel_mac and expert in _FRAME_INTEL_BLOCKED,
            issues=issues, receipt_issues={r["receipt"]: r["issues"] for r in receipts if r["issues"]},
        ))
    return dict(schema=1, source=str(source), runtime_root=str(runtime_root),
                integrity="sha256" if verify else "file-size", models=rows,
                complete_weight_models=sum(row["weights_complete"] for row in rows),
                total_recorded_model_bytes=sum(row["recorded_model_bytes"] for row in rows),
                total_checked_model_bytes=sum(row["checked_model_bytes"] for row in rows),
                inference_verified=False,
                scope="僅本機收據列出的模型檔；不含環境、快取、未列入紀錄的檔案。")


def format_model_audit(report):
    """Compact Chinese console report; caller decides whether to print/save."""
    lines = ["模型目錄：" + report["runtime_root"],
             "檢查方式：" + ("逐檔 SHA-256" if report["integrity"] == "sha256" else "檔案存在及容量（未重算 SHA-256）")]
    for row in report["models"]:
        detail = f'{row["checked_model_files"]}/{row["model_files"]} 檔；紀錄 {row["recorded_model_bytes"] / 1e9:.3f} GB'
        blocked = "；目前安裝設定不支援 Intel macOS 執行" if row["platform_blocked"] else ""
        lines.append(f'{row["id"]}: {row["status_zh"]}（{detail}）{blocked}')
        for issue in row["issues"][:3]:
            lines.append("  - " + issue)
        if len(row["issues"]) > 3:
            lines.append(f'  - 另有 {len(row["issues"]) - 3} 項問題，見 JSON 完整報告。')
    lines.append(f'完整權重紀錄：{report["complete_weight_models"]}/7；合計紀錄 {report["total_recorded_model_bytes"] / 1e9:.3f} GB。')
    lines.append("此檢查不執行模型，所有模型的實際推論皆未由本次檢查驗證。")
    return "\n".join(lines)


EXCLUDED_DIRS = {'.git', '.github', '.ssh', '.venv', '.venv-native', 'venv', 'env', 'node_modules', '__pycache__',
                '.cache', 'cache', 'caches', 'huggingface', '.huggingface', '.hf', '.pytest_cache',
                'outputs', 'output', 'renders', 'uploads', 'user-projects', 'recordings', 'downloads', 'checkpoints', 'weights', 'qa-output',
                '.frame-upload', '.runtime', '.mypy_cache', '.ruff_cache', 'runtime', 'jobs', '.idea', '.vscode', '__macosx'}
WEIGHT_SUFFIXES = {'.safetensors', '.ckpt', '.pt', '.pth', '.gguf', '.ggml', '.h5', '.hdf5', '.bin'}
ARCHIVES = {'.zip', '.tar', '.tgz', '.7z', '.rar'}
SECRET_RE = re.compile(rb'(?:github_pat_[A-Za-z0-9_]{25,}|gh[pousr]_[A-Za-z0-9]{25,}|hf_[A-Za-z0-9]{25,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')

def excluded(rel, is_dir=False):
    parts = pathlib.PurePosixPath(rel).parts
    low = [p.lower() for p in parts]
    if any(p in EXCLUDED_DIRS or p.startswith(('.venv-', '.venv_', '.frame-backup', '.frame-v51-backup', '.frame-upload-')) for p in low):
        return True
    if len(low) > 1 and low[0] in {'native_cpu', 'backend'} and low[1] in {'models', 'model', 'data'}:
        return True
    name = low[-1]
    if name in {'.ds_store', '.gitattributes', '.gitmodules', '.gitconfig', '.netrc', '.npmrc', '.pypirc', 'credentials.json', 'credentials', 'token', 'token.txt'}:
        return True
    if name.startswith(('.env', 'id_rsa', 'id_ed25519', 'credential', 'secret', '._')):
        return True
    suffix = pathlib.PurePosixPath(name).suffix
    archive = suffix in ARCHIVES and not rel.startswith('story/vendor/source/')
    return archive or suffix in WEIGHT_SUFFIXES | {'.pem', '.key', '.p12', '.pfx', '.pyc', '.log'}

def path_ok(path):
    p = pathlib.PurePosixPath(path)
    return not p.is_absolute() and all(x not in {'', '.', '..', '.git'} for x in p.parts) and '\\' not in path and not any(ord(c) < 32 for c in path)

def main():
    source = source_root()
    if args.audit_models or args.verify_models:
        if args.stage_only:
            fail('--stage-only 只能搭配 --push。')
        report = audit_models(source, verify=args.verify_models)
        print(format_model_audit(report), flush=True)
        if args.report:
            out = pathlib.Path(args.report).expanduser().absolute()
            if out.exists():
                fail('報告檔已存在，請選新檔名，避免覆寫：'+str(out))
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open('x', encoding='utf-8') as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
            print('模型報告：'+str(out))
        return
    if args.report:
        fail('--report 僅供模型檢查模式使用。')
    if not shutil.which('git'):
        fail('找不到 Git。Mac 可先執行 xcode-select --install；Windows 請使用 Git Bash。')
    if not 1 <= args.batch_mib <= 256:
        fail('--batch-mib 必須介於 1 到 256。')
    if args.stage_only and not args.push:
        fail('--stage-only 必須搭配 --push。')
    remote = args.remote
    local_remote = remote != DEFAULT_REMOTE
    if local_remote:
        rp = pathlib.Path(remote).expanduser()
        if not rp.is_dir():
            fail('--remote 僅接受預設 GitHub SSH 網址或現有本機 bare Git 路徑。禁止 Token/HTTPS 網址。')
        remote = str(rp.resolve())
    identity_name = args.name or original_config('user.name')
    identity_email = args.email or original_config('user.email')
    if args.push and not (identity_name and identity_email):
        fail('請先設定 git config --global user.name 與 user.email，或傳入 --name / --email。')
    key = digest(remote.encode())[:16]
    state = pathlib.Path(args.state_dir).expanduser().resolve() if args.state_dir else pathlib.Path.home() / '.cache' / 'frame-ssh-upload' / key
    if state == source or source in state.parents:
        fail('獨立快取不可位於來源資料夾中。請改用 --state-dir 指定其他位置。')
    state.mkdir(parents=True, exist_ok=True)
    # Atomic process lock; stale locks can be removed after checking the recorded PID.
    lock = state / 'running.lock'
    try:
        lock.mkdir()
    except FileExistsError:
        fail('快取正在使用或上次被強制中止。確認沒有上傳程序後，刪除 ' + str(lock) + ' 再重試。')
    (lock / 'pid.txt').write_text(str(os.getpid()), encoding='utf-8')
    try:
        execute(source, remote, local_remote, state, identity_name, identity_email)
    finally:
        shutil.rmtree(str(lock), ignore_errors=True)

def execute(source, remote, local_remote, state, identity_name, identity_email):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_TERMINAL_PROMPT': '0',
                'GIT_AUTHOR_NAME': identity_name or 'FRAME preview', 'GIT_AUTHOR_EMAIL': identity_email or 'preview@example.invalid',
                'GIT_COMMITTER_NAME': identity_name or 'FRAME preview', 'GIT_COMMITTER_EMAIL': identity_email or 'preview@example.invalid'})
    if not local_remote:
        env['GIT_SSH_COMMAND'] = 'ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -o ConnectTimeout=30'
    repo = state / 'isolated.git'
    hooks = state / 'empty-hooks'
    hooks.mkdir(exist_ok=True)
    basecmd = ['git', '-c', 'core.hooksPath=' + str(hooks), '-c', 'commit.gpgsign=false', '-c', 'core.autocrlf=false', '-c', 'protocol.file.allow=' + ('always' if local_remote else 'never')]
    def run(cmd, data=None, check=True):
        p = subprocess.run(cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        if check and p.returncode:
            message = p.stderr.decode('utf-8', 'replace').strip()
            fail('Git 操作失敗（來源檔未改動；可重跑）：\n' + message)
        return p
    def git(*cmd, **kw):
        return run(basecmd + ['--git-dir=' + str(repo)] + list(cmd), **kw)
    if not repo.exists():
        print('建立獨立 Git 快取（讀取遠端 main）…', flush=True)
        # Bare clone: no checkout, source hooks, clean filters or LFS downloads run.
        run(basecmd + ['clone', '--bare', '--single-branch', '--branch', 'main', remote, str(repo)])
    else:
        found = git('remote', 'get-url', 'origin').stdout.decode().strip()
        if found != remote:
            fail('快取綁定的遠端不同；請指定新的 --state-dir。')
    index = state / ('index-' + str(os.getpid()))
    if index.exists():
        index.unlink()
    env['GIT_INDEX_FILE'] = str(index)
    git('fetch', '--no-tags', 'origin', 'refs/heads/main:refs/frame/main')
    base = git('rev-parse', 'refs/frame/main').stdout.decode().strip()
    def tree(commit):
        entries = {}
        for row in git('ls-tree', '-r', '-l', '-z', commit).stdout.split(b'\0'):
            if not row:
                continue
            header, path = row.split(b'\t', 1)
            mode, kind, oid, size = header.split()
            p = path.decode('utf-8')
            entries[p] = {'mode': mode.decode(), 'oid': oid.decode(), 'size': int(size) if size != b'-' else 0, 'kind': kind.decode()}
        return entries
    baseline = tree(base)
    files, skipped = {}, []
    print('掃描來源並比對實際內容雜湊：' + str(source), flush=True)
    def add_file(target, data, mode='100644'):
        if len(data) >= 100 * MiB:
            fail('檔案必須小於 100 MiB：' + target)
        # Quantized weights contain arbitrary byte strings that resemble tokens.
        # Inspect UTF-8 text only; validated binary models are checked below by SHA.
        is_text = b'\0' not in data[:8192]
        if is_text:
            try:
                data.decode('utf-8')
            except UnicodeDecodeError:
                is_text = False
        if is_text and SECRET_RE.search(data):
            fail('疑似秘密金鑰出現在待上傳檔案；已停止，未顯示內容：' + target)
        oid = git('hash-object', '-w', '--no-filters', '--stdin', data=data).stdout.decode().strip()
        files[target] = {'mode': mode, 'oid': oid, 'size': len(data), 'sha256': digest(data), 'kind': 'blob'}
    for current, dirs, names in os.walk(str(source), followlinks=False):
        current = pathlib.Path(current)
        for name in list(dirs):
            child = current / name
            rel = child.relative_to(source).as_posix()
            if excluded(rel, True):
                skipped.append(rel + '/')
                dirs.remove(name)
            elif child.is_symlink():
                fail('來源包含符號連結，請改為實體檔案：' + rel)
        dirs.sort()
        for name in sorted(names):
            p = current / name
            rel = p.relative_to(source).as_posix()
            if excluded(rel):
                skipped.append(rel)
                continue
            if not path_ok(rel):
                fail('不支援此檔名（控制字元或特殊路徑）：' + repr(rel))
            st = p.lstat()
            if not stat.S_ISREG(st.st_mode):
                fail('來源包含連結或特殊檔案：' + rel)
            if p.suffix.lower() == '.onnx' and pathlib.Path(str(p) + '.parts.json').is_file():
                skipped.append(rel + '（已有分塊，略過重複整檔）')
                continue
            if re.search(r'\.part\d+$', name) and st.st_size > 40 * MiB:
                fail('瀏覽器模型分塊超過 40 MiB：' + rel)
            if p.suffix.lower() == '.onnx' and st.st_size > 40 * MiB:
                fail('ONNX 必須先使用專案分塊工具產生 .parts.json 與 ≤40 MiB 分塊：' + rel)
            if st.st_size >= 100 * MiB:
                fail('檔案必須小於 100 MiB：' + rel)
            data = p.read_bytes()
            after = p.stat()
            if (st.st_size, st.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                fail('掃描時檔案被修改，請停止編輯後重試：' + rel)
            add_file(PREFIX + rel, data, '100755' if st.st_mode & 0o111 else '100644')
    # The repository has a separate, old root index. Replace just this entry explicitly.
    redirect = ('<!doctype html>\n<html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<meta http-equiv="refresh" content="0;url=./FRAME_AI_Studio/">'
                '<title>FRAME Story Studio</title><a href="./FRAME_AI_Studio/">開啟 FRAME Story Studio</a>'
                '<script>location.replace("./FRAME_AI_Studio/"+location.search+location.hash)</script></html>\n').encode()
    add_file('index.html', redirect)
    add_file('.nojekyll', b'')
    def blob(path):
        return git('cat-file', 'blob', files[path]['oid']).stdout
    # Validate exactly the existing loader's part000… order, each SHA, total SHA and bytes.
    for target in sorted(files):
        if not target.endswith('.parts.json'):
            continue
        manifest = json.loads(blob(target))
        pieces = manifest.get('pieces')
        if not isinstance(pieces, list) or not pieces:
            fail('模型分塊清單無效：' + target)
        full_hash, total = hashlib.sha256(), 0
        stem = pathlib.PurePosixPath(target).name[:-len('.parts.json')]
        for i, piece in enumerate(pieces):
            expected = stem + '.part' + str(i).zfill(3)
            if piece.get('name') != expected:
                fail('模型分塊必須使用 part000 起的原順序：' + target)
            path = str(pathlib.PurePosixPath(target).parent / expected)
            entry = files.get(path)
            if not entry or entry['size'] != piece.get('bytes') or entry['sha256'] != piece.get('sha256') or entry['size'] > 40 * MiB:
                fail('模型分塊缺少、大小或 SHA-256 不符：' + path)
            full_hash.update(blob(path))
            total += entry['size']
        if total != manifest.get('bytes') or full_hash.hexdigest() != manifest.get('sha256'):
            fail('模型合併後的 SHA-256 或總大小不符：' + target)
    master_path = PREFIX + 'story/models/manifest.json'
    if master_path in files:
        master = json.loads(blob(master_path))
        for asset in master.get('assets', []):
            rel = asset.get('path', '')
            if not path_ok(rel):
                fail('模型 manifest 含不安全路徑。')
            path = PREFIX + 'story/models/' + rel
            if asset.get('pieces'):
                pp = path + '.parts.json'
                if pp not in files:
                    fail('缺少模型分塊清單：' + pp)
                m = json.loads(blob(pp))
                if any(m.get(k) != asset.get(k) for k in ('pieces', 'sha256', 'bytes')):
                    fail('模型 manifest 與 .parts.json 不一致：' + pp)
            elif path not in files or any(files[path].get(k) != asset.get(a) for k, a in [('sha256', 'sha256'), ('size', 'bytes')]):
                fail('模型資產缺少或雜湊不符：' + path)
    # Resolve all required offline resources against what will really be uploaded.
    offline_path = PREFIX + 'offline-files.json'
    if offline_path in files:
        offline = json.loads(blob(offline_path))
        rows = offline.get('files')
        if not isinstance(rows, list):
            fail('offline-files.json 缺少 files 陣列。')
        for item in rows:
            rel = item.get('path', '')
            if not path_ok(rel) or rel.endswith('/'):
                fail('離線清單包含不安全路徑。')
            required = files.get(PREFIX + rel)
            if required is None or required['size'] != item.get('bytes'):
                fail('離線必要檔案缺少、被排除或大小不符：'+rel)
    service_worker = PREFIX + 'service-worker.js'
    if service_worker in files and offline_path not in files:
        fail('找到 service-worker.js，但缺少 offline-files.json，請使用完整專案。')
    # Reject implicit deletion caused by directory/file collisions.
    baseline_paths = set(baseline)
    for path in files:
        for parent in pathlib.PurePosixPath(path).parents:
            if str(parent) in baseline_paths:
                fail('檔案/資料夾衝突，為保留遠端內容而停止：' + path)
        if any(p.startswith(path + '/') for p in baseline_paths):
            fail('新檔案會遮蔽遠端資料夾，已停止：' + path)
    final_entries = dict(baseline)
    final_entries.update(files)
    remote_only = sorted((p for p in baseline if p not in files), key=lambda p:baseline[p]['size'], reverse=True)
    total_size = sum(f['size'] for f in final_entries.values())
    # Conservative decimal 1 GB guard for a branch/root Pages publication.
    if total_size >= 1_000_000_000:
        fail('保留遠端檔案後網站總量達 %.1f MB；需小於 1,000 MB。遠端獨有大檔：\n%s\n請先人工整理，腳本不會自動刪除。' % (total_size / 1e6, '\n'.join('%.1f MB  %s' % (baseline[p]['size']/1e6,p) for p in remote_only[:12])))
    def same(a, b):
        return a is not None and b is not None and a['oid'] == b['oid'] and a['mode'] == b['mode']
    changed = sorted(p for p in files if not same(files[p], baseline.get(p)))
    summary = {'uploader_version':'5.2.0', 'generated_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()), 'source': str(source), 'remote': remote, 'main_before': base, 'changed': changed,
               'added':[p for p in changed if p not in baseline], 'modified':[p for p in changed if p in baseline],
               'remote_only_preserved':remote_only, 'files':[dict(path=p, bytes=files[p]['size'], sha256=files[p]['sha256']) for p in sorted(files)],
               'unchanged_count': len(files) - len(changed), 'excluded': skipped, 'final_tree_bytes': total_size,
               'changed_bytes': sum(files[p]['size'] for p in changed), 'mode': 'push' if args.push else 'dry-run'}
    (state / 'last-plan.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('新增/修改 %d；相同略過 %d；排除 %d；保留後網站 %.1f MB。' % (len(changed), len(files)-len(changed), len(skipped), total_size / 1e6), flush=True)
    for path in changed:
        print('  %8.2f MiB  %s' % (files[path]['size'] / MiB, path))
    print('遠端獨有檔案保留 %d 個；不會因為本機缺少而刪除。' % len(remote_only), flush=True)
    print('大型本機權重與虛擬環境不納入上傳；這不影響網頁程式上傳。', flush=True)
    print('完整計畫：' + str(state / 'last-plan.json'), flush=True)
    if not changed:
        print('內容與遠端一致，不建立提交、不推送。')
        return
    if not args.push:
        print('預覽完成，遠端未修改。確認後以相同指令加上 --push 執行。')
        return
    source_digest = digest(json.dumps([(p, files[p]['oid'], files[p]['mode']) for p in sorted(files)], separators=(',', ':')).encode())
    branch = 'frame-upload/' + base[:12] + '-' + source_digest[:16]
    stage_ref = 'refs/heads/' + branch
    print('暫存分支：' + branch, flush=True)
    remote_stage = git('ls-remote', '--heads', 'origin', stage_ref).stdout.strip()
    current = base
    current_entries = baseline
    if remote_stage:
        git('fetch', '--no-tags', 'origin', stage_ref + ':refs/frame/stage')
        current = git('rev-parse', 'refs/frame/stage').stdout.decode().strip()
        if git('merge-base', '--is-ancestor', base, current, check=False).returncode:
            fail('暫存分支基底不符，拒絕覆寫。請檢查該分支。')
        current_entries = tree(current)
        if set(current_entries) - set(final_entries) or set(baseline) - set(current_entries):
            fail('暫存分支含非本次計畫的新增或刪除，拒絕續傳。')
        for path, entry in current_entries.items():
            if not same(entry, baseline.get(path)) and not same(entry, files.get(path)):
                fail('暫存分支含非本次計畫的修改：' + path)
        print('已驗證暫存分支；續傳剩餘檔案。', flush=True)
    remaining = [p for p in changed if not same(files[p], current_entries.get(p))]
    # Binary assets first, application entrypoints/manifests last. main never sees partial batches.
    remaining.sort(key=lambda p: (0 if re.search(r'\.part\d+$', p) or '/edge/model/' in p else 1, p))
    batches, batch, size = [], [], 0
    for path in remaining:
        if batch and size + files[path]['size'] > args.batch_mib * MiB:
            batches.append(batch)
            batch, size = [], 0
        batch.append(path)
        size += files[path]['size']
    if batch:
        batches.append(batch)
    git('read-tree', current)
    last_push = [0.0]
    def push(commit, ref):
        if not local_remote:
            delay = 11 - (time.monotonic() - last_push[0])
            if delay > 0:
                time.sleep(delay)
        result = git('push', 'origin', commit + ':' + ref, check=False)
        last_push[0] = time.monotonic()
        if result.returncode:
            # A lost acknowledgement is not evidence the server rejected the write.
            observed = git('ls-remote', '--heads', 'origin', ref, check=False)
            if observed.returncode == 0 and observed.stdout.split()[:1] == [commit.encode()]:
                print('連線回覆中斷，但遠端已確認收到該提交；繼續。', flush=True)
                return
            fail('推送未確認完成；main 不會被強制覆寫。可重跑續傳。\n' + result.stderr.decode('utf-8', 'replace').strip())
    for i, batch in enumerate(batches, 1):
        updates = b''.join((files[p]['mode'] + ' ' + files[p]['oid'] + '\t' + p).encode() + b'\0' for p in batch)
        git('update-index', '-z', '--index-info', data=updates)
        tree_oid = git('write-tree').stdout.decode().strip()
        message = 'FRAME staged assets (%d files)\n' % len(batch)
        current = git('commit-tree', tree_oid, '-p', current, data=message.encode()).stdout.decode().strip()
        # Retain unreachable local objects/commit between attempts; remote branch is resume authority.
        git('update-ref', 'refs/frame/prepared', current)
        print('上傳暫存批次 %d/%d（%.1f MiB）…' % (i, len(batches), sum(files[p]['size'] for p in batch)/MiB), flush=True)
        push(current, stage_ref)
    if args.stage_only:
        print('暫存完成；main 未變更。再以 --push（不加 --stage-only）執行即可發布。')
        return
    verified = tree(current)
    if set(verified) != set(final_entries) or any(not same(verified.get(p), e) for p, e in final_entries.items()):
        fail('最終樹狀內容驗證不符，已停止發布。')
    latest = git('ls-remote', '--heads', 'origin', 'refs/heads/main').stdout.split()
    if not latest or latest[0].decode() != base:
        fail('上傳期間 main 已被其他人更新。已保留暫存檔案；請重跑以新的 main 比對，不會強推。')
    print('所有資產已齊全；一次 fast-forward 更新 main…', flush=True)
    push(current, 'refs/heads/main')
    summary.update({'published_commit': current, 'staging_branch': branch})
    (state / 'last-plan.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('main 更新成功：' + current)
    print('請在 GitHub Actions 確認 Pages 成功；網址 https://kuonanhong.github.io/Frame_to_Video/')
    print('暫存分支保留供稽核；請使用 main / (root) 作為 Pages 發布來源。')
    print('GitHub Pages 不會自動存取您的本機權重。大型模型請從本機服務 http://127.0.0.1:8787/ 開啟。')

try:
    main()
except (Stop, OSError, ValueError, KeyError, TypeError) as exc:
    print('停止：' + str(exc), file=sys.stderr)
    sys.exit(2)
except KeyboardInterrupt:
    print('\n已中止。遠端已接收的暫存提交可於下次續傳。', file=sys.stderr)
    sys.exit(130)
PYTHON
