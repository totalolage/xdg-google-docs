import shlex
import subprocess

import pytest

from xdg_google_docs import desktop, formats, storage


@pytest.fixture
def environment(tmp_path, monkeypatch):
    for variable, name in (
        ("HOME", "home"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_STATE_HOME", "state"),
    ):
        monkeypatch.setenv(variable, str(tmp_path / name))
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME:Example")
    executable = tmp_path / "bin" / "xdg-google-docs"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    mimeapps = tmp_path / "config" / "mimeapps.list"
    calls = []

    def run(args, **kwargs):
        assert kwargs.get("check") is True
        assert not kwargs.get("shell")
        calls.append(args)
        parser = desktop._read_mimeapps(mimeapps)
        stdout = ""
        if args[:3] == ["xdg-mime", "query", "default"]:
            stdout = parser.get("Default Applications", args[3], fallback="").split(";")[0]
        elif args[:2] == ["xdg-mime", "default"]:
            for group in ("Default Applications", "Added Associations"):
                if not parser.has_section(group):
                    parser.add_section(group)
                parser.set(group, args[3], args[2] + ";")
            mimeapps.parent.mkdir(parents=True, exist_ok=True)
            with mimeapps.open("w") as stream:
                parser.write(stream)
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(desktop.subprocess, "run", run)
    return executable, mimeapps, calls


def write_mimeapps(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_entry_escaping(environment):
    executable, _, _ = environment
    executable = executable.with_name('a space "quote" \\ $d `cmd` %F single\'')
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    desktop.install(str(executable), replace_defaults=False)
    entry = (
        desktop._root("XDG_DATA_HOME", ".local/share") / "applications" / desktop.DESKTOP_ID
    ).read_text()
    line = next(line[5:] for line in entry.splitlines() if line.startswith("Exec="))
    assert '\\\\"quote\\\\"' in line
    assert "\\\\\\\\" in line
    assert "%%F" in line
    # Decode the desktop string layer, then Exec quoting, then literal %%.
    decoded = line.replace("\\\\", "\\")
    tokens = shlex.split(decoded)
    assert tokens[0].replace("\\$", "$").replace("\\`", "`").replace("%%", "%") == str(executable)
    assert tokens[1:] == ["open", "--desktop", "--", "%F"]
    assert "Terminal=false\n" in entry


@pytest.mark.parametrize("include_csv", [False, True])
def test_csv_opt_in(environment, include_csv):
    executable, _, calls = environment
    desktop.install(str(executable), include_csv=include_csv)
    registered = [args[3] for args in calls if args[:2] == ["xdg-mime", "default"]]
    assert set(registered) == set(formats.MIME_TYPES) | ({"text/csv"} if include_csv else set())


def test_first_install_backups_retained(environment):
    executable, mimeapps, _ = environment
    mime = formats.MIME_TYPES[0]
    write_mimeapps(
        mimeapps,
        f"[Default Applications]\n{mime}=old.desktop;fallback.desktop;\n"
        f"[Added Associations]\n{mime}=other.desktop;\n",
    )
    desktop.install(str(executable))
    before = storage.read_json(storage.state_dir() / "desktop.json")["mimes"][mime]
    desktop.install(str(executable), include_csv=True)
    after = storage.read_json(storage.state_dir() / "desktop.json")["mimes"][mime]
    assert after["before"] == before["before"]
    assert after["previous"] == "old.desktop"
    desktop.uninstall()
    parser = desktop._read_mimeapps(mimeapps)
    assert parser.get("Default Applications", mime) == "old.desktop;fallback.desktop;"
    assert parser.get("Added Associations", mime) == "other.desktop;"


def test_user_changed_default_preserved(environment):
    executable, mimeapps, _ = environment
    mime = formats.MIME_TYPES[0]
    write_mimeapps(mimeapps, f"[Default Applications]\n{mime}=old.desktop;\n")
    desktop.install(str(executable))
    write_mimeapps(
        mimeapps,
        f"[Default Applications]\n{mime}=new.desktop;{desktop.DESKTOP_ID};\n"
        f"[Added Associations]\n{mime}=new.desktop;{desktop.DESKTOP_ID};other.desktop;\n"
        "[Other Settings]\nCaseSensitive:Key=SomeValue\n",
    )
    desktop.uninstall()
    parser = desktop._read_mimeapps(mimeapps)
    assert parser.get("Default Applications", mime) == "new.desktop;"
    assert parser.get("Added Associations", mime) == "new.desktop;other.desktop;"
    assert parser.get("Other Settings", "CaseSensitive:Key") == "SomeValue"


def test_uninstall_no_prior_defaults(environment):
    executable, mimeapps, _ = environment
    write_mimeapps(
        mimeapps,
        "[Default Applications]\nx-scheme-handler:Example=Browser.desktop;\n"
        "[Unrelated]\nKeepCase=value%with=equals\n",
    )
    desktop.install(str(executable))
    desktop.uninstall()
    parser = desktop._read_mimeapps(mimeapps)
    for mime in formats.MIME_TYPES:
        for group in desktop._GROUPS:
            assert not parser.has_option(group, mime)
    assert parser.get("Default Applications", "x-scheme-handler:Example") == "Browser.desktop;"
    assert parser.get("Unrelated", "KeepCase") == "value%with=equals"
    assert not (storage.state_dir() / "desktop.json").exists()
    desktop.uninstall()


def test_registration_failure_keeps_recovery_metadata(environment, monkeypatch):
    executable, mimeapps, _ = environment
    original = desktop.subprocess.run

    def fail(args, **kwargs):
        result = original(args, **kwargs)
        if args[:2] == ["xdg-mime", "default"]:
            raise subprocess.CalledProcessError(1, args)
        return result

    monkeypatch.setattr(desktop.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        desktop.install(str(executable))
    assert (storage.state_dir() / "desktop.json").exists()
    monkeypatch.setattr(desktop.subprocess, "run", original)
    desktop.uninstall()
    assert not desktop._read_mimeapps(mimeapps).has_option(
        "Default Applications", formats.MIME_TYPES[0]
    )


def test_restore_failure_keeps_backup(environment, monkeypatch):
    executable, mimeapps, _ = environment
    mime = formats.MIME_TYPES[0]
    write_mimeapps(mimeapps, f"[Default Applications]\n{mime}=old.desktop;\n")
    desktop.install(str(executable))
    original = desktop.subprocess.run

    def fail(args, **kwargs):
        if args[:3] == ["xdg-mime", "default", "old.desktop"]:
            raise subprocess.CalledProcessError(1, args)
        return original(args, **kwargs)

    monkeypatch.setattr(desktop.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        desktop.uninstall()
    record = storage.read_json(storage.state_dir() / "desktop.json")["mimes"][mime]
    assert record["previous"] == "old.desktop"


def test_partial_restore_tool_failure_is_retryable(environment, monkeypatch):
    executable, mimeapps, _ = environment
    mime = formats.MIME_TYPES[0]
    write_mimeapps(mimeapps, f"[Default Applications]\n{mime}=old.desktop;fallback.desktop;\n")
    desktop.install(str(executable))
    original = desktop.subprocess.run

    def fail(args, **kwargs):
        result = original(args, **kwargs)
        if args[:3] == ["xdg-mime", "default", "old.desktop"]:
            raise subprocess.CalledProcessError(1, args)
        return result

    monkeypatch.setattr(desktop.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        desktop.uninstall()
    assert (
        desktop._read_mimeapps(mimeapps).get("Default Applications", mime)
        == "old.desktop;fallback.desktop;"
    )
    monkeypatch.setattr(desktop.subprocess, "run", original)
    desktop.uninstall()
    assert (
        desktop._read_mimeapps(mimeapps).get("Default Applications", mime)
        == "old.desktop;fallback.desktop;"
    )


def test_no_replacement_and_optional_database_tool(environment, monkeypatch):
    executable, _, calls = environment

    def missing(args, **kwargs):
        calls.append(args)
        raise FileNotFoundError(args[0])

    monkeypatch.setattr(desktop.subprocess, "run", missing)
    desktop.install(str(executable), replace_defaults=False)
    desktop.uninstall()
    assert all(args[0] == "update-desktop-database" for args in calls)


@pytest.mark.parametrize("name", ["relative", "/does/not/exist", "bad=name", "bad\nname"])
def test_invalid_executable(environment, name):
    executable, _, calls = environment
    if name.startswith("bad"):
        executable = executable.with_name(name)
        executable.write_text("")
        executable.chmod(0o755)
        name = str(executable)
    with pytest.raises(ValueError):
        desktop.install(name)
    assert calls == []


def test_removed_associations_and_desktop_specific_paths(environment, monkeypatch):
    executable, mimeapps, _ = environment
    mime = formats.MIME_TYPES[0]
    specific = mimeapps.with_name("gnome-mimeapps.list")
    write_mimeapps(
        specific,
        f"[Removed Associations]\n{mime}={desktop.DESKTOP_ID};other.desktop;\n"
        "[Unrelated]\nCase:Key=KeepMe\n",
    )
    original = desktop.subprocess.run

    def run(args, **kwargs):
        result = original(args, **kwargs)
        if args[:3] == ["xdg-mime", "default", desktop.DESKTOP_ID] and args[3] == mime:
            write_mimeapps(
                specific,
                f"[Removed Associations]\n{mime}=other.desktop;\n[Unrelated]\nCase:Key=KeepMe\n",
            )
        return result

    monkeypatch.setattr(desktop.subprocess, "run", run)
    desktop.install(str(executable))
    desktop.uninstall()
    parser = desktop._read_mimeapps(specific)
    assert parser.get("Removed Associations", mime) == f"{desktop.DESKTOP_ID};other.desktop;"
    assert parser.get("Unrelated", "Case:Key") == "KeepMe"


def test_query_failure_does_not_install(environment, monkeypatch):
    executable, _, _ = environment

    def fail(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(desktop.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        desktop.install(str(executable))
    assert not (storage.state_dir() / "desktop.json").exists()
    assert not (
        desktop._root("XDG_DATA_HOME", ".local/share") / "applications" / desktop.DESKTOP_ID
    ).exists()


def test_non_executable_file_rejected(environment):
    executable, _, calls = environment
    executable.chmod(0o644)
    with pytest.raises(ValueError):
        desktop.install(str(executable))
    assert calls == []
