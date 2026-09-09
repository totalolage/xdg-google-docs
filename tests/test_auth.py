import json
import stat
from unittest.mock import Mock, patch

import pytest
from google.auth.exceptions import RefreshError

from xdg_google_docs import auth, storage


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "download.json"
    path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "test-client",
                    "client_secret": "test-secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        )
    )
    return path


@pytest.fixture
def flow():
    with patch.object(auth, "InstalledAppFlow") as factory:
        credentials = factory.from_client_secrets_file.return_value.run_local_server.return_value
        credentials.refresh_token = "refresh"
        credentials.to_json.return_value = json.dumps(
            {"refresh_token": "refresh", "scopes": auth.SCOPES}
        )
        yield factory


@pytest.mark.parametrize("no_browser", [False, True])
def test_login_pkce_loopback_and_private_tokens(client, flow, no_browser):
    auth.login(client, no_browser=no_browser)
    flow.from_client_secrets_file.assert_called_once_with(
        str(storage.config_dir() / "client.json"), auth.SCOPES, autogenerate_code_verifier=True
    )
    flow.from_client_secrets_file.return_value.run_local_server.assert_called_once_with(
        host="127.0.0.1",
        port=0,
        open_browser=not no_browser,
        timeout_seconds=300,
        prompt="consent",
        access_type="offline",
    )
    for name in ("token.json", "client.json"):
        assert stat.S_IMODE((storage.config_dir() / name).stat().st_mode) == 0o600
    assert storage.read_json(storage.config_dir() / "token.json")["refresh_token"] == "refresh"


def test_login_missing_client(flow):
    with pytest.raises(ValueError, match="--client"):
        auth.login()
    flow.from_client_secrets_file.assert_not_called()


def test_login_can_reuse_saved_client(client, flow):
    auth.login(client)
    flow.reset_mock()
    auth.login(no_browser=True)
    flow.from_client_secrets_file.assert_called_once_with(
        str(storage.config_dir() / "client.json"), auth.SCOPES, autogenerate_code_verifier=True
    )


def test_v2_google_authorization_endpoint_is_accepted(client, flow):
    data = json.loads(client.read_text())
    data["installed"]["auth_uri"] = "https://accounts.google.com/o/oauth2/v2/auth"
    client.write_text(json.dumps(data))
    auth.login(client)
    flow.from_client_secrets_file.assert_called_once()


def test_malformed_client_does_not_start_oauth(client, flow):
    client.write_text("{")
    with pytest.raises(json.JSONDecodeError):
        auth.login(client)
    flow.from_client_secrets_file.assert_not_called()


def test_login_requires_refresh_token(client, flow):
    flow.from_client_secrets_file.return_value.run_local_server.return_value.refresh_token = None
    with pytest.raises(ValueError, match="refresh token"):
        auth.login(client)
    assert not (storage.config_dir() / "token.json").exists()


def test_failed_login_preserves_existing_token(client, flow):
    path = storage.config_dir() / "token.json"
    storage.write_json(path, {"refresh_token": "previous"})
    flow.from_client_secrets_file.return_value.run_local_server.return_value.refresh_token = None
    with pytest.raises(ValueError, match="refresh token"):
        auth.login(client)
    assert storage.read_json(path) == {"refresh_token": "previous"}


@pytest.mark.parametrize("change", ["web", "auth_uri", "token_uri"])
def test_rejects_wrong_client_type_or_endpoints(client, flow, change):
    data = json.loads(client.read_text())
    if change == "web":
        data = {"web": data["installed"]}
    else:
        data["installed"][change] = "https://attacker.test/oauth"
    client.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        auth.login(client)
    flow.from_client_secrets_file.assert_not_called()
    assert not (storage.config_dir() / "client.json").exists()


def test_saved_client_is_also_validated(flow):
    storage.write_json(
        storage.config_dir() / "client.json",
        {
            "installed": {
                "auth_uri": "https://attacker.test/auth",
                "token_uri": "https://attacker.test/token",
            }
        },
    )
    with pytest.raises(ValueError):
        auth.login()
    flow.from_client_secrets_file.assert_not_called()


def test_ambiguous_client_rejected_before_real_oauth_factory(client):
    data = json.loads(client.read_text())
    data["web"] = {**data["installed"], "token_uri": "https://attacker.invalid/token"}
    client.write_text(json.dumps(data))
    with patch.object(auth.InstalledAppFlow, "run_local_server") as server:
        with pytest.raises(ValueError, match="Desktop app"):
            auth.login(client)
        server.assert_not_called()


@pytest.mark.parametrize("data", [None, {}, {"scopes": []}, {"scopes": ["openid"]}])
def test_missing_credentials_or_scopes_never_refresh(data):
    if data is not None:
        storage.write_json(storage.config_dir() / "token.json", data)
    with patch.object(auth, "Credentials") as factory:
        with pytest.raises(ValueError, match="authenticated|drive.file"):
            auth.load_credentials()
        factory.from_authorized_user_info.assert_not_called()


def test_stored_credentials_require_refresh_token():
    storage.write_json(
        storage.config_dir() / "token.json",
        {"scopes": auth.SCOPES, "client_id": "client", "client_secret": "secret"},
    )
    with patch.object(auth, "Request") as request:
        with pytest.raises(ValueError, match="refresh_token"):
            auth.load_credentials()
        request.assert_not_called()


@pytest.mark.parametrize("valid", [True, False])
def test_load_and_refresh_credentials(valid):
    path = storage.config_dir() / "token.json"
    data = {"scopes": auth.SCOPES, "refresh_token": "old"}
    storage.write_json(path, data)
    credentials = Mock(valid=valid)
    credentials.to_json.return_value = json.dumps({**data, "token": "renewed"})
    with patch.object(
        auth.Credentials, "from_authorized_user_info", return_value=credentials
    ) as factory:
        with patch.object(auth, "Request") as request:
            assert auth.load_credentials() is credentials
            factory.assert_called_once_with(data, auth.SCOPES)
            if valid:
                credentials.refresh.assert_not_called()
                request.assert_not_called()
                assert storage.read_json(path) == data
            else:
                credentials.refresh.assert_called_once_with(request.return_value)
                assert storage.read_json(path)["token"] == "renewed"
                assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_revoked_refresh_preserves_token_and_explains_reauth():
    path = storage.config_dir() / "token.json"
    data = {"scopes": auth.SCOPES, "refresh_token": "old"}
    storage.write_json(path, data)
    credentials = Mock(valid=False)
    credentials.refresh.side_effect = RefreshError("sensitive server details")
    with patch.object(auth.Credentials, "from_authorized_user_info", return_value=credentials):
        with patch.object(auth, "Request"):
            with pytest.raises(ValueError, match="expired or was revoked") as caught:
                auth.load_credentials()
    assert "sensitive" not in str(caught.value)
    assert storage.read_json(path) == data
