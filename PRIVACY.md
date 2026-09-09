# Privacy Policy for xdg-google-docs

Effective date: September 9, 2026

This policy describes how **xdg-google-docs**, an open-source Linux application maintained by Filip Kalny ([totalolage](https://github.com/totalolage)), accesses, uses, stores, and shares information. It covers the application distributed through [its official repository](https://github.com/totalolage/xdg-google-docs), not independently modified versions or third-party services.

## Overview

xdg-google-docs runs on your computer. It opens local office documents in Google Docs, Sheets, or Slides by uploading a cloud copy to your Google Drive, or reopening a copy previously uploaded through the app. It does not operate a developer-hosted backend, collect telemetry, or send your documents or Google credentials to the maintainer.

**Opening a file with the app can upload its contents to Google.** After you install it as a default file handler, double-clicking an associated document can initiate that upload without a separate confirmation. The app is not a local-only viewer or a synchronization service. Browser edits remain in Google Drive and are not written back to your local file.

## Information Accessed and Its Purpose

| Information | How the app uses it |
| --- | --- |
| Documents you open, including their contents, filenames, and file types | Reads a temporary local snapshot, uploads the contents and a document title to Google Drive, and optionally converts the document to a native Google format. |
| A SHA-256-derived content and format identifier | Identifies a previously uploaded copy to avoid unnecessary duplicate uploads. The identifier is stored locally and as private application metadata on the Drive file. It is not used for advertising or tracking users across services. |
| Google Drive file IDs, titles, MIME types, trash status, and browser URLs | Finds and checks app-created copies and opens their Google browser URLs. Reopening does not overwrite remote document edits. |
| Google account email address and Drive permission identifier | Identifies the authorized upload account, displays the email address when you request an online status check, and separates the local document index by account and OAuth client. The app does not persist a separate email-address directory. |
| OAuth client configuration, access tokens, and refresh tokens | Authenticates requests to Google and renews access without asking you to sign in for every document. The app does not receive your Google password. |
| Local settings, file-association backups, and error details | Remembers your preferred upload mode, restores desktop associations when requested, and reports failures. Error details can include local filenames or paths. |

Full local document paths are not intentionally included in Google Drive upload metadata. Document titles, contents, file types, and the derived identifier are transmitted to Google. The app does not scan or upload your entire filesystem.

## Google Permissions and Authorization

The app requests only the Google OAuth scope `https://www.googleapis.com/auth/drive.file`. This permits access to files created by the app or explicitly made available to it, rather than unrestricted access to your entire Drive. The current app does not provide a picker for granting access to arbitrary existing Drive files.

You initiate authorization from the command line and sign in directly with Google in your browser. The app uses a temporary loopback callback on your computer and PKCE for the authorization flow. You can decline authorization or revoke it later.

xdg-google-docs' use and transfer of information received from Google APIs will adhere to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements. Google user data is used only to provide the document upload, conversion, reopening, and account-status features described here. The app does not use that data for advertising, sell it, or use it to develop, train, or improve generalized artificial intelligence or machine-learning models. The maintainer does not receive or review your Google user data through normal app operation.

## Sharing and Third-Party Services

The app sends documents and necessary API requests directly from your computer to Google over HTTPS. Google receives the information needed to provide its services, including normal connection information such as your IP address. Its handling of that information is governed by [Google's Privacy Policy](https://policies.google.com/privacy) and applicable Google account or organization terms.

The app does not create public sharing permissions or send your files to other users. Access to uploaded files is governed by Google Drive permissions and your account or organization policies. If you share a file through Google Drive, that sharing is managed by Google, not by this app.

The app opens document URLs in your configured browser. Your browser, extensions, operating system, and backup tools may retain their own history or copies under their settings. The project and this policy are hosted on GitHub; visits and information you voluntarily submit there are subject to [GitHub's Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement). The app itself does not send usage analytics to GitHub.

## Storage and Security

Version 0.2.0 stores OAuth client configuration and access/refresh tokens together in one system Secret Service keyring entry. It explicitly uses `keyring.backends.SecretService.Keyring`, with service `xdg-google-docs` and account/profile key `oauth-SHA256(resolved app config directory)`. Changing `XDG_CONFIG_HOME` to a different resolved configuration directory selects a different credential entry.

Settings and a credential-operation lock file remain in `~/.config/xdg-google-docs/`; the document cache/index, desktop-association backups/recovery information, operation lock file, and optional latest error remain in `~/.local/state/xdg-google-docs/`. Lock files do not contain credentials. XDG environment settings can change these locations. App configuration and state directories use owner-only permissions (`0700`), and newly written JSON files use owner-only read/write permissions (`0600`). These filesystem permissions do not prevent access by other processes running as you, system administrators, malware, or backups. Document URLs and status or error messages can also appear in terminal output or desktop notifications.

A session D-Bus and Secret Service provider such as GNOME Keyring are required; GNOME Keyring is already present on the target machine. Python keyring dependencies are installed with the package; the app does not introduce its own daemon. The system may show a keyring-unlock dialog, but there is no custom app keyring GUI. An inaccessible or locked keyring that cannot be unlocked produces an error, with **no plaintext filesystem fallback**. Encryption and access control depend on OS keyring settings; an empty-password keyring may lack encryption. The keyring does not guarantee protection against same-user malware in an unlocked session.

Users of v0.1.0 must upgrade to v0.2.0 for migration. On the next `status`, `auth`, `open`, or `logout`, legacy app-owned `client.json` and `token.json` in the app configuration directory migrate only after the whole bundle is stored in Secret Service and read back successfully for verification. Failed verification or inaccessible keyring storage leaves legacy files untouched. Differing existing keyring and legacy credentials stop migration without deletion. Migration does not itself require repeating Google authorization. The original user-provided downloaded client JSON remains untouched, and unlinking legacy files does not securely erase them or remove backup copies.

A temporary snapshot contains document bytes during processing and is closed when processing finishes or the process exits. Temporary storage is not guaranteed to be encrypted, and closing or deleting files is not secure erasure. See [SECURITY.md](SECURITY.md) for additional security considerations.

## Retention, Control, and Deletion

Keyring credentials, local configuration, and state remain until removed through the controls below, except for legacy files unlinked after verified migration. Uploaded documents and their private application metadata remain in your Google Drive until you delete them; the app does not automatically delete cloud copies when you delete a local original, log out, or uninstall it.

You can control or remove this data as follows:

1. Run `xdg-google-docs uninstall` to remove the app's desktop integration and restore defaults it still owns. Do this before deleting its installation or recovery metadata. This command keeps credentials and cloud documents.
2. Run `xdg-google-docs logout` to remove access/refresh token data from the keyring bundle while preserving the OAuth client configuration. This does not revoke Google's authorization grant or remove token copies in backups.
3. Revoke the app's access through [Google Account connections](https://myaccount.google.com/connections) to prevent further authorized access using that grant.
4. Delete unwanted uploaded documents in Google Drive and manage its trash and retention settings. Google or your organization may retain data according to their policies.
5. To delete the full credential bundle preserved by uninstall, remove the matching `xdg-google-docs` profile entry through the system Passwords and Keys (Seahorse) GUI. There is no app-specific GUI; deleting app directories alone does not remove the keyring entry.
6. After uninstalling, remove the app's configuration and state directories, original downloaded client JSON, and any relevant backups if you want to remove remaining local data. Deletion is not a secure-erasure guarantee. The maintainer cannot delete these credentials, files, or your Drive documents on your behalf because they are not held on a maintainer-operated server.

Using `--keep-office` disables native conversion, not uploading. Using `--print-url` suppresses browser launching, not uploading or remote lookup. Stop opening files with the app if you do not want it to transmit them to Google.

## Changes and Contact

Updates to this policy will be published in this file with a revised effective date. Its revision history is available in the public repository.

For privacy questions, contact the maintainer through [the project's GitHub issues](https://github.com/totalolage/xdg-google-docs/issues). Do not post documents, credentials, private URLs, or other personal information publicly; ask for a private contact channel first if needed. Security vulnerabilities can be reported through [GitHub private vulnerability reporting](https://github.com/totalolage/xdg-google-docs/security/advisories/new).
