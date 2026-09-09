"""Per-user desktop entry and reversible MIME associations."""

import configparser
import io
import os
import subprocess
import warnings
from pathlib import Path
from tempfile import NamedTemporaryFile

from . import formats, storage

DESKTOP_ID = "xdg-google-docs.desktop"
_GROUPS = ("Default Applications", "Added Associations", "Removed Associations")


def _root(variable, fallback):
    path = Path(os.environ.get(variable) or Path.home() / fallback)
    if not path.is_absolute():
        raise ValueError(f"{variable} must be an absolute path")
    return path


def _mimeapps_paths():
    config = _root("XDG_CONFIG_HOME", ".config")
    applications = _root("XDG_DATA_HOME", ".local/share") / "applications"
    names = ["mimeapps.list"]
    for desktop in os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":"):
        if desktop and "/" not in desktop and "\\" not in desktop:
            names.append(f"{desktop}-mimeapps.list")
    return list(
        dict.fromkeys(
            [root / name for root in (config, applications) for name in names]
            + [applications / "defaults.list"]
        )
    )


def _read_mimeapps(path):
    parser = configparser.ConfigParser(
        interpolation=None,
        delimiters=("=",),
        strict=False,
        empty_lines_in_values=False,
        default_section="__unused_defaults__",
    )
    parser.optionxform = str
    if path.exists():
        parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def _snapshot(paths, mime):
    return {
        str(path): {group: parser.get(group, mime, fallback=None) for group in _GROUPS}
        for path in paths
        for parser in [_read_mimeapps(path)]
    }


def _atomic_write(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), mode)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _query(mime):
    return subprocess.run(
        ["xdg-mime", "query", "default", mime],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _set_default(desktop, mime):
    subprocess.run(
        ["xdg-mime", "default", desktop, mime], check=True, capture_output=True, text=True
    )


def _update_database(applications):
    try:
        subprocess.run(
            ["update-desktop-database", str(applications)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        pass
    except (OSError, subprocess.CalledProcessError) as error:
        warnings.warn(f"Could not update desktop database: {error}", stacklevel=2)


def _entry(executable, mimes):
    path = Path(executable)
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("executable must be an absolute path to an executable file")
    if "=" in executable or any(ord(char) < 32 or ord(char) == 127 for char in executable):
        raise ValueError("executable contains characters unsupported in a desktop Exec key")
    # Exec quoting is decoded AFTER desktop string escapes, BEFORE field codes.
    quoted = "".join("\\" + char if char in '\\"`$' else char for char in executable)
    quoted = quoted.replace("\\", "\\\\").replace("%", "%%")
    return (
        "[Desktop Entry]\nType=Application\nName=Google Docs\n"
        "Comment=Open office documents in Google Docs, Sheets and Slides\n"
        f'Exec="{quoted}" open --desktop -- %F\n'
        "Terminal=false\nNoDisplay=true\nCategories=Office;\n"
        f"MimeType={';'.join(mimes)};\n"
    )


def install(executable: str, include_csv: bool = False, replace_defaults: bool = True):
    """Install for the current user; retain first-install backups across reinstalls.

    Failures propagate, with recovery metadata retained for a later uninstall.
    With replace_defaults=False only the desktop entry is installed.
    """
    mimes = list(formats.MIME_TYPES)
    if include_csv:
        mimes.append("text/csv")
    entry = _entry(executable, mimes)
    applications = _root("XDG_DATA_HOME", ".local/share") / "applications"
    path = applications / DESKTOP_ID
    with storage.locked():
        metadata = storage.state_dir() / "desktop.json"
        state = storage.read_json(metadata, None)
        if state is None:
            if path.exists():
                raise FileExistsError(f"Refusing to overwrite untracked desktop entry: {path}")
            state = {"entry_path": str(path), "entry": entry, "mimes": {}}
        elif state["entry_path"] != str(path):
            raise ValueError("XDG_DATA_HOME changed; uninstall the previous installation first")
        paths = _mimeapps_paths()
        if replace_defaults:
            # Back up everything before the first tool invocation or entry write.
            for mime in mimes:
                if mime not in state["mimes"]:
                    state["mimes"][mime] = {
                        "previous": _query(mime),
                        "before": _snapshot(paths, mime),
                    }
                else:
                    for name, values in _snapshot(paths, mime).items():
                        state["mimes"][mime]["before"].setdefault(name, values)
        state["entry"] = entry
        storage.write_json(metadata, state)
        _atomic_write(path, entry)
        _update_database(applications)
        if replace_defaults:
            _root("XDG_CONFIG_HOME", ".config").mkdir(parents=True, exist_ok=True)
            for mime in mimes:
                record = state["mimes"][mime]
                record["pending"] = True
                storage.write_json(metadata, state)
                try:
                    _set_default(DESKTOP_ID, mime)
                finally:
                    record["after"] = _snapshot([Path(p) for p in record["before"]], mime)
                    record["pending"] = False
                    storage.write_json(metadata, state)


def _restore(mime, record, owned):
    paths = [Path(name) for name in record["before"]]
    current = _snapshot(paths, mime)
    tool_error = None
    if owned and record["previous"] and record["previous"] != DESKTOP_ID:
        try:
            _set_default(record["previous"], mime)
        except (OSError, subprocess.CalledProcessError) as error:
            # A failing tool may already have changed files. Finish restoring
            # those keys, but retain metadata and report the failure for retry.
            tool_error = error
    for path in paths:
        name = str(path)
        parser = _read_mimeapps(path)
        changed = False
        for group in _GROUPS:
            before = record["before"][name][group]
            value = current[name][group]
            after = record.get("after", {}).get(name, {}).get(group)
            ids = (value or "").split(";")
            # Only revert an unchanged app-written value. Otherwise remove our
            # addition, leaving the user's other associations and ordering alone.
            if (value == after or (record.get("pending") and DESKTOP_ID in ids)) and (
                group != "Default Applications" or owned
            ):
                restored = before
            elif DESKTOP_ID in ids and DESKTOP_ID not in (before or "").split(";"):
                remaining = [item for item in ids if item and item != DESKTOP_ID]
                restored = ";".join(remaining) + ";" if remaining else None
            else:
                restored = value
            if parser.get(group, mime, fallback=None) == restored:
                continue
            changed = True
            if restored is None:
                parser.remove_option(group, mime)
            else:
                if not parser.has_section(group):
                    parser.add_section(group)
                parser.set(group, mime, restored)
        if changed:
            output = io.StringIO()
            parser.write(output, space_around_delimiters=False)
            _atomic_write(
                path.resolve(),
                output.getvalue(),
                path.stat().st_mode & 0o777 if path.exists() else 0o644,
            )
    if tool_error is not None:
        raise tool_error


def uninstall():
    """Restore still-owned defaults and remove only our tracked desktop entry."""
    with storage.locked():
        metadata = storage.state_dir() / "desktop.json"
        state = storage.read_json(metadata, None)
        if state is None:
            return
        for mime in list(state["mimes"]):
            record = state["mimes"][mime]
            if "after" in record or record.get("pending"):
                _restore(mime, record, _query(mime) == DESKTOP_ID)
            del state["mimes"][mime]
            storage.write_json(metadata, state)
        path = Path(state["entry_path"])
        if path.exists():
            if path.read_text(encoding="utf-8") != state["entry"]:
                raise RuntimeError(
                    f"Desktop entry was modified; leaving it and metadata intact: {path}"
                )
            path.unlink()
        _update_database(path.parent)
        metadata.unlink()
