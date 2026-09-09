# xdg-google-docs

Open local office documents in Google Docs, Sheets, and Slides from Linux, from the command line or your file manager's Open With menu.

**This uploads a cloud copy to Google Drive. It is not sync.** Browser edits stay in Drive and are never written back to the local file. Opening an associated file can upload sensitive contents without another confirmation. Read [SECURITY.md](SECURITY.md) before enabling desktop defaults.

Repository: [totalolage/xdg-google-docs](https://github.com/totalolage/xdg-google-docs). Licensed under [MIT](LICENSE).

[Privacy Policy](PRIVACY.md) describes Google API data access, use, storage, sharing, and deletion.
[Terms of Service](TERMS.md) describe user responsibilities, third-party services, and warranty limitations.

## Install

Requires Python 3.11 or newer, Linux, and a browser. Desktop integration needs `xdg-mime` and browser launching needs `xdg-open` (usually provided by `xdg-utils`). Default-handler installation also needs `update-mime-database` (from `shared-mime-info`) for document icons. `update-desktop-database`, `gtk-update-icon-cache`, and `notify-send` are optional; `update-desktop-database` is recommended for Open With discovery.

```sh
git clone https://github.com/totalolage/xdg-google-docs.git
cd xdg-google-docs
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
xdg-google-docs --help
```

Keep the repository and virtual environment at a stable location: desktop installation records the absolute executable path. No root privileges are needed. Activate the environment again in new terminals to use these commands.

On desktops using the generic `xdg-open` fallback (including some window-manager sessions), use an installation path without spaces or shell-special characters. That upstream launcher does not correctly parse quoted executable paths; standards-compliant launchers such as GIO do.

## Releases And Upgrades

For versioned downloads, use [GitHub Releases](https://github.com/totalolage/xdg-google-docs/releases). Each release includes a wheel, source archive, and `SHA256SUMS`. Releases are published automatically after a new package version merges to `main` and CI passes. Merges retaining an already released version produce CI build artifacts, not a replacement release.

To upgrade an existing virtual-environment installation, download the new wheel and checksum file, verify the wheel against its entry in `SHA256SUMS`, then run the environment's `python -m pip install --upgrade /path/to/downloaded.whl` followed by `xdg-google-docs install` to refresh desktop assets. Reuse `--include-csv` or `--no-defaults` if that is your chosen installation mode. Configuration and Google credentials remain outside the installed package.

## Authorize Your Account

There is no bundled OAuth client. Use your own Google Cloud project:

1. Create or select a project in the [Google Cloud console](https://console.cloud.google.com/).
2. Enable the **Google Drive API** in that same project. Separate Docs, Sheets, and Slides APIs are not required for this upload-and-open workflow.
3. Configure the OAuth consent screen in Google Auth Platform, including the required branding and contact details. For a personal Google account, choose **External** under Audience; while in **Testing**, add your Google account as a test user.
4. Under **Data Access**, add only `https://www.googleapis.com/auth/drive.file`. This is per-file access, not full-Drive access.
5. Under **Clients**, create an OAuth client with application type **Desktop app** and download its JSON. Do not use a Web application or service-account credential.
6. Run the following command with the downloaded file, then complete Google's sign-in and consent in your browser:

```sh
xdg-google-docs auth --client "$HOME/Downloads/client_secret.json"
xdg-google-docs status --check
```

Authentication is explicitly initiated from the CLI. It uses Google's installed-app OAuth flow, PKCE, and a temporary `127.0.0.1` loopback listener on an available port. Browser consent is unavoidable; there is no custom login GUI and no password collection by this app. Desktop file opening does not initiate authentication.

To print the authorization URL rather than launch the browser:

```sh
xdg-google-docs auth --no-browser
```

Supply `--client` as well on first use. The browser must be able to reach the loopback listener on the **same machine running the CLI**; this is not a remote/headless authorization flow. Complete consent within five minutes. Subsequent `auth` calls reuse the stored client JSON.

**Testing-mode expiry:** for an External OAuth app in Testing, refresh tokens for this Drive scope expire after seven days. You can reauthorize, or move the consent app to **Production** for personal use where Google's current rules allow it. Production does not guarantee permanent tokens or exempt an app from applicable verification and organization policies. See Google's [token expiration rules](https://developers.google.com/identity/protocols/oauth2#expiration) and [native-app OAuth guide](https://developers.google.com/identity/protocols/oauth2/native-app).

The account used by the CLI may differ from the account currently active in your browser. Use `status --check` to see the authenticated upload account; switch browser accounts if the editor reports that you lack access. Changing the browser account alone does not change the upload account. Run `auth` again to authorize a different account.

## Open Documents

```sh
xdg-google-docs open report.docx budget.xlsx slides.pptx
xdg-google-docs open --keep-office report.docx
xdg-google-docs open --new report.docx
xdg-google-docs open --print-url report.docx
```

By default, uploads convert to native Google Docs, Sheets, or Slides. `--keep-office` uploads the original format instead; Google's browser editing/preview support still varies by format. Conversion can be lossy, including formatting, formulas, macros, embedded objects, and other unsupported features. Keep your originals and check important documents.

| Target | Supported local extensions |
| --- | --- |
| Google Docs | `.doc`, `.docx`, `.odt`, `.rtf` |
| Google Sheets | `.xls`, `.xlsx`, `.ods`, `.csv` |
| Google Slides | `.ppt`, `.pptx`, `.odp` |

The app checks Google's currently advertised import support before conversion. Empty files and unsupported extensions are rejected. `--print-url` still uploads or looks up the cloud copy; it only suppresses browser launching. Use `--` before filenames starting with a dash.

Set the default for both CLI and desktop opening:

```sh
xdg-google-docs config office
xdg-google-docs config convert
```

`open --convert` overrides an `office` default; `open --keep-office` overrides a `convert` default.

### Cloud-Copy Identity

- A snapshot of the local bytes is hashed with SHA-256. The reuse identity includes that content hash, the source MIME type, and the conversion mode/target MIME type, not the local pathname.
- A local index is partitioned by Google account and OAuth client. Cached file IDs are checked remotely before reuse; missing or trashed files are not reused.
- On an index miss, the app searches Drive for its private `appProperties` marker, `xdgDocsV1`. This can recover an app-created copy after local index loss, within the same account and app's visibility.
- Identical bytes renamed or moved, with the same source MIME and mode, reopen the existing cloud copy **with its existing title**. Reopening does not rename it.
- Changed local bytes produce a new identity and normally a new cloud copy, rather than updating the previous copy. If those bytes already have a matching app-created copy, that copy is reused.
- Remote edits are preserved: reopening unchanged local bytes opens the existing, possibly edited cloud document. Nothing is downloaded or overwritten. `--new` deliberately creates another copy and makes it the local index's current match.
- `drive.file` covers app-created files and files explicitly granted to an app. This app has no picker/import-existing flow: it cannot discover arbitrary existing manually uploaded files, even if their names or bytes match. Deduplication concerns this app's marked copies, not your whole Drive.
- One local process lock serializes operations sharing the state directory. It is not a distributed lock. Other machines, separate state directories, Drive search-index lag, or an interrupted upload with an uncertain result can still produce duplicates. There is no exactly-once or global deduplication guarantee.

## Desktop Integration

Authenticate first, then choose one installation mode:

```sh
xdg-google-docs install --no-defaults
```

This adds a per-user **Google Docs** Open With entry without replacing MIME defaults. To make it the default handler for supported office formats instead:

```sh
xdg-google-docs install
```

**Double-clicking an associated file now uploads/reopens a cloud copy.** CSV is always advertised in Open With, but changing its default handler and document icon requires `install --include-csv`. Your existing CSV default remains unchanged otherwise. Generic text and ZIP associations are not claimed.

Installation includes original blue document, green spreadsheet, and amber presentation SVG icons. The launcher has an app icon, and default-handler installation adds per-user MIME icon mappings for the associated formats. These mappings apply to all files of those types, not just uploaded files. `install --no-defaults` installs the app icons without adding file-type icon mappings. The artwork is distributed under the project's MIT license and is not an official Google logo.

Icons are installed in `${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/mimetypes/` and mappings in `mime/packages/xdg-google-docs.xml` beneath the same data root. System theme files and unrelated MIME definitions are not replaced. Re-run `install` after upgrading to add new assets; original association backups are retained. Uninstall removes tracked icon assets and mappings and refreshes caches, but refuses to delete user-modified assets. File managers may need a refresh or reopening to see updated icons; thumbnails and per-file custom icons can take precedence.

The entry is stored at `${XDG_DATA_HOME:-$HOME/.local/share}/applications/xdg-google-docs.desktop`. Installation records previous per-user associations and retains the original backups across reinstalls.

```sh
xdg-google-docs uninstall
```

Uninstall restores defaults only while they are still owned by this app, removes its associations without replacing later user choices, and removes its tracked desktop entry. A modified entry is left intact and reported rather than silently deleted. Recovery metadata is retained on failure so uninstall can be retried. `install --no-defaults` does not undo defaults from an earlier installation; use `uninstall` first if that is your intention.

Uninstall keeps credentials, settings, the document index, and cloud documents. Run it **before** removing the virtual environment or desktop recovery metadata.

## Local Data And Removal

| Default location | Contents |
| --- | --- |
| `~/.config/xdg-google-docs/` | `client.json`, `token.json`, `settings.json` |
| `~/.local/state/xdg-google-docs/` | `documents.json`, `desktop.json`, `operation.lock`, optional `last-error.json` |

`XDG_CONFIG_HOME` and `XDG_STATE_HOME` override the respective roots and must be absolute paths. App configuration/state directories use mode `0700`; newly written JSON files, including the **plaintext token**, use mode `0600`. There is **no keyring integration or encryption at rest**. These permissions do not protect against your own account, root, malware, or exposed backups.

```sh
xdg-google-docs status
xdg-google-docs logout
```

`status` reports local setup without validating the token; `status --check` contacts Google. `logout` deletes the local token only. Revoke the app grant separately in your [Google Account connections](https://myaccount.google.com/connections). Cloud documents must be deleted in Drive if no longer wanted. After uninstalling, you may remove the app's configuration/state directories and virtual environment if you want to remove all local setup.

## Limitations And Validation

This is an online cloud-copy opener, not a filesystem, backup tool, sync client, or fidelity-preserving converter. Network access, Drive quota, Google's import limits, account policy, and browser support apply. The app does not create public sharing permissions; an editor URL is not a public-share link.

The maintainer has confirmed successful authenticated upload and repeat-open behavior on the target Linux machine. Conversion fidelity across all formats and cross-machine reuse remain unverified; offline tests and CI cannot establish those properties. See [CONTRIBUTING.md](CONTRIBUTING.md) for checks and a manual validation checklist, and [research notes](docs/research.md) for alternatives and design sources.
