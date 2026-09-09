# Research And Design Notes

## Goal

Provide a small Linux XDG integration for opening a local office document as a Google Drive cloud copy. This is intentionally narrower than synchronization or a general Google Workspace CLI: authenticate explicitly once, upload/reopen from the CLI or file manager, and let Google's browser editor handle editing.

## Related Projects

| Project | License | Relevant approach | Fit for this project |
| --- | --- | --- | --- |
| [goodoc](https://github.com/djachenko/goodoc) | [MIT](https://github.com/djachenko/goodoc/blob/master/LICENSE) | Office uploads with native conversion, browser opening, and a macOS Finder Quick Action. | Close workflow inspiration, but its macOS integration is not Linux XDG MIME registration. |
| [gogcli](https://github.com/openclaw/gogcli) | [MIT](https://github.com/openclaw/gogcli/blob/main/LICENSE) | Broad, scriptable Google Workspace CLI covering Drive and many other services. | A capable alternative foundation, but this focused desktop workflow would still require a wrapper for associations, copy identity, and lifecycle behavior. |
| [rclone](https://github.com/rclone/rclone) | [MIT](https://github.com/rclone/rclone/blob/master/COPYING) | Mature cloud storage transfer/synchronization tooling with a [Google Drive backend](https://rclone.org/drive/). | Useful for storage automation, but a focused upload-and-open workflow still needs integration. Do not use `rclone link` as a shortcut for an authenticated editor URL: it creates/retrieves public sharing links. |
| [OpenWithGoogleDocs](https://github.com/FKLC/OpenWithGoogleDocs) | [MIT](https://github.com/FKLC/OpenWithGoogleDocs/blob/main/LICENSE.txt) | Archived, Windows-oriented document opener; MD5-based reopen identification is relevant inspiration. | The reopen concept is useful, but Windows integration and its identity design are not adopted as implementation. |

**Attribution:** goodoc's upload-and-open workflow and FKLC/OpenWithGoogleDocs' content-based reopening explicitly inspired this design. gogcli and rclone informed the alternatives comparison. We wrote this project's code independently; no source code was copied or borrowed from these projects. These are inspiration/research credits, not claims of shared implementation, affiliation, or endorsement. This project's own license is [MIT](../LICENSE); third-party dependencies retain their own licenses.

## API Decisions

### Upload And Conversion

The [Drive upload guide](https://developers.google.com/workspace/drive/api/guides/manage-uploads) documents media uploads and conversion by setting a Google Workspace target MIME type. The implementation uses a resumable upload of a temporary snapshot, defaults to native conversion, and checks the account's `importFormats` before creating a converted file. `--keep-office` instead keeps the source MIME type. Google's supported conversions and fidelity are external constraints, not guarantees of this wrapper.

The snapshot ensures the hash describes the bytes uploaded; metadata checks reject a source that visibly changes while being read. Conversion may discard or change formatting, macros, formulas, and embedded content. Neither conversion nor keeping an Office file implements local write-back.

### Scope And Reuse

Google's [scope guidance](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) recommends the per-file, non-sensitive `drive.file` scope for suitable apps. It permits access to app-created or explicitly user-authorized files, not arbitrary existing files throughout Drive. This implementation has no Google Picker or other existing-file authorization flow, so it cannot match arbitrary manually uploaded documents.

The [custom properties guide](https://developers.google.com/workspace/drive/api/guides/properties) and [file search guide](https://developers.google.com/workspace/drive/api/guides/search-files) document private `appProperties` and property queries. The app stores an `xdgDocsV1` identity derived from SHA-256 content hash, source MIME, and conversion mode. A local index is scoped to the Google account and OAuth client, with remote existence/trash checks before reuse and a property search on index miss.

Identity is not a pathname or a comparison with current remote content. The same bytes under a new name reopen the old cloud title. Changed local bytes normally create another copy. Existing remote edits remain untouched. This avoids destructive overwrite but is not sync, version reconciliation, or whole-Drive deduplication.

A single local process lock only coordinates clients sharing local state. Drive property search is not an atomic create-if-absent operation or a uniqueness constraint. Distributed callers, search-index lag, and ambiguous upload failures can create duplicates. Losing local state may be recoverable through properties, but recovery and exactly-once creation are not guaranteed.

### Authentication And Privacy

Google's [OAuth for native apps](https://developers.google.com/identity/protocols/oauth2/native-app) describes browser authorization, loopback redirects, and PKCE. This project uses a downloaded Desktop OAuth client, a loopback listener, and an automatically generated PKCE verifier. It has no custom authentication GUI. `--no-browser` prints the URL, but the browser still needs access to the originating machine's loopback listener; it does not bypass consent.

The [OAuth expiration documentation](https://developers.google.com/identity/protocols/oauth2#expiration) describes the seven-day refresh-token lifetime for External apps in Testing when requesting scopes such as `drive.file`. Production status for personal use can remove that testing-specific limit where Google's policies permit, but does not eliminate revocation, other expiration causes, or verification requirements.

Tokens are plaintext files written with mode `0600` inside an app directory with mode `0700`; there is no keyring. File contents, titles, and the derived identity are sent to Google Drive. Full local paths are not intentionally included in upload metadata. The app opens Drive's authenticated `webViewLink` and does not request public sharing. In contrast, [`rclone link`](https://rclone.org/commands/rclone_link/) is explicitly a public-link operation and is unsuitable as a privacy-preserving substitute.

## Validation Boundary

Documentation review and offline tests do not establish live Google behavior. The maintainer subsequently confirmed successful authenticated upload and repeat-open behavior on the target Linux machine. Conversion fidelity across all formats and cross-machine deduplication remain unverified. Use the [manual checklist](../CONTRIBUTING.md#manual-validation) with disposable, non-sensitive documents and record the actual environment and results.
