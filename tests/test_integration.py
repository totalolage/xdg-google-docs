"""Real CLI/xdg subprocess checks in isolated per-user XDG directories."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def environment(tmp_path):
    env = dict(os.environ)
    for name in ("APPIMAGE", "APPDIR", "LD_LIBRARY_PATH"):
        env.pop(name, None)
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        path = tmp_path / name
        path.mkdir()
        env[name] = str(path)
    env["XDG_CURRENT_DESKTOP"] = "X-Generic"
    env["DE"] = "generic"
    env["PATH"] = f"{Path(sys.executable).parent}:{env['PATH']}"
    return env


def run(environment, *args, check=True):
    return subprocess.run(
        [sys.executable, "-m", "xdg_google_docs.cli", *args],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=check,
    )


def test_real_cli_missing_auth_is_actionable(environment):
    result = run(environment, "open", "--print-url", "missing.docx", check=False)
    assert result.returncode == 1
    assert "Not authenticated" in result.stderr
    assert "auth --client" in result.stderr


@pytest.mark.skipif(not shutil.which("xdg-mime"), reason="xdg-utils not installed")
def test_real_desktop_install_uninstall_does_not_deadlock(environment):
    result = run(environment, "install")
    assert "installed" in result.stdout
    entry = Path(environment["XDG_DATA_HOME"]) / "applications/xdg-google-docs.desktop"
    assert entry.exists()
    if shutil.which("desktop-file-validate"):
        subprocess.run(["desktop-file-validate", str(entry)], check=True, timeout=10)
    query = subprocess.run(
        [
            "xdg-mime",
            "query",
            "default",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert query.stdout.strip() == "xdg-google-docs.desktop"
    rtf = Path(environment["XDG_STATE_HOME"]) / "synthetic.rtf"
    rtf.write_text(r"{\rtf1\ansi Synthetic document.}")
    detected = subprocess.run(
        ["xdg-mime", "query", "filetype", str(rtf)],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    assert detected in {"application/rtf", "text/rtf"}
    rtf_handler = subprocess.run(
        ["xdg-mime", "query", "default", detected],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    assert rtf_handler == "xdg-google-docs.desktop"
    metadata = Path(environment["XDG_STATE_HOME"]) / "xdg-google-docs/desktop.json"
    original = json.loads(metadata.read_text())
    run(environment, "install")
    assert json.loads(metadata.read_text())["mimes"] == original["mimes"]
    run(environment, "uninstall")
    assert not entry.exists()
    assert not metadata.exists()
    mimeapps = Path(environment["XDG_CONFIG_HOME"]) / "mimeapps.list"
    if mimeapps.exists():
        assert "xdg-google-docs.desktop" not in mimeapps.read_text()
