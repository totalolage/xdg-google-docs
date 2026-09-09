"""OAuth storage in Secret Service, with verified migration from v0.1 files."""

import hashlib
import json

from keyring.backends.SecretService import Keyring
from keyring.errors import KeyringError
from secretstorage.exceptions import SecretStorageException

from .storage import config_dir, read_json

SERVICE = "xdg-google-docs"


def credentials(replacement=None):
    """Read or replace the credential bundle; caller holds storage.locked().

    Choose Secret Service directly, never a configurable plaintext fallback.
    A profile is scoped to its config directory, not a Google account, so auth
    can switch accounts while retaining the existing CLI's single-login model.
    """
    directory = config_dir()
    profile = "oauth-" + hashlib.sha256(str(directory.resolve()).encode()).hexdigest()
    legacy = []
    try:
        backend = Keyring()
        backend.appid = SERVICE
        raw = backend.get_password(SERVICE, profile)
        try:
            saved = json.loads(raw) if raw is not None else {}
        except (ValueError, TypeError):
            raise ValueError("The system keyring contains invalid credential data") from None
        if not isinstance(saved, dict):
            raise ValueError("The system keyring contains invalid credential data")
        for name in ("client", "token"):
            path = directory / f"{name}.json"
            if path.exists():
                value = read_json(path)
                if name in saved and saved[name] != value:
                    raise ValueError(
                        "Legacy credential files conflict with the system keyring. "
                        "Neither copy was removed; resolve the conflicting local file before retrying."
                    )
                saved[name] = value
                legacy.append(path)
        desired = saved if replacement is None else replacement
        if legacy or replacement is not None:
            serialized = json.dumps(desired)
            backend.set_password(SERVICE, profile, serialized)
            if backend.get_password(SERVICE, profile) != serialized:
                raise ValueError(
                    "System keyring write verification failed. Legacy credential files were kept."
                )
    except (KeyringError, SecretStorageException, OSError, RuntimeError):
        raise ValueError(
            "Cannot access the system keyring (Secret Service). "
            "Start or unlock GNOME Keyring or another Secret Service provider in your desktop session. "
            "Credentials will not fall back to plaintext files."
        ) from None
    # Only remove app-owned legacy files after the entire bundle was read back.
    for path in legacy:
        path.unlink()
    return desired
