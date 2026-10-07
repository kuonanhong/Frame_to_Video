"""Contract tests use a fake runner; they do not exercise model inference."""
import io
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import BODY_LIMIT, IMAGE_LIMIT, BodyLimitMiddleware, JobCancelled, Settings, create_app


def image_bytes():
    target = io.BytesIO()
    Image.new("RGB", (32, 32), "teal").save(target, "PNG")
    return target.getvalue()


def fake_runner(spec, source, output, report, cancel):
    report(35, "Contract test runner")
    if spec.workflow != "text-image":
        assert source and source.is_file()
    output.write_bytes(b"contract-test-result")
    report(95, "Contract test output saved")


def wait_for(client, jid, target=None):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        data = client.get(f"/api/jobs/{jid}").json()
        if data["status"] in (target or {"succeeded", "failed", "cancelled"}):
            return data
        time.sleep(.01)
    raise AssertionError(f"Job did not finish: {data}")


class APIContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.directory.name), allowed_origins=("http://frontend.test",))
        self.app = create_app(fake_runner, self.settings)
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.directory.cleanup()

    def submit(self, **overrides):
        data = {"workflow": "text-image", "prompt": "A softly lit mountain", **overrides}
        return self.client.post("/api/jobs", data=data)

    def test_health_is_lazy_and_includes_limits(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["inference_state"], "lazy")
        self.assertTrue(data["worker_running"])
        self.assertEqual(data["max_image_mb"], 20)
        self.assertEqual(data["max_video_mb"], 80)
        self.assertNotIn("torch", sys.modules)
        self.assertNotIn("diffusers", sys.modules)

    def test_text_image_job_and_download(self):
        response = self.submit(seed="42")
        self.assertEqual(response.status_code, 202)
        queued = response.json()
        self.assertEqual(queued["model"], "sd-turbo")
        result = wait_for(self.client, queued["id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["progress"], 100)
        self.assertEqual(result["output_type"], "image")
        download = self.client.get(result["output_url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.headers["content-type"], "image/png")
        self.assertEqual(download.content, b"contract-test-result")

    def test_image_upload_validation_and_source_cleanup(self):
        response = self.client.post("/api/jobs", data={"workflow": "image-video", "prompt": "Clouds drift"},
                                    files={"file": ("../../escape.png", image_bytes(), "text/plain")})
        self.assertEqual(response.status_code, 202)
        result = wait_for(self.client, response.json()["id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["output_type"], "video")
        self.assertEqual(list(self.app.state.manager.upload_dir.iterdir()), [])
        download = self.client.get(result["output_url"])
        self.assertEqual(download.headers["content-type"], "video/mp4")
        self.assertFalse((Path(self.directory.name).parent / "escape.png").exists())

    def test_video_contract_and_strength(self):
        captured = []

        def runner(spec, source, output, report, cancel):
            captured.append(spec)
            fake_runner(spec, source, output, report, cancel)

        self.app.state.manager.runner = runner
        # Deliberately only a container header: the fake runner tests the API
        # contract. Actual source decoding is verified by the real inference path.
        upload = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 20
        response = self.client.post("/api/jobs", data={
            "workflow": "video-video", "model": "ltx-2b", "prompt": "Change to watercolor",
            "strength": "0.4", "duration": "2.5", "aspect": "9:16", "seed": "3",
        }, files={"file": ("input.mp4", upload, "video/mp4")})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(wait_for(self.client, response.json()["id"])["status"], "succeeded")
        self.assertEqual(captured[0].strength, .4)
        self.assertEqual(captured[0].duration, 2.5)
        self.assertEqual(captured[0].aspect, "9:16")

    def test_invalid_fields_are_rejected(self):
        cases = [
            {"workflow": "unknown"}, {"prompt": "  "}, {"prompt": "a" * 1801},
            {"model": "ltx-2b"}, {"duration": "0"}, {"duration": "6"}, {"duration": "nan"},
            {"aspect": "4:3"}, {"seed": "-1"}, {"seed": "4294967296"},
            {"strength": "1"}, {"strength": "nan"}, {"negative_prompt": "a" * 1801},
        ]
        for case in cases:
            with self.subTest(case=list(case)):
                self.assertEqual(self.submit(**case).status_code, 422)
        self.assertEqual(self.submit(workflow="image-video", model="ltx-2b").status_code, 422)
        self.assertEqual(self.submit(workflow="video-video", model="wan-5b").status_code, 422)

    def test_invalid_uploads_are_rejected_without_leaks(self):
        for workflow, filename, payload in [
            ("image-video", "x.png", b"not an image"),
            ("image-video", "x.png", b""),
            ("video-video", "x.mp4", b"not a video"),
        ]:
            with self.subTest(workflow=workflow, payload=payload):
                response = self.client.post("/api/jobs", data={"workflow": workflow, "prompt": "A scene"},
                                            files={"file": (filename, payload)})
                self.assertIn(response.status_code, {415, 422})
        response = self.client.post("/api/jobs", data={"workflow": "text-image", "prompt": "A scene"},
                                    files={"file": ("x.png", image_bytes())})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(list(self.app.state.manager.upload_dir.iterdir()), [])

    def test_image_size_and_total_body_limits(self):
        response = self.client.post("/api/jobs", data={"workflow": "image-video", "prompt": "A scene"},
                                    files={"file": ("x.png", image_bytes() + b"x" * IMAGE_LIMIT)})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(list(self.app.state.manager.upload_dir.iterdir()), [])
        response = self.client.post("/api/jobs", data={"workflow": "text-image", "prompt": "A scene"},
                                    headers={"Content-Length": str(BODY_LIMIT + 1)})
        self.assertEqual(response.status_code, 413)

    def test_unknown_ids_and_unready_output(self):
        for method, url in [("get", "/api/jobs/unknown"), ("delete", "/api/jobs/unknown"), ("get", "/api/files/unknown")]:
            self.assertEqual(getattr(self.client, method)(url).status_code, 404)
        gate = threading.Event()
        self.app.state.manager.runner = lambda spec, source, output, report, cancel: gate.wait(2)
        jid = self.submit().json()["id"]
        try:
            self.assertEqual(self.client.get(f"/api/files/{jid}").status_code, 409)
        finally:
            self.client.delete(f"/api/jobs/{jid}")
            gate.set()

    def test_cors_only_allows_explicit_origin(self):
        accepted = self.client.options("/api/jobs", headers={
            "Origin": "http://frontend.test", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        })
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.headers["access-control-allow-origin"], "http://frontend.test")
        denied = self.client.get("/api/health", headers={"Origin": "https://unlisted.test"})
        self.assertNotIn("access-control-allow-origin", denied.headers)

    def test_worker_failure_is_reported_and_source_deleted(self):
        def fail(spec, source, output, report, cancel):
            output.write_bytes(b"partial")
            raise RuntimeError("A controlled inference failure")

        self.app.state.manager.runner = fail
        with self.assertLogs("frame", level="ERROR"):
            jid = self.submit().json()["id"]
            result = wait_for(self.client, jid)
        self.assertEqual(result["status"], "failed")
        self.assertIn("controlled inference failure", result["error"])
        self.assertFalse(self.app.state.manager.jobs[jid].output.exists())

    def test_retention_cleans_results_and_job_record(self):
        jid = self.submit().json()["id"]
        wait_for(self.client, jid)
        job = self.app.state.manager.jobs[jid]
        job.finished_at = time.time() - 25 * 3600
        self.assertEqual(self.client.get(f"/api/jobs/{jid}").status_code, 404)
        self.assertFalse(job.output.exists())


class ProtectedAndQueueTests(unittest.TestCase):
    def test_streamed_body_without_content_length_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(fake_runner, Settings(data_dir=Path(directory)))
            for middleware in app.user_middleware:
                if middleware.cls is BodyLimitMiddleware:
                    middleware.kwargs["limit"] = 128
            with TestClient(app) as client:
                chunks = iter([b"workflow=text-image&prompt=" + b"a" * 64, b"a" * 64])
                response = client.post("/api/jobs", content=chunks,
                                       headers={"Content-Type": "application/x-www-form-urlencoded"})
                self.assertEqual(response.status_code, 413)
                self.assertIn("upload limit", response.json()["detail"])
                self.assertEqual(app.state.manager.jobs, {})

    def test_token_protects_jobs_and_downloads_but_not_health(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory), api_key="test-only-key")
            app = create_app(fake_runner, settings)
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/health").status_code, 200)
                self.assertEqual(client.post("/api/jobs", data={"workflow": "text-image", "prompt": "Scene"}).status_code, 401)
                self.assertEqual(client.get("/api/jobs/unknown").status_code, 401)
                self.assertEqual(client.delete("/api/jobs/unknown").status_code, 401)
                self.assertEqual(client.get("/api/files/unknown").status_code, 401)
                client.headers["Authorization"] = "Bearer wrong-key"
                self.assertEqual(client.get("/api/jobs/unknown").status_code, 401)
                client.headers["Authorization"] = "Bearer test-only-key"
                response = client.post("/api/jobs", data={"workflow": "text-image", "prompt": "Scene"})
                self.assertEqual(response.status_code, 202)
                result = wait_for(client, response.json()["id"])
                self.assertEqual(client.get(result["output_url"]).status_code, 200)

    def test_one_worker_queued_and_running_cancellation(self):
        started, release = threading.Event(), threading.Event()
        executed = []

        def blocked(spec, source, output, report, cancel):
            executed.append(spec.id)
            started.set()
            while not release.wait(.01):
                if cancel.is_set():
                    raise JobCancelled()
            fake_runner(spec, source, output, report, cancel)

        with tempfile.TemporaryDirectory() as directory:
            app = create_app(blocked, Settings(data_dir=Path(directory)))
            with TestClient(app) as client:
                first = client.post("/api/jobs", data={"workflow": "text-image", "prompt": "First"}).json()["id"]
                self.assertTrue(started.wait(1))
                second = client.post("/api/jobs", data={"workflow": "text-image", "prompt": "Second"}).json()["id"]
                self.assertEqual(client.get(f"/api/jobs/{second}").json()["status"], "queued")
                self.assertEqual(client.delete(f"/api/jobs/{second}").json()["status"], "cancelled")
                cancelled = client.delete(f"/api/jobs/{first}").json()
                self.assertTrue(cancelled["cancel_requested"])
                self.assertEqual(wait_for(client, first)["status"], "cancelled")
                release.set()
                self.assertEqual(executed, [first])

    def test_capacity_rejection_does_not_leak_uploaded_file(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(fake_runner, Settings(data_dir=Path(directory), max_jobs=1))
            with TestClient(app) as client:
                first = client.post("/api/jobs", data={"workflow": "text-image", "prompt": "Scene"}).json()["id"]
                wait_for(client, first)
                rejected = client.post("/api/jobs", data={"workflow": "image-video", "prompt": "Scene"},
                                       files={"file": ("x.png", image_bytes())})
                self.assertEqual(rejected.status_code, 429)
                self.assertEqual(list(app.state.manager.upload_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
