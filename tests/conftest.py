from types import SimpleNamespace
from unittest.mock import Mock

import keyring
import pytest
from keyring.backends import SecretService

from xdg_google_docs import vault


@pytest.fixture(autouse=True)
def fake_secret_service(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/no-session-bus")
    values = {}
    backend = Mock()
    backend.get_password.side_effect = lambda service, profile: values.get((service, profile))
    backend.set_password.side_effect = lambda service, profile, value: values.__setitem__(
        (service, profile), value
    )
    factory = Mock(return_value=backend)
    monkeypatch.setattr(SecretService, "Keyring", factory)
    monkeypatch.setattr(vault, "Keyring", factory)
    # Backend discovery must never select a user's configured fallback.
    for name in ("get_keyring", "get_password", "set_password", "delete_password"):
        monkeypatch.setattr(
            keyring, name, Mock(side_effect=AssertionError("Implicit keyring access"))
        )
    return SimpleNamespace(values=values, backend=backend, factory=factory)
