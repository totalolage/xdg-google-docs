"""Real CLI/xdg subprocess checks in isolated per-user XDG directories."""

import json
import os
import select
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_credential_operations_share_lock_across_state_directories(environment):
    first_code = (
        "from xdg_google_docs.storage import locked\n"
        "with locked():\n"
        " print('holding', flush=True)\n"
        " input()\n"
    )
    second_code = (
        "from xdg_google_docs.storage import locked\n"
        "with locked():\n"
        " print('acquired', flush=True)\n"
    )
    other = {**environment, "XDG_STATE_HOME": environment["XDG_STATE_HOME"] + "-other"}
    first = subprocess.Popen(
        [sys.executable, "-c", first_code],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    second = None
    try:
        assert select.select([first.stdout], [], [], 10)[0]
        assert first.stdout.readline().strip() == "holding"
        second = subprocess.Popen(
            [sys.executable, "-c", second_code],
            env=other,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert not select.select([second.stdout], [], [], 0.3)[0]
        first.communicate(input="\n", timeout=10)
        output, error = second.communicate(timeout=10)
        assert first.returncode == second.returncode == 0
        assert output.strip() == "acquired"
        assert not error
    finally:
        for process in (first, second):
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate()


@pytest.fixture
def environment(tmp_path):
    env = dict(os.environ)
    for name in (
        "APPIMAGE",
        "APPDIR",
        "LD_LIBRARY_PATH",
        "DBUS_SESSION_BUS_ADDRESS",
        "WAYLAND_DISPLAY",
    ):
        env.pop(name, None)
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        path = tmp_path / name
        path.mkdir()
        env[name] = str(path)
    env["XDG_CURRENT_DESKTOP"] = "X-Generic"
    env["DE"] = "generic"
    env["DISPLAY"] = ":99"
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={tmp_path}/no-session-bus"
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
    assert_keyring_unavailable(result.stderr)
    assert "https://" not in result.stdout


def assert_keyring_unavailable(message):
    assert "system keyring" in message
    assert "Secret Service" in message
    assert "Start or unlock" in message
    assert "Traceback" not in message
    assert "accounts.google.com" not in message
    assert "Google access verified" not in message


@pytest.mark.skipif(
    not shutil.which("xdg-mime") or not shutil.which("update-mime-database"),
    reason="xdg-utils and shared-mime-info required",
)
def test_real_desktop_install_uninstall_does_not_deadlock(environment):
    result = run(environment, "install")
    assert "installed" in result.stdout
    entry = Path(environment["XDG_DATA_HOME"]) / "applications/xdg-google-docs.desktop"
    assert entry.exists()
    assert "Icon=xdg-google-docs-document\n" in entry.read_text()
    assert "text/csv;" in entry.read_text()
    data = Path(environment["XDG_DATA_HOME"])
    icon_map = data / "mime/icons"
    assert "xdg-google-docs-document" in icon_map.read_text()
    assert "text/csv:" not in icon_map.read_text()
    assert (data / "icons/hicolor/scalable/mimetypes/xdg-google-docs-document.svg").exists()
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
    if shutil.which("xdg-open"):
        launched = subprocess.run(
            ["xdg-open", str(rtf)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert_keyring_unavailable(launched.stderr)
        error = Path(environment["XDG_STATE_HOME"]) / "xdg-google-docs/last-error.json"
        assert_keyring_unavailable(json.loads(error.read_text())["message"])
    metadata = Path(environment["XDG_STATE_HOME"]) / "xdg-google-docs/desktop.json"
    original = json.loads(metadata.read_text())
    run(environment, "install")
    assert json.loads(metadata.read_text())["mimes"] == original["mimes"]
    run(environment, "uninstall")
    assert not entry.exists()
    assert not metadata.exists()
    assert "xdg-google-docs-" not in icon_map.read_text()
    mimeapps = Path(environment["XDG_CONFIG_HOME"]) / "mimeapps.list"
    if mimeapps.exists():
        assert "xdg-google-docs.desktop" not in mimeapps.read_text()
