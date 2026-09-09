"""Build checksums locally; publish only from a validated main-branch Actions job."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path


def gh(*args):
    return subprocess.run(
        ["gh", *args], check=True, stdout=subprocess.PIPE, text=True, timeout=120
    ).stdout


def main(publish=False):
    version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise ValueError("Releases require a stable MAJOR.MINOR.PATCH project version")
    tag = f"v{version}"
    assets = [
        Path(f"dist/xdg_google_docs-{version}-py3-none-any.whl"),
        Path(f"dist/xdg_google_docs-{version}.tar.gz"),
    ]
    # Read every expected artifact before changing files or contacting GitHub.
    checksums = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in assets
    )
    sums = Path("dist/SHA256SUMS")
    sums.write_text(checksums)
    assets.append(sums)
    if not publish:
        return
    if os.environ.get("GITHUB_REF") != "refs/heads/main" or os.environ.get(
        "GITHUB_EVENT_NAME"
    ) not in {"push", "workflow_dispatch"}:
        raise ValueError("Publishing is allowed only on main push or manual main runs")
    repo = os.environ["GITHUB_REPOSITORY"]
    sha = os.environ["GITHUB_SHA"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("GITHUB_SHA must identify the exact tested commit")
    pages = json.loads(gh("api", f"repos/{repo}/releases", "--paginate", "--slurp"))
    releases = [release for page in pages for release in page]
    existing = next((release for release in releases if release["tag_name"] == tag), None)
    if existing and not existing["draft"]:
        print(f"{tag} is already published; leaving its tag and assets unchanged.")
        return
    current_version = tuple(map(int, version.split(".")))
    for release in releases:
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", release["tag_name"])
        if not release["draft"] and match and tuple(map(int, match.groups())) > current_version:
            raise ValueError("Refusing to publish a version older than an existing release")
    if existing and existing["target_commitish"] != sha:
        raise ValueError("Draft belongs to another commit; rerun its workflow or bump the version")
    refs = json.loads(gh("api", f"repos/{repo}/git/matching-refs/tags/{tag}"))
    ref = next((ref for ref in refs if ref["ref"] == f"refs/tags/{tag}"), None)
    if ref:
        if ref["object"].get("type") != "commit" or ref["object"].get("sha") != sha:
            raise ValueError(
                "Release tag does not point directly to the tested commit; refusing to move it"
            )
    else:
        gh(
            "api",
            "--method",
            "POST",
            f"repos/{repo}/git/refs",
            "-f",
            f"ref=refs/tags/{tag}",
            "-f",
            f"sha={sha}",
        )
    if not existing:
        gh(
            "release",
            "create",
            tag,
            "--repo",
            repo,
            "--verify-tag",
            "--target",
            sha,
            "--draft",
            "--generate-notes",
            "--title",
            tag,
            "--notes",
            "Linux CLI and desktop handler for Google Docs, Sheets and Slides. "
            "Download the wheel or source archive below; SHA256SUMS covers both. "
            "See the README for installation, OAuth setup, upgrades and cloud-copy limitations. "
            "This pre-1.0 project is not a synchronization client.",
        )
    # Only a draft for this exact commit can be repaired after an interrupted upload.
    gh("release", "upload", tag, *(str(path) for path in assets), "--repo", repo, "--clobber")
    gh("release", "edit", tag, "--repo", repo, "--draft=false", "--latest", "--verify-tag")
    print(f"Published https://github.com/{repo}/releases/tag/{tag}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true")
    main(parser.parse_args().publish)
