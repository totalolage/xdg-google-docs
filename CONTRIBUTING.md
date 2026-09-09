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

CI installs `.[dev]` and runs these checks on Python 3.11, 3.13, and 3.14. Tests must not need real OAuth credentials, a network connection to Google, a graphical session, or changes to the developer's actual MIME defaults. Use temporary HOME/XDG directories and mocked external tools/services. Building distributions may fetch build dependencies.

## Design Expectations

- Preserve cloud-copy semantics: no silent overwrite of remote edits and no suggestion that browser edits sync back to local files.
- Keep reuse keyed by content, source MIME, and mode, with account/client isolation and remote validation. Do not claim distributed uniqueness from a local lock or Drive property search.
- Keep authorization explicit in the CLI, use `drive.file`, and do not introduce public sharing or a broader scope without a documented need and review.
- Keep desktop installation per-user and CSV opt-in. Restore only still-owned defaults, preserve later user choices, and retain recovery metadata after failures.
- Never commit client JSON, tokens, document contents, private Drive URLs, or copied user state. Use synthetic fixtures and redact issue reports.
- Add focused regression tests for changed behavior. Credit ideas and respect upstream licenses if introducing third-party material; the existing implementation was written independently, not copied from the projects in [research notes](docs/research.md).

## Manual Validation

Live authenticated testing awaits user credentials and consent; it is not part of credential-free CI and is not currently claimed as completed. If you opt in, use disposable non-sensitive files and an account/project you control. Follow the [README OAuth setup](README.md#authorize-your-account), and record Python version, desktop environment, browser, formats, and observed results without publishing secrets.

1. Authenticate with a downloaded Desktop OAuth client; verify the account using `status --check`. Check `--no-browser` on the same machine and confirm expired/revoked credentials produce a useful error.
2. Open representative documents in default conversion mode and with `--keep-office`. Inspect fidelity, not just HTTP success. Confirm `--print-url` suppresses browser launching but still performs the upload/reuse operation.
3. Reopen identical bytes, then rename the local file without changing its source MIME. Confirm the same Drive file and existing title are reused.
4. Edit the cloud document, reopen the unchanged local file, and confirm remote edits survive. Change local bytes and confirm a separate copy is created; verify `--new` deliberately creates another copy.
5. Test a missing/trashed cached file and an index miss with an existing app property. Do not treat success as proof of global deduplication; document duplicate behavior under separate clients or index lag if tested.
6. Confirm an arbitrary manually uploaded matching file is not discovered. Check upload-account/browser-account mismatch without changing sharing permissions to work around it.
7. In a disposable Linux user session, test Open With installation, default installation, CSV opt-in, reinstall, and uninstall. Confirm previous owned defaults return and later user-selected defaults survive. Test failure recovery without touching a real user's configuration.
8. Confirm `logout` removes only the local token and `uninstall` leaves credentials and cloud documents. Revoke the test grant and delete disposable cloud files separately when finished.

Report which steps were actually performed. Mocked API tests do not verify real conversion, OAuth policy, Drive indexing, or desktop-environment behavior.
