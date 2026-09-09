import json
from unittest.mock import Mock, patch

import pytest
from google.auth.exceptions import RefreshError
from keyring.errors import KeyringLocked

from xdg_google_docs import auth, storage, vault


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
        credentials = factory.from_client_config.return_value.run_local_server.return_value
        credentials.refresh_token = "refresh"
        credentials.to_json.return_value = json.dumps(
            {"refresh_token": "refresh", "scopes": auth.SCOPES}
        )
        yield factory


@pytest.mark.parametrize("no_browser", [False, True])
def test_login_pkce_loopback_and_private_tokens(client, flow, no_browser):
    auth.login(client, no_browser=no_browser)
    flow.from_client_config.assert_called_once_with(
        json.loads(client.read_text()), auth.SCOPES, autogenerate_code_verifier=True
    )
    flow.from_client_config.return_value.run_local_server.assert_called_once_with(
        host="127.0.0.1",
        port=0,
        open_browser=not no_browser,
        timeout_seconds=300,
        prompt="consent",
        access_type="offline",
    )
    for name in ("token.json", "client.json"):
        assert not (storage.config_dir() / name).exists()
    assert vault.credentials() == {
        "client": json.loads(client.read_text()),
        "token": {"refresh_token": "refresh", "scopes": auth.SCOPES},
    }
    flow.from_client_secrets_file.assert_not_called()


def test_login_missing_client(flow):
    with pytest.raises(ValueError, match="--client"):
        auth.login()
    flow.from_client_config.assert_not_called()


def test_login_can_reuse_saved_client(client, flow):
    auth.login(client)
    flow.reset_mock()
    auth.login(no_browser=True)
    flow.from_client_config.assert_called_once_with(
        json.loads(client.read_text()), auth.SCOPES, autogenerate_code_verifier=True
    )


def test_v2_google_authorization_endpoint_is_accepted(client, flow):
    data = json.loads(client.read_text())
    data["installed"]["auth_uri"] = "https://accounts.google.com/o/oauth2/v2/auth"
    client.write_text(json.dumps(data))
    auth.login(client)
    flow.from_client_config.assert_called_once()


def test_malformed_client_does_not_start_oauth(client, flow):
    client.write_text("{")
    with pytest.raises(json.JSONDecodeError):
        auth.login(client)
    flow.from_client_config.assert_not_called()


def test_login_requires_refresh_token(client, flow):
    flow.from_client_config.return_value.run_local_server.return_value.refresh_token = None
    with pytest.raises(ValueError, match="refresh token"):
        auth.login(client)
    assert not (storage.config_dir() / "token.json").exists()
    assert vault.credentials() == {}


def test_failed_login_preserves_existing_token(client, flow):
    path = storage.config_dir() / "token.json"
    storage.write_json(path, {"refresh_token": "previous"})
    flow.from_client_config.return_value.run_local_server.return_value.refresh_token = None
    with pytest.raises(ValueError, match="refresh token"):
        auth.login(client)
    assert vault.credentials()["token"] == {"refresh_token": "previous"}
    assert not path.exists()


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
    flow.from_client_config.assert_not_called()
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
    flow.from_client_config.assert_not_called()


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
    client = {"installed": {"client_id": "synthetic-client"}}
    storage.write_json(storage.config_dir() / "client.json", client)
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
                assert vault.credentials()["token"] == data
            else:
                credentials.refresh.assert_called_once_with(request.return_value)
                assert vault.credentials()["token"]["token"] == "renewed"
    assert vault.credentials()["client"] == client
    assert not path.exists()
    assert not (storage.config_dir() / "client.json").exists()


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
    assert vault.credentials()["token"] == data
    assert not path.exists()


def test_locked_keyring_prevents_oauth_and_refresh(client, flow, fake_secret_service):
    fake_secret_service.backend.get_password.side_effect = KeyringLocked("synthetic-secret")
    with patch.object(auth, "Credentials") as factory, patch.object(auth, "Request") as request:
        for operation in (lambda: auth.login(client), auth.load_credentials):
            with pytest.raises(ValueError, match="Start or unlock") as caught:
                operation()
            assert "synthetic-secret" not in str(caught.value)
        factory.from_authorized_user_info.assert_not_called()
        request.assert_not_called()
    flow.from_client_config.assert_not_called()


def test_refresh_of_stored_bundle_preserves_client(client):
    data = {"scopes": auth.SCOPES, "refresh_token": "synthetic-refresh"}
    config = json.loads(client.read_text())
    vault.credentials({"client": config, "token": data})
    credentials = Mock(valid=False)
    renewed = {**data, "token": "synthetic-renewed"}
    credentials.to_json.return_value = json.dumps(renewed)
    with (
        patch.object(auth.Credentials, "from_authorized_user_info", return_value=credentials),
        patch.object(auth, "Request") as request,
    ):
        assert auth.load_credentials() is credentials
        credentials.refresh.assert_called_once_with(request.return_value)
    assert vault.credentials() == {"client": config, "token": renewed}
    assert not (storage.config_dir() / "client.json").exists()
    assert not (storage.config_dir() / "token.json").exists()


@pytest.mark.parametrize("symlink", [False, True])
def test_explicit_legacy_client_survives_migration(client, flow, symlink):
    config = json.loads(client.read_text())
    legacy = storage.config_dir() / "client.json"
    storage.write_json(legacy, config)
    supplied = legacy
    if symlink:
        supplied = client.with_name("client-link.json")
        supplied.symlink_to(legacy)
    auth.login(supplied)
    flow.from_client_config.assert_called_once_with(
        config, auth.SCOPES, autogenerate_code_verifier=True
    )
    assert vault.credentials()["client"] == config
    assert not legacy.exists()
