# Contributing

Contributions to [totalolage/xdg-google-docs](https://github.com/totalolage/xdg-google-docs) are welcome under the project's [MIT license](LICENSE). Keep changes focused and describe user-visible behavior and validation in your pull request. Report vulnerabilities according to [SECURITY.md](SECURITY.md), not with public credentials or documents.

## Development Setup

Use Linux and Python 3.11 or newer. From the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest
python -m build
```

CI installs `.[dev]` and runs these checks on Python 3.11, 3.13, and 3.14. Tests must not need real OAuth credentials, a network connection to Google, a graphical session, a real system keyring, or changes to the developer's actual MIME defaults. Use temporary HOME/XDG directories and mocked external tools/services, including Secret Service. Building distributions may fetch build dependencies.

Live credential operations in v0.2.0 require a session D-Bus and a Secret Service provider, such as GNOME Keyring (already present on the target machine). The package installs Python keyring dependencies, not an app daemon. Any unlock dialog belongs to the system keyring; do not add a custom app keyring GUI.

## Design Expectations

- Preserve cloud-copy semantics: no silent overwrite of remote edits and no suggestion that browser edits sync back to local files.
- Keep reuse keyed by content, source MIME, and mode, with account/client isolation and remote validation. Do not claim distributed uniqueness from a local lock or Drive property search.
- Keep authorization explicit in the CLI, use `drive.file`, and do not introduce public sharing or a broader scope without a documented need and review.
- Keep `keyring.backends.SecretService.Keyring` explicit, with no plaintext fallback. Store OAuth client configuration and access/refresh tokens in one bundle under service `xdg-google-docs`, account/profile key `oauth-SHA256(resolved app config directory)`. Different resolved config directories must isolate profiles; settings, cache/index, errors, and desktop backups remain filesystem data.
- Preserve verified migration from v0.1.0: after upgrading to v0.2.0, the next `status`, `auth`, `open`, or `logout` must store and read back the whole bundle before unlinking app-owned legacy `client.json` and `token.json`. Failed verification or inaccessible/locked keyring storage must leave legacy files untouched; differing existing keyring and legacy credentials must stop migration without deletion. Do not alter the original user-provided client download or require Google reauthorization just for migration.
- Do not promise secure erasure or unconditional keyring encryption. OS settings govern encryption/access, an empty-password keyring may lack encryption, and unlocked-session same-user malware is not covered by a protection guarantee.
- Keep desktop installation per-user and CSV opt-in. Restore only still-owned defaults, preserve later user choices, and retain recovery metadata after failures.
- Never commit client JSON, tokens, document contents, private Drive URLs, or copied user state. Use synthetic fixtures and redact issue reports.
- Add focused regression tests for changed behavior. Credit ideas and respect upstream licenses if introducing third-party material; the existing implementation was written independently, not copied from the projects in [research notes](docs/research.md).

## Releases

Every push to `main` (including a merged PR) runs the full Python-version CI matrix. After it succeeds, a separate job builds and checks a wheel and source archive, generates `SHA256SUMS`, and retains the distributions as a GitHub Actions artifact for 30 days. Pull requests and other branches cannot publish releases.

Publishing is **version-gated**: if `project.version` in `pyproject.toml` has no published release yet, the job creates `v<version>` at the exact tested commit and publishes a GitHub release with generated notes and all three assets. The current package version is `0.2.0`; the initial release was `v0.1.0`. To publish another release, include a version bump in a PR, for example `0.2.1` for a fix or `0.3.0` for a feature, and merge it. Merges without a version bump still build artifacts but do not alter the published release. Only stable `MAJOR.MINOR.PATCH` versions are supported; pre-1.0 versions are not automatically marked as GitHub prereleases. Nothing is published to PyPI.

The publishing job has `contents: write` permission; test and build jobs remain read-only. It downloads its own run's validated distributions by artifact ID. Publishing uses the built-in `GITHUB_TOKEN`, so no personal access token or Google credentials are needed. The checkout does not persist Git credentials in the build or release jobs. Publishing jobs are serialized; GitHub can replace an older pending publisher if several runs are queued, so allow a version's release to finish before merging another version bump. Build and artifact-retention jobs are not serialized and are unaffected by this publishing queue.

Published versions are never overwritten by automation. Assets are uploaded to a draft before publication. For a transient failure, rerun the failed workflow at the **same commit** to resume its draft or tag; a draft or tag associated with a different commit is rejected rather than moved. A new version older than an existing published release is rejected. Use the CI workflow's manual dispatch on `main` to retry when it still points at the intended release commit.

Before merging release changes, run the normal checks and `python .github/scripts/release.py` after `python -m build` to generate local checksums without contacting GitHub. Release logic is covered by mocked tests. Review generated release notes for accuracy and avoid including private data in commit or PR titles.

## Manual Validation

The maintainer has confirmed a successful authenticated upload and repeat-open cycle on the target Linux machine. This does not establish conversion fidelity across all formats, cross-machine reuse, or completion of every check below. Authenticated tests remain outside credential-free CI. If you opt in, use disposable non-sensitive files and an account/project you control. Follow the [README OAuth setup](README.md#authorize-your-account), and record Python version, desktop environment, browser, formats, and observed results without publishing secrets.

1. Authenticate with a downloaded Desktop OAuth client; verify the account using `status --check`. Check `--no-browser` on the same machine and confirm expired/revoked credentials produce a useful error.
2. Open representative documents in default conversion mode and with `--keep-office`. Inspect fidelity, not just HTTP success. Confirm `--print-url` suppresses browser launching but still performs the upload/reuse operation.
3. Reopen identical bytes, then rename the local file without changing its source MIME. Confirm the same Drive file and existing title are reused.
4. Edit the cloud document, reopen the unchanged local file, and confirm remote edits survive. Change local bytes and confirm a separate copy is created; verify `--new` deliberately creates another copy.
5. Test a missing/trashed cached file and an index miss with an existing app property. Do not treat success as proof of global deduplication; document duplicate behavior under separate clients or index lag if tested.
6. Confirm an arbitrary manually uploaded matching file is not discovered. Check upload-account/browser-account mismatch without changing sharing permissions to work around it.
7. In a disposable Linux user session, test Open With installation, default installation, CSV opt-in, reinstall, and uninstall. Confirm previous owned defaults return and later user-selected defaults survive. Test failure recovery without touching a real user's configuration.
8. In a disposable profile/session, confirm client configuration and tokens share one Secret Service entry, changing the resolved `XDG_CONFIG_HOME` selects a different entry, and unavailable/locked keyring errors never produce plaintext fallback files. Check any system unlock dialog without assuming all keyring configurations provide encryption.
9. With disposable legacy credentials, check migration after upgrading from v0.1.0 to v0.2.0 through `status`, `auth`, `open`, and `logout`: whole-bundle write/readback verification precedes legacy unlinking, failures retain legacy files, and conflicts stop without deletion. Confirm the original client download is untouched and migration alone needs no repeat Google authorization.
10. Confirm `logout` removes token data but preserves the keyring client configuration, and `uninstall` leaves keyring credentials and cloud documents. Check full-entry removal through the system Passwords and Keys (Seahorse) GUI. Revoke the test grant and delete disposable cloud files and remaining local data separately when finished; do not describe deletion as secure erasure.

Report which steps were actually performed. Mocked API tests do not verify real conversion, OAuth policy, Drive indexing, or desktop-environment behavior.
