from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from pdf_remediation.ai import AIUnavailable, check_policy, suggest_alt
from pdf_remediation.pipeline import Options, remediate_file


class _FakeModel(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible /chat/completions endpoint."""
    requests: list = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FakeModel.requests.append(body)
        reply = {"choices": [{"message": {"content":
                 '{"decorative": false, "alt": "Image of a blue bar chart showing budget growth"}'}}]}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_model(settings):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    settings.ai_enabled = True
    settings.ai_base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    _FakeModel.requests = []
    yield settings
    server.shutdown()


def test_suggestion_is_cleaned_and_audited(fake_model):
    out = suggest_alt(fake_model, Image.new("RGB", (40, 30), "blue"), context="Budget by year")
    assert out["alt"] == "Blue bar chart showing budget growth"  # 'Image of' removed
    assert out["audit"]["boundary"] == "local" and len(out["audit"]["image_sha256"]) == 64
    sent = _FakeModel.requests[0]
    user_text = sent["messages"][1]["content"][0]["text"]
    assert "<document_context>" in user_text  # document text fenced as untrusted data
    assert "tools" not in sent


def test_remote_endpoint_blocked_by_default(settings):
    settings.ai_base_url = "https://8.8.8.8/v1"  # a public address; no DNS lookup needed
    with pytest.raises(AIUnavailable, match="local-only policy"):
        check_policy(settings)
    settings.ai_allow_remote = True
    assert check_policy(settings) == "remote"
    settings.ai_base_url = "http://127.0.0.1:11434/v1"
    settings.ai_allow_remote = False
    assert check_policy(settings) == "local"


def test_pipeline_keeps_ai_alt_as_suggestion(sample_pdf, tmp_path, fake_model):
    r = remediate_file(sample_pdf, tmp_path / "o.pdf", display_name="s.pdf", settings=fake_model,
                       options=Options(engine="basic", ai=True, verapdf=False))
    fig = r["figures"][0]
    assert fig["alt"] is None  # not written without review
    assert fig["ai"]["alt"].startswith("Blue bar chart")


def test_pipeline_accept_ai_alt_writes_and_warns(sample_pdf, tmp_path, fake_model):
    r = remediate_file(sample_pdf, tmp_path / "o.pdf", display_name="s.pdf", settings=fake_model,
                       options=Options(engine="basic", ai=True, accept_ai_alt=True, verapdf=False))
    assert r["figures"][0]["alt"].startswith("Blue bar chart")
    assert any(i["rule"] == "ai.accepted-unreviewed" for i in r["issues"])
