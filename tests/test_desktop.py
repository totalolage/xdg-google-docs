import shlex
import subprocess
from pathlib import Path
from xml.etree import ElementTree

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
    monkeypatch.setattr(desktop.shutil, "which", lambda name: f"/usr/bin/{name}")
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
    assert all(args[0] in {"update-desktop-database", "gtk-update-icon-cache"} for args in calls)


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


def test_icons_are_packaged_registered_and_removed(environment):
    executable, _, calls = environment
    desktop.install(str(executable))
    data = desktop._root("XDG_DATA_HOME", ".local/share")
    entry = (data / "applications" / desktop.DESKTOP_ID).read_text()
    assert "Icon=xdg-google-docs-document\n" in entry
    assert "text/csv;" in entry
    package = data / "mime/packages/xdg-google-docs.xml"
    root = ElementTree.fromstring(package.read_text())
    ns = {"m": "http://www.freedesktop.org/standards/shared-mime-info"}
    mappings = {item.attrib["type"]: item.find("m:icon", ns).attrib["name"] for item in root}
    assert mappings[formats.FORMATS[".docx"][0]] == "xdg-google-docs-document"
    assert mappings[formats.FORMATS[".xlsx"][0]] == "xdg-google-docs-spreadsheet"
    assert mappings[formats.FORMATS[".pptx"][0]] == "xdg-google-docs-presentation"
    assert "text/csv" not in mappings
    assert "text/rtf" not in mappings  # Canonical application/rtf covers its alias.
    for item in root:
        assert item.find("m:generic-icon", ns).attrib["name"] == mappings[item.attrib["type"]]
    assert not root.findall(".//m:glob", ns)
    installed = list((data / "icons/hicolor/scalable/mimetypes").glob("*.svg"))
    assert len(installed) == 3
    for icon in installed:
        assert ElementTree.fromstring(icon.read_text()).tag.endswith("svg")
    assert any(args[0] == "update-mime-database" for args in calls)
    desktop.uninstall()
    assert not package.exists()
    assert all(not icon.exists() for icon in installed)


def test_no_defaults_only_installs_app_icons(environment):
    executable, _, calls = environment
    desktop.install(str(executable), replace_defaults=False)
    data = desktop._root("XDG_DATA_HOME", ".local/share")
    assert not (data / "mime/packages/xdg-google-docs.xml").exists()
    assert not any(args[0] == "update-mime-database" for args in calls)
    assert "text/csv;" in (data / "applications" / desktop.DESKTOP_ID).read_text()


def test_icon_reinstall_and_csv_opt_in(environment):
    executable, _, _ = environment
    desktop.install(str(executable))
    original = storage.read_json(storage.state_dir() / "desktop.json")["icon_files"]
    desktop.install(str(executable))
    assert storage.read_json(storage.state_dir() / "desktop.json")["icon_files"] == original
    desktop.install(str(executable), include_csv=True)
    package = desktop._root("XDG_DATA_HOME", ".local/share") / "mime/packages/xdg-google-docs.xml"
    assert 'type="text/csv"' in package.read_text()
    desktop.install(str(executable), replace_defaults=False)
    assert 'type="text/csv"' in package.read_text()
    desktop.uninstall()
    assert not package.exists()


def test_modified_icons_are_preserved(environment):
    executable, _, _ = environment
    desktop.install(str(executable))
    tracked = storage.read_json(storage.state_dir() / "desktop.json")["icon_files"]
    icon = Path(next(iter(tracked)))
    original = icon.read_text()
    icon.write_text("user customization")
    with pytest.raises(FileExistsError, match="modified icon"):
        desktop.install(str(executable))
    with pytest.raises(RuntimeError, match="Icon file was modified"):
        desktop.uninstall()
    assert icon.read_text() == "user customization"
    assert (storage.state_dir() / "desktop.json").exists()
    icon.write_text(original)
    desktop.uninstall()


def test_untracked_icon_is_not_overwritten(environment):
    executable, _, _ = environment
    icon = (
        desktop._root("XDG_DATA_HOME", ".local/share")
        / "icons/hicolor/scalable/mimetypes/xdg-google-docs-document.svg"
    )
    icon.parent.mkdir(parents=True)
    icon.write_text("preexisting")
    with pytest.raises(FileExistsError, match="untracked"):
        desktop.install(str(executable))
    assert icon.read_text() == "preexisting"
    desktop.uninstall()
    assert icon.read_text() == "preexisting"


def test_mime_refresh_failure_can_be_retried(environment, monkeypatch):
    executable, _, _ = environment
    original = desktop.subprocess.run

    def fail(args, **kwargs):
        if args[0] == "update-mime-database":
            raise subprocess.CalledProcessError(1, args)
        return original(args, **kwargs)

    monkeypatch.setattr(desktop.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        desktop.install(str(executable))
    assert storage.read_json(storage.state_dir() / "desktop.json")["icon_files"]
    monkeypatch.setattr(desktop.subprocess, "run", original)
    desktop.install(str(executable))
    desktop.uninstall()


def test_missing_mime_tool_fails_before_installing(environment, monkeypatch):
    executable, _, _ = environment
    monkeypatch.setattr(desktop.shutil, "which", lambda _: None)
    with pytest.raises(FileNotFoundError, match="shared-mime-info"):
        desktop.install(str(executable))
    assert not (storage.state_dir() / "desktop.json").exists()
    assert not (desktop._root("XDG_DATA_HOME", ".local/share") / "applications").exists()


def test_interrupted_icon_install_can_be_uninstalled(environment, monkeypatch):
    executable, _, _ = environment
    original = desktop._atomic_write

    def fail(path, text, mode=0o644):
        if path.suffix == ".svg":
            raise OSError("interrupted before icon directories were created")
        original(path, text, mode)

    monkeypatch.setattr(desktop, "_atomic_write", fail)
    with pytest.raises(OSError, match="interrupted"):
        desktop.install(str(executable))
    assert storage.read_json(storage.state_dir() / "desktop.json")["icon_files"]
    desktop.uninstall()
    assert not (storage.state_dir() / "desktop.json").exists()
