"""Private, atomic local state and a process lock for double-click races."""

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile


def directory(variable, fallback):
    root = Path(os.environ.get(variable) or Path.home() / fallback)
    if not root.is_absolute():
        raise ValueError(f"{variable} must be an absolute path")
    path = root / "xdg-google-docs"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def config_dir():
    return directory("XDG_CONFIG_HOME", ".config")


def state_dir():
    return directory("XDG_STATE_HOME", ".local/state")


def read_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path, value):
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def locked():
    # Credential identity follows config, while the document cache follows state.
    # Acquire both in this order to serialize refresh/logout across state roots.
    with (
        open(config_dir() / "credentials.lock", "a", opener=_private_open) as credentials,
        open(state_dir() / "operation.lock", "a", opener=_private_open) as stream,
    ):
        fcntl.flock(credentials, fcntl.LOCK_EX)
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def _private_open(path, flags):
    return os.open(path, flags, 0o600)
