import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import httplib2
import pytest
from googleapiclient.errors import HttpError
from keyring.errors import KeyringLocked

from xdg_google_docs import cli, storage, vault

URL = "https://docs.google.com/document/d/test/edit"
REAL_DRIVE_SERVICE = cli.drive_service
REAL_LOGIN = cli.auth.login


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    with (
        patch.object(cli, "drive_service") as service,
        patch.object(cli, "open_document", return_value=(URL, True)) as opening,
        patch.object(cli.subprocess, "run") as run,
        patch.object(cli.auth, "login") as login,
    ):
        service.return_value = (Mock(), "account", {"emailAddress": "test@example.test"})
        yield service, opening, run, login


def test_multiple_files_continue_after_errors(offline, capsys):
    service, opening, run, _ = offline
    opening.side_effect = [(URL, True), ValueError("unsupported document"), (URL, False)]
    assert cli.main(["open", "--print-url", "a.docx", "b.bad", "c.xlsx"]) == 1
    assert opening.call_count == 3
    assert capsys.readouterr().out.count(URL) == 2
    run.assert_not_called()
    service.return_value[0].close.assert_called_once()


@pytest.mark.parametrize(
    "mode,flags,convert",
    [
        (None, [], True),
        ("office", [], False),
        ("convert", [], True),
        ("office", ["--convert"], True),
        ("convert", ["--keep-office"], False),
    ],
)
def test_config_and_explicit_mode_precedence(offline, mode, flags, convert):
    if mode:
        assert cli.main(["config", mode]) == 0
        assert storage.read_json(storage.config_dir() / "settings.json") == {"mode": mode}
    assert cli.main(["open", "--print-url", "--new", *flags, "a.docx"]) == 0
    service, opening, run, _ = offline
    opening.assert_called_once_with(
        service.return_value[0], "account", Path("a.docx"), convert=convert, new=True
    )
    run.assert_not_called()


def test_browser_launch_is_argument_vector(offline):
    assert cli.main(["open", "a.docx"]) == 0
    offline[2].assert_called_once_with(["xdg-open", URL], check=True, timeout=30)


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("xdg-open missing"),
        subprocess.CalledProcessError(1, "xdg-open"),
        subprocess.TimeoutExpired("xdg-open", 30),
    ],
)
def test_browser_failure_still_prints_url_and_closes_service(offline, capsys, error):
    offline[2].side_effect = error
    assert cli.main(["open", "a.docx", "b.docx"]) == 1
    output = capsys.readouterr()
    assert output.out.count(URL) == 2
    assert "xdg-google-docs:" in output.err
    assert offline[1].call_count == 2
    offline[0].return_value[0].close.assert_called_once()


@pytest.mark.parametrize("present", [False, True])
def test_status_is_local_without_check(offline, capsys, present):
    if present:
        storage.write_json(storage.config_dir() / "token.json", {"token": "secret"})
    assert cli.main(["status"]) == 0
    output = capsys.readouterr().out
    assert ("present in system keyring (not verified)" if present else "missing") in output
    assert "secret" not in output
    offline[0].assert_not_called()
    assert not (storage.config_dir() / "token.json").exists()
    assert vault.credentials() == ({"token": {"token": "secret"}} if present else {})


def test_status_check_verifies_and_closes(offline, capsys):
    assert cli.main(["status", "--check"]) == 0
    assert "Google access verified: test@example.test" in capsys.readouterr().out
    offline[0].return_value[0].close.assert_called_once()


@pytest.mark.parametrize(
    "args", [["status"], ["status", "--check"], ["logout"], ["open", "--desktop", "a.docx"]]
)
def test_locked_keyring_never_contacts_google(offline, fake_secret_service, capsys, args):
    fake_secret_service.backend.get_password.side_effect = KeyringLocked("synthetic-secret")
    with (
        patch.object(cli, "drive_service", REAL_DRIVE_SERVICE),
        patch.object(cli, "build") as build,
        patch.object(cli.auth, "Request") as request,
        patch.object(cli, "notify") as notify,
    ):
        assert cli.main(args) == 1
        build.assert_not_called()
        request.assert_not_called()
    output = capsys.readouterr()
    assert "Start or unlock" in output.err
    assert "synthetic-secret" not in output.out + output.err
    assert "Traceback" not in output.err
    offline[1].assert_not_called()
    offline[2].assert_not_called()
    if "--desktop" in args:
        message = storage.read_json(storage.state_dir() / "last-error.json")["message"]
        assert "synthetic-secret" not in message
        notify.assert_called_once_with(message)


@pytest.mark.parametrize(
    "bundle,args",
    [
        ({"token": "synthetic-secret"}, ["status", "--check"]),
        ({"token": {"scopes": None, "token": "synthetic-secret"}}, ["status", "--check"]),
        ({"client": {"installed": "synthetic-secret"}}, ["auth"]),
    ],
)
def test_malformed_nested_credentials_fail_without_leaks_or_google(offline, capsys, bundle, args):
    vault.credentials(bundle)
    with (
        patch.object(cli, "drive_service", REAL_DRIVE_SERVICE),
        patch.object(cli.auth, "login", REAL_LOGIN),
        patch.object(cli, "build") as build,
        patch.object(cli.auth, "InstalledAppFlow") as flow,
        patch.object(cli.auth, "Request") as request,
    ):
        assert cli.main(args) == 1
        build.assert_not_called()
        flow.from_client_config.assert_not_called()
        request.assert_not_called()
    output = capsys.readouterr()
    assert "synthetic-secret" not in output.out + output.err
    assert "Traceback" not in output.err
    assert vault.credentials() == bundle


def test_auth_dispatch_and_logout_preserve_other_state(offline):
    assert cli.main(["auth", "--client", "client.json", "--no-browser"]) == 0
    offline[3].assert_called_once_with(Path("client.json"), True)
    storage.write_json(storage.config_dir() / "token.json", {"token": "secret"})
    storage.write_json(storage.config_dir() / "client.json", {"installed": {}})
    storage.write_json(storage.state_dir() / "documents.json", {"key": "doc"})
    assert cli.main(["logout"]) == 0
    assert cli.main(["logout"]) == 0
    assert not (storage.config_dir() / "token.json").exists()
    assert not (storage.config_dir() / "client.json").exists()
    assert vault.credentials() == {"client": {"installed": {}}}
    assert storage.read_json(storage.state_dir() / "documents.json") == {"key": "doc"}


def test_setup_failure_is_reported_without_upload(offline, capsys):
    offline[0].side_effect = ValueError("Not authenticated")
    assert cli.main(["open", "a.docx"]) == 1
    assert "Not authenticated" in capsys.readouterr().err
    offline[1].assert_not_called()


def test_interrupt_closes_service(offline):
    offline[1].side_effect = KeyboardInterrupt
    assert cli.main(["open", "a.docx"]) == 130
    offline[0].return_value[0].close.assert_called_once()


@pytest.mark.parametrize(
    "error,expected",
    [
        (
            HttpError(httplib2.Response({"status": "403"}), b"secret", uri="https://secret.test"),
            "HTTP 403",
        ),
        (RuntimeError("secret"), "RuntimeError: operation failed"),
    ],
)
def test_desktop_errors_are_sanitized_and_persisted(offline, capsys, error, expected):
    offline[1].side_effect = error
    with patch.object(cli, "notify") as notify:
        assert cli.main(["open", "--desktop", "a.docx"]) == 1
    message = storage.read_json(storage.state_dir() / "last-error.json")["message"]
    assert expected in message
    assert "secret" not in message
    assert "secret" not in capsys.readouterr().err
    notify.assert_any_call(message)


@pytest.mark.parametrize(
    "field,reason,disabled",
    [
        ("errors", "accessNotConfigured", True),
        ("details", "SERVICE_DISABLED", True),
        ("errors", "insufficientPermissions", False),
        ("errors", "secret-unknown-reason", False),
    ],
)
def test_api_disabled_error_is_actionable_without_exposing_response(
    offline, capsys, field, reason, disabled
):
    content = json.dumps(
        {
            "error": {
                "message": "secret server message",
                field: [{"reason": reason, "metadata": {"consumer": "secret-project"}}],
            }
        }
    ).encode()
    offline[0].side_effect = HttpError(
        httplib2.Response({"status": "403"}), content, uri="https://secret.test"
    )
    with patch.object(cli, "notify"):
        assert cli.main(["open", "--desktop", "a.docx"]) == 1
    message = storage.read_json(storage.state_dir() / "last-error.json")["message"]
    assert ("Enable Google Drive API" in message) is disabled
    if disabled:
        assert "same Google Cloud project" in message
        assert "status --check" in message
    assert "secret" not in message
    assert "secret" not in capsys.readouterr().err
    offline[1].assert_not_called()


@pytest.mark.parametrize("created", [True, False])
def test_desktop_success_notification(offline, created):
    offline[1].return_value = (URL, created)
    with patch.object(cli, "notify") as notify:
        assert cli.main(["open", "--desktop", "--print-url", "a.docx"]) == 0
    notify.assert_any_call(
        "Uploaded a cloud copy." if created else "Opened the existing cloud copy."
    )


def test_notify_failures_are_nonfatal(offline):
    with patch.object(cli.shutil, "which", return_value="/usr/bin/notify-send"):
        for error in [OSError("missing"), subprocess.TimeoutExpired("notify-send", 5)]:
            offline[2].side_effect = error
            cli.notify("message")


@pytest.mark.parametrize(
    "args", [[], ["open"], ["config", "invalid"], ["open", "--convert", "--keep-office", "a.docx"]]
)
def test_invalid_arguments_exit_before_side_effects(offline, args):
    with pytest.raises(SystemExit) as caught:
        cli.main(args)
    assert caught.value.code == 2
    offline[0].assert_not_called()
    offline[2].assert_not_called()


def test_drive_service_account_key_includes_client_and_user(offline):
    with (
        patch.object(cli.auth, "load_credentials") as load,
        patch.object(cli, "build") as build,
        patch.object(cli.google_auth_httplib2, "AuthorizedHttp") as authorized,
        patch.object(cli.httplib2, "Http") as http,
    ):
        load.return_value.client_id = "client-one"
        build.return_value.about.return_value.get.return_value.execute.return_value = {
            "user": {"permissionId": "user-one"}
        }
        service, account, user = REAL_DRIVE_SERVICE()
        assert account == hashlib.sha256(b"client-one:user-one").hexdigest()
        assert service is build.return_value
        assert user == {"permissionId": "user-one"}
        http.assert_called_once_with(timeout=60)
        authorized.assert_called_once_with(load.return_value, http=http.return_value)
        build.assert_called_once_with(
            "drive", "v3", cache_discovery=False, http=authorized.return_value
        )
        load.return_value.client_id = "client-two"
        assert REAL_DRIVE_SERVICE()[1] != account
        load.return_value.client_id = "client-one"
        build.return_value.about.return_value.get.return_value.execute.return_value = {
            "user": {"permissionId": "user-two"}
        }
        assert REAL_DRIVE_SERVICE()[1] != account
