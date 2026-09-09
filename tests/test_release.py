import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

SPEC = importlib.util.spec_from_file_location(
    "release", Path(__file__).parents[1] / ".github/scripts/release.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
SHA = "a" * 40


def test_github_errors_remain_visible(monkeypatch):
    command = Mock(return_value=Mock(stdout="response"))
    monkeypatch.setattr(release.subprocess, "run", command)
    assert release.gh("api", "test") == "response"
    assert command.call_args.kwargs["stdout"] == subprocess.PIPE
    assert "stderr" not in command.call_args.kwargs
    assert "capture_output" not in command.call_args.kwargs


@pytest.fixture
def build(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/test")
    monkeypatch.setenv("GITHUB_SHA", SHA)
    Path("pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    Path("dist").mkdir()
    for name in ("xdg_google_docs-0.1.0-py3-none-any.whl", "xdg_google_docs-0.1.0.tar.gz"):
        Path("dist", name).write_bytes(name.encode())
    command = Mock(side_effect=["[[]]", "[]", "", "", "", ""])
    monkeypatch.setattr(release, "gh", command)
    return command


def test_checksums_without_network(build):
    release.main()
    lines = Path("dist/SHA256SUMS").read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        digest, filename = line.split("  ")
        assert digest == hashlib.sha256(Path("dist", filename).read_bytes()).hexdigest()
    build.assert_not_called()


def test_new_release_uses_exact_sha_and_publishes_after_upload(build):
    release.main(publish=True)
    calls = [call.args for call in build.call_args_list]
    assert calls[2] == (
        "api",
        "--method",
        "POST",
        "repos/example/test/git/refs",
        "-f",
        "ref=refs/tags/v0.1.0",
        "-f",
        f"sha={SHA}",
    )
    assert calls[3][:3] == ("release", "create", "v0.1.0")
    assert "--draft" in calls[3]
    assert SHA in calls[3]
    assert calls[4][:3] == ("release", "upload", "v0.1.0")
    assert "dist/SHA256SUMS" in calls[4]
    assert "--clobber" in calls[4]
    assert calls[5][:3] == ("release", "edit", "v0.1.0")
    assert "--draft=false" in calls[5]


def test_published_version_is_immutable(build):
    build.side_effect = [json.dumps([[{"tag_name": "v0.1.0", "draft": False}]])]
    release.main(publish=True)
    assert build.call_count == 1


@pytest.mark.parametrize("reason", ["newer", "foreign-draft", "wrong-tag", "annotated-tag"])
def test_conflicts_fail_without_writes(build, reason):
    releases = []
    refs = []
    if reason == "newer":
        releases = [{"tag_name": "v0.2.0", "draft": False}]
    elif reason == "foreign-draft":
        releases = [{"tag_name": "v0.1.0", "draft": True, "target_commitish": "b" * 40}]
    else:
        refs = [
            {
                "ref": "refs/tags/v0.1.0",
                "object": {
                    "type": "tag" if reason == "annotated-tag" else "commit",
                    "sha": "b" * 40,
                },
            }
        ]
    build.side_effect = [json.dumps([releases]), json.dumps(refs)]
    with pytest.raises(ValueError):
        release.main(publish=True)
    assert build.call_count <= 2


def test_same_commit_draft_is_resumable(build):
    build.side_effect = [
        json.dumps([[{"tag_name": "v0.1.0", "draft": True, "target_commitish": SHA}]]),
        json.dumps([{"ref": "refs/tags/v0.1.0", "object": {"type": "commit", "sha": SHA}}]),
        "",
        "",
    ]
    release.main(publish=True)
    assert build.call_args_list[2].args[:2] == ("release", "upload")
    assert build.call_args_list[3].args[:2] == ("release", "edit")


def test_api_failure_is_not_treated_as_missing_release(build):
    build.side_effect = subprocess.CalledProcessError(1, "gh")
    with pytest.raises(subprocess.CalledProcessError):
        release.main(publish=True)
    assert build.call_count == 1


def test_upload_failure_leaves_draft_unpublished(build):
    build.side_effect = ["[[]]", "[]", "", "", subprocess.CalledProcessError(1, "gh")]
    with pytest.raises(subprocess.CalledProcessError):
        release.main(publish=True)
    assert all(call.args[:2] != ("release", "edit") for call in build.call_args_list)


@pytest.mark.parametrize("version", ["0.1.0rc1", "01.0.0", "1.2", "invalid"])
def test_invalid_versions_do_not_contact_github(build, version):
    Path("pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    with pytest.raises(ValueError):
        release.main(publish=True)
    build.assert_not_called()


def test_missing_artifact_does_not_contact_github(build):
    Path("dist/xdg_google_docs-0.1.0.tar.gz").unlink()
    with pytest.raises(FileNotFoundError):
        release.main(publish=True)
    assert not Path("dist/SHA256SUMS").exists()
    build.assert_not_called()


@pytest.mark.parametrize(
    "variable,value",
    [
        ("GITHUB_REF", "refs/heads/feature"),
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_SHA", "main"),
    ],
)
def test_untrusted_context_cannot_publish(build, monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError):
        release.main(publish=True)
    build.assert_not_called()
