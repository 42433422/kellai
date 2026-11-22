"""Candidate identity is derived from committed source, never an environment claim."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app import build_info


def test_provenance_uses_clean_git_tree_and_rejects_dirty_source(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "build_identity.py"
    spec = importlib.util.spec_from_file_location("build_identity", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend/pyproject.toml").write_text('[project]\nversion="1.0.1"\n')
    (tmp_path / ".gitignore").write_text("backend/build-info.json\n")
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()
    git("init", "-q")
    git("add", "backend/pyproject.toml", ".gitignore")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    monkeypatch.setenv("KELLAI_SOURCE_SHA", "e" * 40)
    monkeypatch.setenv("KELLAI_TEST_SECRET", "must-not-be-packaged")
    result = module.write_build_info(tmp_path)
    info = json.loads(result.read_text())
    assert info["source_sha"] == git("rev-parse", "HEAD")
    assert info["source_tree"] == git("rev-parse", "HEAD^{tree}")
    assert "must-not-be-packaged" not in result.read_text()
    (tmp_path / "backend/pyproject.toml").write_text('[project]\nversion="2.0.0"\n')
    with pytest.raises(RuntimeError, match="clean committed checkout"):
        module.write_build_info(tmp_path)


def test_frozen_identity_is_validated_and_source_mode_cannot_claim_a_package(tmp_path, monkeypatch):
    manifest = {"schema_version": 1, "source_sha": "a" * 40, "source_tree": "b" * 40,
                "version": "1.0.1", "platform": sys.platform, "architecture": "fixture", "channel": "candidate"}
    (tmp_path / "build-info.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(build_info, "__file__", str(tmp_path / "build_info.py"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("KELLAI_SOURCE_SHA", "f" * 40)
    assert build_info.load_build_info("1.0.1") == manifest
    with pytest.raises(RuntimeError, match="invalid"):
        build_info.load_build_info("2.0.0")
    monkeypatch.setattr(sys, "frozen", False)
    assert build_info.load_build_info("1.0.1")["source_sha"] is None
