import json
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from xdg_google_docs import storage


@pytest.fixture(autouse=True)
def isolated_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.mark.parametrize(
    "getter,variable,fallback",
    [
        (storage.config_dir, "XDG_CONFIG_HOME", ".config"),
        (storage.state_dir, "XDG_STATE_HOME", ".local/state"),
    ],
)
def test_xdg_paths_and_private_permissions(getter, variable, fallback, tmp_path, monkeypatch):
    path = getter()
    assert path.name == "xdg-google-docs"
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    path.chmod(0o777)
    assert getter() == path
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    monkeypatch.delenv(variable)
    assert getter() == tmp_path / fallback / "xdg-google-docs"
    monkeypatch.setenv(variable, "")
    assert getter() == tmp_path / fallback / "xdg-google-docs"
    monkeypatch.setenv(variable, "relative")
    with pytest.raises(ValueError, match="absolute"):
        getter()


def test_json_defaults_round_trip_and_private_replacement(tmp_path):
    path = tmp_path / "token.json"
    default = {}
    assert storage.read_json(path, default) is default
    assert storage.read_json(path) is None
    path.write_text("old")
    path.chmod(0o666)
    storage.write_json(path, {"token": "secret", "nested": [1, True, None]})
    assert storage.read_json(path) == {"token": "secret", "nested": [1, True, None]}
    assert path.read_text().endswith("\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [path]


def test_invalid_json_is_not_silently_discarded(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{")
    with pytest.raises(json.JSONDecodeError):
        storage.read_json(path, {})


@pytest.mark.parametrize("stage", ["serialize", "fsync", "replace"])
def test_failed_write_preserves_original_and_cleans_temporary(tmp_path, stage):
    path = tmp_path / "state.json"
    storage.write_json(path, {"old": True})
    target = {
        "serialize": "xdg_google_docs.storage.json.dump",
        "fsync": "xdg_google_docs.storage.os.fsync",
        "replace": "pathlib.Path.replace",
    }[stage]
    with patch(target, side_effect=OSError("write failed")):
        with pytest.raises(OSError, match="write failed"):
            storage.write_json(path, {"new": True})
    assert storage.read_json(path) == {"old": True}
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_replace_happens_after_fsync(tmp_path):
    path = tmp_path / "state.json"
    events = []
    replace = Path.replace

    def replace_checked(temporary, destination):
        assert events == ["fsync"]
        assert temporary.parent == destination.parent
        assert json.loads(temporary.read_text()) == {"ready": True}
        return replace(temporary, destination)

    with patch.object(storage.os, "fsync", side_effect=lambda fd: events.append("fsync")):
        with patch.object(Path, "replace", replace_checked):
            storage.write_json(path, {"ready": True})


@pytest.mark.parametrize("raises", [False, True])
def test_lock_is_exclusive_private_and_closed_on_exit(raises):
    streams = []

    def flock(stream, operation):
        streams.append(stream)
        assert operation == storage.fcntl.LOCK_EX
        assert not stream.closed

    with patch.object(storage.fcntl, "flock", side_effect=flock):
        try:
            with storage.locked():
                assert len(streams) == 1
                assert (
                    stat.S_IMODE((storage.state_dir() / "operation.lock").stat().st_mode) == 0o600
                )
                if raises:
                    raise RuntimeError("inside lock")
        except RuntimeError:
            assert raises
    assert streams[0].closed
