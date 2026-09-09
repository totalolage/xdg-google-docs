import hashlib
import json
from pathlib import Path

import pytest
from keyring.errors import KeyringError, KeyringLocked
from secretstorage.exceptions import SecretStorageException

from xdg_google_docs import storage, vault

BUNDLE = {
    "client": {"installed": {"client_id": "synthetic-client", "client_secret": "synthetic-secret"}},
    "token": {"refresh_token": "synthetic-refresh", "token": "synthetic-access"},
}


@pytest.fixture
def legacy():
    paths = []
    for name, data in BUNDLE.items():
        path = storage.config_dir() / f"{name}.json"
        storage.write_json(path, data)
        paths.append(path)
    return paths


def test_empty_vault_uses_explicit_backend_and_hashed_profile(fake_secret_service):
    assert vault.credentials() == {}
    profile = "oauth-" + hashlib.sha256(str(storage.config_dir().resolve()).encode()).hexdigest()
    fake_secret_service.factory.assert_called_once_with()
    assert fake_secret_service.backend.appid == "xdg-google-docs"
    fake_secret_service.backend.get_password.assert_called_once_with("xdg-google-docs", profile)
    fake_secret_service.backend.set_password.assert_not_called()


@pytest.mark.parametrize("replace", [False, True])
def test_migration_sets_and_verifies_entire_bundle_before_unlink(
    legacy, fake_secret_service, monkeypatch, replace
):
    events = []
    backend = fake_secret_service.backend
    get = backend.get_password.side_effect
    set_password = backend.set_password.side_effect
    unlink = Path.unlink

    def read(service, profile):
        assert all(path.exists() for path in legacy)
        events.append("get")
        return get(service, profile)

    def write(service, profile, raw):
        assert all(path.exists() for path in legacy)
        assert json.loads(raw) == BUNDLE
        events.append("set")
        set_password(service, profile, raw)

    def remove(path, *args, **kwargs):
        events.append(path.name)
        return unlink(path, *args, **kwargs)

    backend.get_password.side_effect = read
    backend.set_password.side_effect = write
    monkeypatch.setattr(Path, "unlink", remove)
    assert vault.credentials(BUNDLE if replace else None) == BUNDLE
    assert events == ["get", "set", "get", "client.json", "token.json"]
    assert not any(path.exists() for path in legacy)
    assert len(fake_secret_service.values) == 1


@pytest.mark.parametrize("failure", ["set", "readback", "mismatch"])
def test_failed_write_or_verification_preserves_legacy(legacy, fake_secret_service, failure):
    original = [path.read_bytes() for path in legacy]
    backend = fake_secret_service.backend
    if failure == "set":
        backend.set_password.side_effect = KeyringError("synthetic-secret")
    else:
        backend.get_password.side_effect = [
            None,
            KeyringLocked("synthetic-secret") if failure == "readback" else "{}",
        ]
    with pytest.raises(ValueError, match="keyring") as caught:
        vault.credentials()
    assert "synthetic-secret" not in str(caught.value)
    assert [path.read_bytes() for path in legacy] == original
    backend.set_password.assert_called_once()


@pytest.mark.parametrize("name", ["client", "token"])
@pytest.mark.parametrize("replacement", [None, {}])
def test_conflicting_legacy_fails_closed(legacy, fake_secret_service, name, replacement):
    original = [path.read_bytes() for path in legacy]
    fake_secret_service.backend.get_password.return_value = json.dumps(
        {name: {"conflicting": "synthetic-secret"}}
    )
    fake_secret_service.backend.get_password.side_effect = None
    with pytest.raises(ValueError, match="conflict") as caught:
        vault.credentials(replacement)
    assert "synthetic-secret" not in str(caught.value)
    fake_secret_service.backend.set_password.assert_not_called()
    assert [path.read_bytes() for path in legacy] == original


def test_matching_legacy_is_removed_without_losing_stored_fields(legacy, fake_secret_service):
    saved = {**BUNDLE, "extra": "preserved"}
    vault.credentials(saved)
    for name, data in BUNDLE.items():
        storage.write_json(storage.config_dir() / f"{name}.json", data)
    assert vault.credentials() == saved
    assert not any(path.exists() for path in legacy)


@pytest.mark.parametrize("raw", ["{synthetic-secret", "[]", "null", '"synthetic-secret"', "42"])
def test_malformed_stored_bundle_is_safe(legacy, fake_secret_service, raw):
    fake_secret_service.backend.get_password.side_effect = None
    fake_secret_service.backend.get_password.return_value = raw
    with pytest.raises(ValueError, match="invalid credential data") as caught:
        vault.credentials()
    assert "synthetic-secret" not in str(caught.value)
    assert all(path.exists() for path in legacy)
    fake_secret_service.backend.set_password.assert_not_called()


def test_malformed_legacy_is_not_written_or_removed(legacy, fake_secret_service):
    legacy[1].write_text("{synthetic-secret")
    with pytest.raises(ValueError) as caught:
        vault.credentials()
    assert "synthetic-secret" not in str(caught.value)
    assert all(path.exists() for path in legacy)
    fake_secret_service.backend.set_password.assert_not_called()


@pytest.mark.parametrize("stage", ["construct", "read", "write"])
@pytest.mark.parametrize(
    "error", [KeyringError, KeyringLocked, SecretStorageException, OSError, RuntimeError]
)
def test_backend_failures_are_actionable_and_sanitized(legacy, fake_secret_service, stage, error):
    target = {
        "construct": fake_secret_service.factory,
        "read": fake_secret_service.backend.get_password,
        "write": fake_secret_service.backend.set_password,
    }[stage]
    target.side_effect = error("synthetic-secret")
    with pytest.raises(ValueError, match="Start or unlock") as caught:
        vault.credentials()
    assert "synthetic-secret" not in str(caught.value)
    assert "plaintext" in str(caught.value)
    assert all(path.exists() for path in legacy)
    if stage != "write":
        fake_secret_service.backend.set_password.assert_not_called()


def test_profiles_are_separated_by_config_directory(fake_secret_service, tmp_path, monkeypatch):
    first = str(tmp_path / "first")
    monkeypatch.setenv("XDG_CONFIG_HOME", first)
    vault.credentials(BUNDLE)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "second"))
    assert vault.credentials() == {}
    vault.credentials({"client": BUNDLE["client"]})
    monkeypatch.setenv("XDG_CONFIG_HOME", first)
    assert vault.credentials() == BUNDLE
    assert len(fake_secret_service.values) == 2
    assert {service for service, _ in fake_secret_service.values} == {"xdg-google-docs"}


def test_stored_bundle_read_does_not_rewrite(fake_secret_service):
    vault.credentials(BUNDLE)
    fake_secret_service.backend.set_password.reset_mock()
    assert vault.credentials() == BUNDLE
    assert vault.credentials() == BUNDLE
    fake_secret_service.backend.set_password.assert_not_called()
    assert not (storage.config_dir() / "client.json").exists()
    assert not (storage.config_dir() / "token.json").exists()
