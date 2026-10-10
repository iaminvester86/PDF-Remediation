from __future__ import annotations

import hashlib
import json

from pdf_remediation.config import Settings
from scripts.evaluate_corpus import run_corpus

from conftest import make_sample


def test_corpus_runner_records_manifest_regressions(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    make_sample(corpus / "sample.pdf")
    manifest = {
        "version": 1,
        "documents": [{
            "id": "sample",
            "file": "sample.pdf",
            "sha256": hashlib.sha256((corpus / "sample.pdf").read_bytes()).hexdigest(),
            "category": "born-digital",
            "source": "generated test fixture",
            "license": "Apache-2.0 project test fixture",
            "expected": {
                "required_roles": {"H1": 1, "H2": 1, "LI": 2},
                "forbidden_issue_rules": ["tagger.possible-table"],
            },
        }],
    }
    (corpus / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = run_corpus(
        corpus,
        tmp_path / "results",
        engine="basic",
        verapdf=False,
        settings=Settings.from_env(data_dir=tmp_path / "data"),
    )

    assert report["total"] == 1 and report["passed"] == 1 and report["failed"] == 0
    case = report["cases"][0]
    assert case["visual_identical"] and case["text_identical"]
    assert case["roles"]["H1"] >= 1 and case["roles"]["H2"] >= 1 and case["roles"]["LI"] >= 2
    assert (tmp_path / "results" / "corpus-results.json").is_file()
    assert (tmp_path / "results" / "corpus-results.csv").is_file()


def test_corpus_runner_rejects_manifest_path_traversal(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    make_sample(corpus / "sample.pdf")
    manifest = {
        "version": 1,
        "documents": [{
            "id": "escape",
            "file": "../outside.pdf",
            "sha256": "0" * 64,
            "category": "test",
            "source": "test",
            "license": "test",
        }],
    }
    (corpus / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    try:
        run_corpus(corpus, tmp_path / "results", engine="basic", verapdf=False)
    except ValueError as exc:
        assert "inside the corpus directory" in str(exc)
    else:
        raise AssertionError("manifest path traversal was accepted")


def test_corpus_runner_fails_when_declared_roles_are_missing(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    make_sample(corpus / "sample.pdf")
    manifest = {
        "version": 1,
        "documents": [{
            "id": "missing-table",
            "file": "sample.pdf",
            "sha256": hashlib.sha256((corpus / "sample.pdf").read_bytes()).hexdigest(),
            "category": "born-digital",
            "source": "generated test fixture",
            "license": "Apache-2.0 project test fixture",
            "expected": {"required_roles": {"Table": 1}},
        }],
    }
    (corpus / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = run_corpus(
        corpus,
        tmp_path / "results",
        engine="basic",
        verapdf=False,
        settings=Settings.from_env(data_dir=tmp_path / "data"),
    )

    assert report["passed"] == 0 and report["failed"] == 1
    assert "expected at least 1 Table structure element(s), found 0" in report["cases"][0]["failures"]


def test_corpus_runner_rejects_changed_input_hash(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    make_sample(corpus / "sample.pdf")
    manifest = {
        "version": 1,
        "documents": [{
            "id": "changed-input",
            "file": "sample.pdf",
            "sha256": "0" * 64,
            "category": "born-digital",
            "source": "generated test fixture",
            "license": "Apache-2.0 project test fixture",
        }],
    }
    (corpus / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    try:
        run_corpus(corpus, tmp_path / "results", engine="basic", verapdf=False)
    except ValueError as exc:
        assert "sha256 does not match" in str(exc)
    else:
        raise AssertionError("changed corpus input was accepted")
