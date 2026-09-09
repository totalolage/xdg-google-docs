# Security And Privacy

## Upload Boundary

Opening a document uploads its contents to Google Drive unless an existing app-created copy is reused. Native conversion is the default and can be lossy. `--keep-office` still uploads the original file; `--print-url` still performs upload/reuse. Once desktop defaults are installed, double-clicking associated files can send sensitive documents to Google without a further upload confirmation.

Only open files you are authorized to send to that Google account and service. Organization policy, Google processing/retention, Drive permissions, browser sessions, and backups remain relevant. This is not offline editing, synchronization, or a local-only viewer. Local originals are not updated with remote edits.

The app uses only `https://www.googleapis.com/auth/drive.file`. That scope allows app-created files and explicitly authorized files, not arbitrary existing manually uploaded documents. It is still a write-capable scope: theft of the token can endanger files available to the app. The implementation does not create public sharing permissions and uses an authenticated Google editor URL rather than a public-share operation. Do not use `rclone link` as a substitute; that command creates/retrieves public links.

## Credentials And Local State

- Authorization uses the user's downloaded Desktop OAuth client, Google's browser consent flow, PKCE, and a temporary loopback listener on `127.0.0.1`. There is no custom login GUI. `auth --no-browser` prints the URL but still requires the browser to reach the same machine's loopback callback.
- Refresh/access tokens are stored **in plaintext**, normally at `~/.config/xdg-google-docs/token.json`. There is **no keyring integration or encryption at rest**. Newly written JSON files use mode `0600`; app configuration and state directories use mode `0700`.
- Same-user processes, root, malware, and backups may still read these files. Protect the downloaded client JSON too; permissions applied to the app's stored copy do not secure the original download. Desktop OAuth client secrets are not a substitute for protecting refresh tokens.
- The app also stores settings, a content-derived identity-to-Drive-ID index, desktop association recovery metadata, and potentially the latest desktop error message. Treat these as private: errors can contain filenames/paths and the index contains Drive IDs and content-derived identifiers.
- A temporary local snapshot holds document bytes while hashing/uploading. This is not secure deletion or an encrypted temporary-storage guarantee; use appropriate disk encryption and host security for your threat model.
- Upload metadata includes a title and a derived content/MIME/mode identifier in private Drive `appProperties`, not the full local path. Private properties are access-controlled metadata, not encrypted secrets.
- The Google account authorized in the CLI can differ from the browser account. Confirm it with `status --check` before uploading sensitive material; switching browser accounts does not change the upload account.

The app validates editor URLs before launching them, but that is not a guarantee about document content or Google's editor. Do not publish tokens, authorization URLs/codes, client JSON, private document links, local state, or unredacted error output in issues or logs.

## Reuse Is Not An Integrity Guarantee

Content-hash reuse identifies the original local upload bytes together with source MIME and mode, not the current remote contents. Remote edits are intentionally preserved and not checked against the local hash. Renaming unchanged local bytes reopens the existing cloud title; changed local bytes normally create a new copy.

The local process lock does not coordinate separate machines or state directories. Drive property-search index lag and uncertain upload outcomes can produce duplicates. Neither the index nor `appProperties` is a distributed uniqueness mechanism, backup system, or proof of remote document integrity.

## Revocation And Removal

Run `xdg-google-docs logout` to delete the local token. This does **not** revoke Google's grant, delete cloud documents, or remove other copies/backups of the token. Revoke access through [Google Account connections](https://myaccount.google.com/connections) if a token may have leaked. Delete unwanted cloud documents in Drive separately.

`xdg-google-docs uninstall` removes owned desktop integration and restores still-owned defaults, but keeps credentials and cloud documents. Run uninstall before deleting the environment or its recovery state. See the [README](README.md#local-data-and-removal) for local paths and XDG overrides.

External OAuth apps in Testing have a seven-day refresh-token lifetime for the requested Drive scope. Production status where allowed for personal use avoids that testing-specific expiry, not other token revocation or policy limits. Never weaken scopes, sharing, or credential protection to work around authorization failures.

## Reporting A Vulnerability

Use the repository's [private vulnerability reporting page](https://github.com/totalolage/xdg-google-docs/security/advisories/new) if GitHub private reporting is enabled. If it is unavailable, open a minimal [issue](https://github.com/totalolage/xdg-google-docs/issues) asking the maintainer for a private reporting channel; do not include exploit details or sensitive data publicly. No response-time or supported-release guarantee is currently published.

Include the affected revision, environment, impact, and a minimal reproduction using synthetic data through the private channel. Never send real refresh tokens or private documents. Live authenticated end-to-end testing awaits user credentials and consent; offline checks are not a security audit or evidence of verified live Google behavior.
