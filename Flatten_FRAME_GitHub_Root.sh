#!/bin/bash
# FRAME v5.3: relocate tracked GitHub files without touching local model folders.
set -eu
if [ -n "${FRAME_PYTHON:-}" ]; then
  PYTHON_BIN="$FRAME_PYTHON"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN=python3.11
else
  PYTHON_BIN=python3
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo '需要 Python 3.10+ 與 Git；您的 python3.11 可用。' >&2
  exit 2
fi
exec "$PYTHON_BIN" - "$@" <<'PYTHON'
import argparse, hashlib, json, os, pathlib, shutil, subprocess, sys, time
if sys.version_info < (3, 10):
    raise SystemExit('需要 Python 3.10 以上。')
DEFAULT_REMOTE='git@github.com:kuonanhong/Frame_to_Video.git'
PREFIX='FRAME_AI_Studio/'
class Stop(Exception): pass
def fail(text): raise Stop(text)
p=argparse.ArgumentParser(description='將 GitHub main 的 FRAME_AI_Studio/ 全部已追蹤檔案搬到根目錄。預設只預覽；--push 才發布。')
m=p.add_mutually_exclusive_group()
m.add_argument('--dry-run',action='store_true',help='只讀取並預覽（預設）')
m.add_argument('--push',action='store_true',help='先建立遠端備份分支，再正常更新 main')
p.add_argument('--state-dir',help='獨立快取位置；不須在本機專案裡執行')
p.add_argument('--name',help='Git 提交姓名；預設用 git config user.name')
p.add_argument('--email',help='Git 提交信箱；預設用 git config user.email')
p.add_argument('--prefer-inner',action='store_true',help='若有其他同名普通檔案，採用內層版本；先檢查 dry-run 清單')
p.add_argument('--remote',default=DEFAULT_REMOTE,help='預設固定 GitHub SSH；只另接受現有本機 bare repo 路徑作測試')
a=p.parse_args()
def configured(key):
    q=subprocess.run(['git','config','--get',key],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    return q.stdout.decode('utf-8','replace').strip() if q.returncode==0 else ''
def main():
    if not shutil.which('git'): fail('找不到 Git。Mac 可使用 xcode-select --install。')
    remote=a.remote
    local=remote!=DEFAULT_REMOTE
    if local:
        r=pathlib.Path(remote).expanduser()
        if not r.is_dir(): fail('--remote 僅接受固定 GitHub SSH 位址或本機 bare repository；不接受 PAT/HTTPS。')
        remote=str(r.resolve())
    name=a.name or configured('user.name')
    email=a.email or configured('user.email')
    if a.push and not(name and email): fail('請加 --name "Git 姓名" --email "GitHub 已驗證信箱"，或先設定 Git 作者。')
    key=hashlib.sha256(remote.encode()).hexdigest()[:16]
    state=pathlib.Path(a.state_dir).expanduser().resolve() if a.state_dir else pathlib.Path.home()/'.cache'/'frame-root-migration'/key
    state.mkdir(parents=True,exist_ok=True)
    lock=state/'running.lock'
    try: lock.mkdir()
    except FileExistsError: fail('已有程序或上次強制中止的鎖。先確認 pid.txt 對應程序已結束，再移除此鎖目錄：'+str(lock))
    (lock/'pid.txt').write_text(str(os.getpid()))
    try: execute(remote,local,state,name,email)
    finally: shutil.rmtree(lock,ignore_errors=True)
def execute(remote,local,state,name,email):
    env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_TERMINAL_PROMPT='0',
               GIT_AUTHOR_NAME=name or 'FRAME preview',GIT_AUTHOR_EMAIL=email or 'preview@example.invalid',
               GIT_COMMITTER_NAME=name or 'FRAME preview',GIT_COMMITTER_EMAIL=email or 'preview@example.invalid')
    if not local: env['GIT_SSH_COMMAND']='ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -o ConnectTimeout=30'
    repo=state/'isolated.git'; hooks=state/'empty-hooks'; hooks.mkdir(exist_ok=True)
    basecmd=['git','-c','core.hooksPath='+str(hooks),'-c','commit.gpgsign=false','-c','core.autocrlf=false','-c','protocol.file.allow='+('always' if local else 'never')]
    def run(cmd,data=None,check=True):
        q=subprocess.run(cmd,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
        if check and q.returncode: fail('Git 操作失敗：\n'+q.stderr.decode('utf-8','replace').strip())
        return q
    def git(*cmd,**kw): return run(basecmd+['--git-dir='+str(repo)]+list(cmd),**kw)
    if not repo.exists():
        print('讀取 GitHub main 至獨立快取；首次需下載現有儲存庫，請稍候…',flush=True)
        run(basecmd+['clone','--bare','--single-branch','--branch','main',remote,str(repo)])
    elif git('remote','get-url','origin').stdout.decode().strip()!=remote: fail('快取遠端不同，請另選 --state-dir。')
    env['GIT_INDEX_FILE']=str(state/('index-'+str(os.getpid())))
    git('fetch','--no-tags','origin','refs/heads/main:refs/frame/main')
    before=git('rev-parse','refs/frame/main').stdout.decode().strip()
    def tree(commit):
        result={}
        for row in git('ls-tree','-r','-z',commit).stdout.split(b'\0'):
            if not row: continue
            header,path=row.split(b'\t',1); mode,kind,oid=header.split()
            result[path.decode('utf-8')]=(mode.decode(),kind.decode(),oid.decode())
        return result
    original=tree(before)
    inner={path:entry for path,entry in original.items() if path.startswith(PREFIX)}
    if not inner:
        if 'index.html' in original and any(x.startswith('story/') for x in original):
            print('已是根目錄版：沒有 FRAME_AI_Studio/；不再提交或推送。',flush=True); return
        fail('遠端沒有 FRAME_AI_Studio/，也未找到完整根目錄工作台；未作任何更動。')
    if PREFIX+'index.html' not in inner or not any(x.startswith(PREFIX+'story/') for x in inner):
        fail('內層需有 index.html 與 story/。此程式針對最新版 FRAME Story Studio。')
    final={path:entry for path,entry in original.items() if not path.startswith(PREFIX)}
    same=[]; overwritten=[]; conflicts=[]; moves=[]
    for path,entry in sorted(inner.items()):
        dest=path[len(PREFIX):]
        pp=pathlib.PurePosixPath(dest)
        if not dest or pp.is_absolute() or any(x in ('.','..','.git') for x in pp.parts) or '\\' in dest or any(ord(c)<32 for c in dest):
            fail('不支援的檔案路徑：'+repr(path))
        if entry[0] not in ('100644','100755') or entry[1]!='blob': fail('遇到符號連結或子模組，請先人工檢查：'+path)
        if dest.startswith(PREFIX) or dest=='FRAME_AI_Studio': fail('發現多包一層的 FRAME_AI_Studio，請先整理。')
        if dest in final:
            if final[dest]==entry: same.append(dest)
            elif dest in ('index.html','README.md','.nojekyll') or a.prefer_inner: overwritten.append(dest)
            else: conflicts.append(dest)
        final[dest]=entry
        moves.append({'from':path,'to':dest,'git_blob':entry[2],'mode':entry[0]})
    # Stop before writes on any file/directory collision.
    for path in sorted(final):
        for parent in pathlib.PurePosixPath(path).parents:
            if str(parent) in final: fail('檔案/資料夾衝突，未發布：'+str(parent)+' ↔ '+path)
    summary=dict(version='5.3.0',operation='flatten-github-root',remote=remote,main_before=before,
                 moved_count=len(moves),moves=moves,same_name_identical=same,inner_replaces_root=overwritten,
                 other_conflicts=conflicts,root_only_preserved=sorted(set(original)-set(inner)-{x['to'] for x in moves}),
                 mode='push' if a.push else 'dry-run')
    report=state/'last-flatten-plan.json'
    report.write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print('目前 main：'+before,flush=True)
    print('搬移 %d 個已追蹤檔案；包含隱藏檔，Git blob 與檔案權限保持不變。'%len(moves),flush=True)
    print('採用內層版本的同名檔：'+(', '.join(overwritten) or '無'),flush=True)
    print('同名且完全相同：'+(', '.join(same) or '無'),flush=True)
    print('保留根目錄獨有檔案：%d 個。'%len(summary['root_only_preserved']),flush=True)
    print('完整搬移清單：'+str(report),flush=True)
    if conflicts:
        fail('另有同名不同內容檔案，未發布：\n'+'\n'.join(conflicts)+'\n確認以內層為準後，才加 --prefer-inner 重跑。')
    if not a.push:
        print('預覽完成，GitHub 未變更。執行同一腳本加 --push 才發布。',flush=True); return
    # Build the exact intended tree in the isolated index. Never run mv/rm in user's source.
    git('read-tree','--empty')
    records=b''.join((entry[0]+' '+entry[2]+'\t'+path).encode()+b'\0' for path,entry in sorted(final.items()))
    git('update-index','-z','--index-info',data=records)
    tid=git('write-tree').stdout.decode().strip()
    commit=git('commit-tree',tid,'-p',before,data=b'FRAME: move complete studio from subdirectory to repository root\n').stdout.decode().strip()
    git('update-ref','refs/frame/prepared',commit)
    verified=tree(commit)
    if verified!=final or any(x.startswith(PREFIX) for x in verified): fail('最終內容驗證失敗，未發布。')
    for item in moves:
        if verified[item['to']]!=original[item['from']]: fail('檔案完整度驗證失敗：'+item['to'])
    def observed(ref):
        q=git('ls-remote','--heads','origin',ref)
        return q.stdout.split()[0].decode() if q.stdout.strip() else None
    def push(oid,ref):
        q=git('push','origin',oid+':'+ref,check=False)
        if q.returncode and observed(ref)!=oid:
            fail('推送未完成；未強制覆寫，可重新執行。\n'+q.stderr.decode('utf-8','replace'))
    if observed('refs/heads/main')!=before: fail('main 已有新提交，請重新預覽後再執行；未覆寫。')
    backup='frame-backup/before-root-'+before[:12]
    ref='refs/heads/'+backup
    existing=observed(ref)
    if existing and existing!=before: fail('備份分支已存在但指向不同提交，未覆寫：'+backup)
    if not existing:
        print('先保存完整原狀至備份分支：'+backup,flush=True)
        push(before,ref)
    if observed('refs/heads/main')!=before: fail('備份後 main 已變動；保留備份並停止，請重跑。')
    print('一次正常 fast-forward 更新 main；既有資產不重新編碼或拆分…',flush=True)
    push(commit,'refs/heads/main')
    summary.update(published_commit=commit,backup_branch=backup)
    report.write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print('完成！main 根目錄已放入完整網站，FRAME_AI_Studio/ 不再存在。',flush=True)
    print('Git 不追蹤空資料夾，因此沒有空目錄需要另外刪除。',flush=True)
    print('原本本機的專案、模型權重與資料夾未變動。備份分支：'+backup,flush=True)
    print('Pages 請用 main / (root)，等待 Actions 部署成功：https://kuonanhong.github.io/Frame_to_Video/',flush=True)
    print('後續上傳改用 Upload_FRAME_Root_v5_3.sh；勿再使用 v5.2 子目錄上傳器。',flush=True)
try: main()
except (Stop,OSError,ValueError,KeyError,TypeError) as e:
    print('停止：'+str(e),file=sys.stderr); sys.exit(2)
except KeyboardInterrupt:
    print('\n已中止。可重跑；若 main 已完成搬移，重跑會顯示已完成。',file=sys.stderr); sys.exit(130)
PYTHON
