#!/usr/bin/env python3
"""Local-only integration tests for the single-file SSH deployment uploader.

Every remote is a disposable bare repository. Nothing in this suite contacts
GitHub, invokes SSH, or modifies an existing checkout.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parent.parent / "Upload_FRAME_SSH.sh"
REAL_GIT = shutil.which("git") or "git"
PREFIX = "FRAME_AI_Studio/"


class UploadIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="frame-upload-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.seed = self.root / "seed"
        self.source = self.root / "source"
        self.state = self.root / "state"
        self.home = self.root / "home"
        self.home.mkdir()
        self.source.mkdir()
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("GIT_")}
        self.env.update({
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "Integration Tester",
            "GIT_AUTHOR_EMAIL": "tester@example.invalid",
            "GIT_COMMITTER_NAME": "Integration Tester",
            "GIT_COMMITTER_EMAIL": "tester@example.invalid",
        })
        self.git("init", "--bare", "--initial-branch=main", self.remote)
        self.git("init", "--initial-branch=main", self.seed)
        self.write(self.seed, "index.html", b"<!doctype html><title>Old root</title>\n")
        self.write(self.seed, PREFIX + "index.html", b"<!doctype html><title>Old</title>\n")
        self.write(self.seed, "README.md", b"Unrelated repository documentation\n")
        self.write(self.seed, PREFIX + "existing/keep.txt", b"Preserve this unrelated file\n")
        self.git("-C", self.seed, "add", "--all")
        self.git("-C", self.seed, "commit", "-m", "Fixture baseline")
        self.git("-C", self.seed, "push", str(self.remote), "HEAD:refs/heads/main")
        self.baseline = self.main_oid()
        self.write(self.source, "index.html", b"<!doctype html><title>New</title>\n")

    def git(self, *args, input=None, check=True, env=None):
        result = subprocess.run(
            [REAL_GIT, *map(str, args)], input=input, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env or self.env,
        )
        if check and result.returncode:
            self.fail(f"Fixture Git command failed: {args!r}\n"
                      f"{result.stdout.decode(errors='replace')}\n"
                      f"{result.stderr.decode(errors='replace')}")
        return result

    def upload(self, *flags, check=True, env=None):
        self.assertTrue(SCRIPT.is_file(), f"Uploader is missing: {SCRIPT}")
        result = subprocess.run(
            ["bash", str(SCRIPT), "--source", str(self.source),
             "--remote", str(self.remote), "--state-dir", str(self.state),
             "--name", "Integration Tester", "--email", "tester@example.invalid",
             *map(str, flags)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env or self.env, timeout=90,
        )
        if check and result.returncode:
            self.fail(f"Uploader failed ({result.returncode}): {flags!r}\n"
                      f"{result.stdout.decode(errors='replace')}\n"
                      f"{result.stderr.decode(errors='replace')}")
        return result

    @staticmethod
    def write(root, relative, data):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def main_oid(self):
        return self.git("--git-dir", self.remote, "rev-parse", "refs/heads/main").stdout.strip()

    def refs(self):
        return self.git("--git-dir", self.remote, "for-each-ref",
                        "--format=%(refname) %(objectname)").stdout

    def tree(self, ref="refs/heads/main"):
        raw = self.git("--git-dir", self.remote, "ls-tree", "-rz", ref).stdout
        entries = {}
        for record in raw.split(b"\0"):
            if not record:
                continue
            metadata, name = record.split(b"\t", 1)
            mode, kind, oid = metadata.split(b" ", 2)
            entries[os.fsdecode(name)] = (mode, kind, oid)
        return entries

    def blob(self, relative, ref="refs/heads/main"):
        return self.git("--git-dir", self.remote, "show", f"{ref}:{relative}").stdout

    def make_git_shim(self, *, fail_after="", race_oid="", fail_before_stage_number=0):
        """Instrument the real local Git binary; optionally lose one push ACK."""
        bindir = self.root / "bin"
        bindir.mkdir(exist_ok=True)
        marker = self.root / "injected-once"
        log = self.root / "git-calls.jsonl"
        code = f'''#!{sys.executable}
import json, os, pathlib, subprocess, sys
real = {REAL_GIT!r}
args = sys.argv[1:]
with open({str(log)!r}, "a", encoding="utf-8") as stream:
    stream.write(json.dumps(args) + "\\n")
is_push = "push" in args
is_main = any(arg == "main" or arg.endswith(":refs/heads/main")
              or arg.endswith(":main") for arg in args)
marker = pathlib.Path({str(marker)!r})
counter = pathlib.Path({str(self.root / "stage-push-count")!r})
if is_push and not is_main and {fail_before_stage_number!r}:
    count = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(count))
    if count == {fail_before_stage_number!r} and not marker.exists():
        marker.touch()
        print("SIMULATED: connection failed before staging push", file=sys.stderr)
        sys.exit(96)
if is_push and is_main and {bool(race_oid)!r} and not marker.exists():
    subprocess.run([real, "--git-dir", {str(self.remote)!r}, "update-ref",
                    "refs/heads/main", {race_oid!r}], check=True)
    marker.touch()
result = subprocess.run([real, *args])
should_fail = ({fail_after!r} == "main" and is_main or
               {fail_after!r} == "stage" and not is_main)
if is_push and result.returncode == 0 and should_fail and not marker.exists():
    marker.touch()
    print("SIMULATED: remote accepted push, transport acknowledgement lost", file=sys.stderr)
    sys.exit(97)
sys.exit(result.returncode)
'''
        shim = bindir / "git"
        shim.write_text(code, encoding="utf-8")
        shim.chmod(0o755)
        env = dict(self.env, PATH=str(bindir) + os.pathsep + self.env.get("PATH", ""))
        return env, marker, log

    def assert_source_present(self):
        self.assertEqual(self.blob(PREFIX + "index.html"), (self.source / "index.html").read_bytes())

    def test_preserves_unrelated_files_and_changes_only_source_paths(self):
        before = self.tree()
        self.write(self.source, "assets/new.dat", bytes(range(256)))
        self.upload("--push")
        after = self.tree()
        self.assert_source_present()
        self.assertEqual(after["README.md"], before["README.md"])
        self.assertEqual(after[PREFIX + "existing/keep.txt"], before[PREFIX + "existing/keep.txt"])
        self.assertEqual(self.blob(PREFIX + "assets/new.dat"), bytes(range(256)))
        changed = {path for path in before.keys() | after.keys()
                   if before.get(path) != after.get(path)}
        self.assertEqual(changed, {"index.html", ".nojekyll", PREFIX + "index.html", PREFIX + "assets/new.dat"})
        self.assertEqual(self.git("--git-dir", self.remote, "merge-base", "--is-ancestor",
                                 self.baseline.decode(), "main", check=False).returncode, 0)

    def test_same_size_and_mtime_content_change_is_uploaded(self):
        self.upload("--push")
        path = self.source / "index.html"
        old_stat = path.stat()
        path.write_bytes(path.read_bytes().replace(b"New", b"Two"))
        os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        previous = self.main_oid()
        self.upload("--push")
        self.assertNotEqual(self.main_oid(), previous)
        self.assert_source_present()

    def test_same_bytes_mode_change_is_uploaded(self):
        self.upload("--push")
        previous_blob = self.tree()[PREFIX + "index.html"][2]
        (self.source / "index.html").chmod(0o755)
        self.upload("--push")
        self.assertEqual(self.tree()[PREFIX + "index.html"][0], b"100755")
        self.assertEqual(self.tree()[PREFIX + "index.html"][2], previous_blob)

    def test_retry_is_idempotent(self):
        self.upload("--push")
        published = self.main_oid()
        self.upload("--push")
        self.assertEqual(self.main_oid(), published)

    def test_dry_run_does_not_push_or_change_source(self):
        before_refs = self.refs()
        path = self.source / "index.html"
        before = (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode)
        env, _, log = self.make_git_shim()
        self.upload("--dry-run", env=env)
        self.assertEqual(self.refs(), before_refs)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode), before)
        if log.exists():
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertFalse(any("push" in args for args in calls), calls)

    def test_stage_only_then_resume_publish(self):
        self.write(self.source, "assets/payload.dat", b"payload" * 1000)
        self.upload("--push", "--stage-only", "--batch-mib", "1")
        self.assertEqual(self.main_oid(), self.baseline)
        staged_refs = self.refs()
        self.assertGreater(len(staged_refs.splitlines()), 1)
        self.upload("--push", "--stage-only", "--batch-mib", "1")
        self.assertEqual(self.refs(), staged_refs)
        self.upload("--push", "--batch-mib", "1")
        self.assert_source_present()
        self.assertEqual(self.blob(PREFIX + "assets/payload.dat"), b"payload" * 1000)

    def test_resume_after_staging_push_acknowledgement_is_lost(self):
        env, marker, _ = self.make_git_shim(fail_after="stage")
        self.upload("--push", "--stage-only", check=False, env=env)
        self.assertTrue(marker.exists(), "Did not intercept an accepted staging push")
        self.assertEqual(self.main_oid(), self.baseline)
        self.upload("--push")
        self.assert_source_present()

    def test_partial_multibatch_interruption_resumes_without_duplicate_commits(self):
        for number in range(3):
            self.write(self.source, f"assets/payload-{number}.dat", bytes([number]) * (700 * 1024))
        env, marker, log = self.make_git_shim(fail_before_stage_number=2)
        result = self.upload("--push", "--batch-mib", "1", check=False, env=env)
        self.assertTrue(marker.exists(), "Did not interrupt the second staging batch")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.main_oid(), self.baseline)
        stages = self.git("--git-dir", self.remote, "for-each-ref", "--format=%(objectname)",
                          "refs/heads/frame-upload/").stdout.decode().splitlines()
        self.assertEqual(len(stages), 1)
        first_stage = stages[0]
        staged_tree = self.tree(first_stage)
        self.assertIn(PREFIX + "assets/payload-0.dat", staged_tree)
        self.assertNotIn(PREFIX + "assets/payload-1.dat", staged_tree)
        self.upload("--push", "--batch-mib", "1")
        self.assert_source_present()
        for number in range(3):
            self.assertEqual(self.blob(PREFIX + f"assets/payload-{number}.dat"),
                             bytes([number]) * (700 * 1024))
        self.assertEqual(self.git("--git-dir", self.remote, "merge-base", "--is-ancestor",
                                 first_stage, "main", check=False).returncode, 0)
        count = self.git("--git-dir", self.remote, "rev-list", "--count",
                         self.baseline.decode() + "..main").stdout.strip()
        self.assertEqual(count, b"3", "Resume duplicated or rebuilt already staged batches")
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        for args in calls:
            if "push" in args:
                self.assertFalse(any(arg == "-f" or arg.startswith("--force")
                                     or arg.startswith("+") for arg in args), args)

    def test_retry_after_main_push_acknowledgement_is_lost(self):
        env, marker, _ = self.make_git_shim(fail_after="main")
        self.upload("--push", check=False, env=env)
        self.assertTrue(marker.exists(), "Did not intercept an accepted main push")
        self.assert_source_present()
        accepted = self.main_oid()
        self.upload("--push")
        self.assertEqual(self.main_oid(), accepted)

    def test_environment_secret_and_git_metadata_are_excluded(self):
        self.write(self.source, ".env", b"GITHUB_TOKEN=TEST_FIXTURE_ONLY\n")
        self.write(self.source, ".env.local", b"PASSWORD=TEST_FIXTURE_ONLY\n")
        self.write(self.source, ".git/config", b"[remote \"private\"]\n")
        self.write(self.source, "advanced_service/.runtime/jobs/example.txt", b"Private generated output\n")
        self.write(self.source, "native_cpu/.venv-native/bin/python", b"Runtime executable\n")
        self.write(self.source, "story/vendor/source/corresponding-source.zip", b"Redistributed source archive fixture\n")
        self.upload("--push")
        paths = self.tree()
        self.assertNotIn(PREFIX + ".env", paths)
        self.assertNotIn(PREFIX + ".env.local", paths)
        self.assertFalse(any(path.startswith(PREFIX + ".git/") for path in paths))
        self.assertFalse(any('/.runtime/' in path or '/.venv-native/' in path for path in paths))
        self.assertIn(PREFIX + "story/vendor/source/corresponding-source.zip", paths)

    def test_corrupt_parts_manifest_aborts_before_remote_mutation(self):
        self.write(self.source, "story/models/broken.parts.json", b"{invalid JSON")
        before = self.refs()
        result = self.upload("--push", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.refs(), before)

    def multipart_fixture(self):
        parts = [b"first model portion\x00\x01", b"second model portion\xfe\xff"]
        pieces = []
        for number, content in enumerate(parts):
            name = f"fixture.onnx.part{number:03d}"
            self.write(self.source, "story/models/" + name, content)
            pieces.append({"name": name, "bytes": len(content),
                           "sha256": hashlib.sha256(content).hexdigest()})
        whole = b"".join(parts)
        manifest = {"bytes": len(whole), "sha256": hashlib.sha256(whole).hexdigest(),
                    "pieces": pieces}
        self.write(self.source, "story/models/fixture.onnx.parts.json",
                   json.dumps(manifest).encode())
        return manifest

    def test_valid_model_parts_publish_and_duplicate_whole_model_is_skipped(self):
        self.multipart_fixture()
        self.write(self.source, "story/models/fixture.onnx", b"not used: verified pieces are authoritative")
        self.upload("--push")
        tree = self.tree()
        self.assertIn(PREFIX + "story/models/fixture.onnx.part000", tree)
        self.assertIn(PREFIX + "story/models/fixture.onnx.part001", tree)
        self.assertIn(PREFIX + "story/models/fixture.onnx.parts.json", tree)
        self.assertNotIn(PREFIX + "story/models/fixture.onnx", tree)

    def test_missing_or_hash_mismatched_model_part_blocks_upload(self):
        self.multipart_fixture()
        part = self.source / "story/models/fixture.onnx.part001"
        part.write_bytes(b"different content")
        before = self.refs()
        mismatch = self.upload("--push", check=False)
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertEqual(self.refs(), before)
        part.unlink()
        missing = self.upload("--push", check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(self.refs(), before)

    def test_model_chunk_larger_than_40_mib_blocks_upload(self):
        path = self.source / "story" / "models" / "oversized.onnx.part000"
        path.parent.mkdir(parents=True)
        with path.open("wb") as stream:
            stream.truncate(40 * 1024 * 1024 + 1)
        before = self.refs()
        result = self.upload("--push", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.refs(), before)

    def test_embedded_token_blocks_upload_without_echoing_secret(self):
        token = b"ghp_" + b"A" * 30
        self.write(self.source, "index.html", b"<html>" + token + b"</html>")
        before = self.refs()
        result = self.upload("--push", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(token, result.stdout + result.stderr)
        self.assertEqual(self.refs(), before)

    def test_contaminated_staging_branch_is_rejected(self):
        self.upload("--push", "--stage-only")
        refs = self.git("--git-dir", self.remote, "for-each-ref", "--format=%(refname)",
                        "refs/heads/frame-upload/").stdout.decode().splitlines()
        self.assertEqual(len(refs), 1)
        staging = refs[0]
        self.git("-C", self.seed, "fetch", str(self.remote), staging)
        self.git("-C", self.seed, "checkout", "--detach", "FETCH_HEAD")
        self.write(self.seed, "README.md", b"An unrelated, unapproved staged edit\n")
        self.git("-C", self.seed, "add", "README.md")
        self.git("-C", self.seed, "commit", "-m", "Contaminate fixture staging branch")
        self.git("-C", self.seed, "push", str(self.remote), "HEAD:" + staging)
        before = self.refs()
        result = self.upload("--push", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.main_oid(), self.baseline)
        self.assertEqual(self.refs(), before)

    def test_file_directory_collision_does_not_delete_unrelated_files(self):
        self.write(self.source, "existing", b"Cannot replace an unrelated directory\n")
        before = self.refs()
        result = self.upload("--push", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.main_oid(), self.baseline)
        self.assertEqual(self.blob(PREFIX + "existing/keep.txt"), b"Preserve this unrelated file\n")

    def test_raw_bytes_ignore_attributes_and_untrusted_global_filter(self):
        self.write(self.seed, ".gitattributes", b"*.html text eol=lf filter=tripwire\n")
        self.git("-C", self.seed, "add", ".gitattributes")
        self.git("-C", self.seed, "commit", "-m", "Fixture attributes")
        self.git("-C", self.seed, "push", str(self.remote), "HEAD:refs/heads/main")
        marker = self.root / "FILTER_RAN"
        filter_program = self.root / "filter.py"
        filter_program.write_text(
            "import pathlib,sys\n"
            f"pathlib.Path({str(marker)!r}).write_text('unexpected filter execution')\n"
            "sys.stdout.buffer.write(sys.stdin.buffer.read().replace(b'New', b'Bad'))\n"
        )
        config = self.home / ".gitconfig"
        self.git("config", "--file", config, "filter.tripwire.clean", f"{sys.executable} {filter_program}")
        self.git("config", "--file", config, "filter.tripwire.required", "true")
        self.git("config", "--file", config, "core.autocrlf", "true")
        self.write(self.source, "index.html", b"<!doctype html>\r\n<title>New</title>\r\n")
        hostile_env = dict(self.env, GIT_CONFIG_GLOBAL=str(config))
        self.upload("--push", env=hostile_env)
        self.assert_source_present()
        self.assertFalse(marker.exists(), "A configured Git filter executed")

    def test_concurrent_main_change_fails_then_rerun_preserves_new_work(self):
        self.write(self.seed, "concurrent.txt", b"Concurrent writer's unrelated work\n")
        self.git("-C", self.seed, "add", "concurrent.txt")
        self.git("-C", self.seed, "commit", "-m", "Concurrent fixture commit")
        advance = self.git("-C", self.seed, "rev-parse", "HEAD").stdout.strip().decode()
        self.git("-C", self.seed, "push", str(self.remote), "HEAD:refs/test-fixtures/advance")
        env, marker, _ = self.make_git_shim(race_oid=advance)
        result = self.upload("--push", check=False, env=env)
        self.assertTrue(marker.exists(), "Did not inject the final-push race")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.main_oid(), advance.encode())
        self.assertEqual(self.blob("concurrent.txt"), b"Concurrent writer's unrelated work\n")
        self.upload("--push")
        self.assert_source_present()
        self.assertEqual(self.blob("concurrent.txt"), b"Concurrent writer's unrelated work\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
