# Terms of Service for xdg-google-docs

Effective date: September 9, 2026

These terms describe the use of **xdg-google-docs**, an open-source Linux application maintained by Filip Kalny ([totalolage](https://github.com/totalolage)) and distributed through [its official repository](https://github.com/totalolage/xdg-google-docs). Please read these terms and the [Privacy Policy](PRIVACY.md) before authorizing the app or opening documents with it.

## Application and License

xdg-google-docs runs on your computer and uses your authorized Google account to upload local office documents to Google Drive, optionally convert them to Google Docs, Sheets, or Slides, and open their browser URLs. It can reopen copies previously uploaded through the app. It is not a developer-hosted document storage service and is not affiliated with, endorsed by, or operated by Google.

The software is provided under the [MIT License](LICENSE). That license governs your rights to use, copy, modify, and distribute the software. These terms do not impose additional restrictions on those license rights or replace the MIT License. Third-party components remain subject to their respective licenses. Independently modified versions may behave differently from the official application.

## Your Responsibilities

You are responsible for choosing which documents to open, which Google account to authorize, and whether uploading those documents is appropriate. In particular:

- Only upload material you have the right and permission to send to Google and to store in the authorized account.
- Follow applicable law, confidentiality obligations, workplace or organization policies, and the terms governing your Google account.
- Check the authorized account before uploading sensitive documents. The account used by the CLI can differ from the account currently active in your browser.
- Protect your computer, OAuth client configuration, tokens, and backups. Version 0.2.0 stores the client configuration and access/refresh tokens in one system Secret Service keyring entry, with no plaintext fallback. Encryption and access control depend on OS keyring settings; an empty-password keyring may lack encryption, and an unlocked session is not guaranteed protection against same-user malware. Settings, cache/index, errors, and desktop association backups remain on the filesystem; the original downloaded client JSON remains untouched.
- Keep independent backups and verify important documents after uploading or converting them.
- Do not use the app to obtain unauthorized access, circumvent service restrictions, or infringe the rights of others.

You retain your rights in your documents. Using the app does not transfer ownership of your documents to the maintainer. Permissions you grant Google are governed separately by your agreements with Google.

## Uploads, Conversion, and Reopening

**Opening a document can transmit its contents to Google.** If you set the app as a default file handler, double-clicking an associated file can initiate an upload without an additional confirmation. `--keep-office` disables native conversion, not uploading. `--print-url` suppresses browser launching, not uploading or remote lookup.

The app creates cloud copies; it does not synchronize local files with Google Drive. Browser edits remain in Google Drive and are not automatically saved back to the local original. Changed local contents generally produce a separate cloud copy rather than overwrite an existing copy. Identical local contents can reopen an existing cloud document that has since been edited online.

Conversion can change or omit formatting, formulas, macros, embedded objects, and other features. Neither conversion fidelity nor successful editing of every supported extension is guaranteed. Content-based reopening is not a guarantee of uniqueness, backup integrity, or equivalence between current local and remote contents. Network failures, indexing delays, concurrent clients, and interrupted operations can produce duplicates or incomplete operations.

## Google and Other Third Parties

You must supply an appropriate Google OAuth client and authorize access to your Google account. The app requests the `drive.file` scope. You are responsible for your Google Cloud project configuration and any verification or organization requirements that apply to your use.

Google Drive, Google Docs, Google Sheets, Google Slides, OAuth authorization, and related services are provided by Google, not by the maintainer. Your use of those services is subject to [Google's Terms of Service](https://policies.google.com/terms), [Google's Privacy Policy](https://policies.google.com/privacy), and any additional terms applicable to your account or services. Storage limits, API quotas, service availability, token expiration, and Google's policies can affect the app's operation. Any third-party charges associated with your account or use remain your responsibility.

The maintainer cannot guarantee continued access to third-party services or control their changes, retention policies, or availability. Your browser, extensions, operating system, and backup tools are also outside the app's control.

Credential operations require a session D-Bus and a Secret Service provider, such as the GNOME Keyring already present on the target machine. The package installs its Python keyring dependencies and introduces no app daemon. The system may show an unlock dialog; the app has no custom keyring GUI. An inaccessible or locked keyring that cannot be unlocked causes an error rather than a filesystem fallback.

## Privacy and Removal

The [Privacy Policy](PRIVACY.md) describes data access, use, storage, sharing, retention, and deletion. The [security documentation](SECURITY.md) explains additional risks and safeguards.

Users of v0.1.0 must upgrade to v0.2.0 to migrate legacy app-owned `client.json` and `token.json`. The next `status`, `auth`, `open`, or `logout` stores and reads back the whole keyring bundle for verification before unlinking legacy files. Failed verification or inaccessible keyring storage leaves legacy files untouched; differing existing keyring and legacy credentials stop migration without deletion. Migration itself requires no repeat Google authorization and does not securely erase legacy files, original downloads, or backups. See the [README](README.md#local-data-and-removal) for profile isolation by resolved configuration directory.

You may stop using the app at any time. Run `xdg-google-docs uninstall` before removing its installation or recovery metadata to remove its desktop integration and restore defaults it still owns. Run `xdg-google-docs logout` to remove access/refresh token data from its keyring bundle while preserving the OAuth client configuration, and revoke the grant through [Google Account connections](https://myaccount.google.com/connections) if you want to withdraw Google authorization.

Uninstall preserves keyring credentials. To delete the full credential entry, use the system Passwords and Keys (Seahorse) GUI to remove the matching `xdg-google-docs` profile entry; there is no app-specific GUI. Uninstalling or logging out does not delete uploaded documents from Google Drive. You must manage cloud documents and their deletion through Google. Remaining local configuration, state, original downloaded credentials, and backups must be removed separately if desired. Removing app directories does not remove keyring credentials, and deletion is not a secure-erasure guarantee.

## Availability and Changes

The software is provided without a commitment to ongoing maintenance, support, compatibility, availability, or a particular response time. The maintainer may change or discontinue future development or distribution. This does not revoke rights already granted under the MIT License.

Updates to these terms will be published here with a revised effective date, and the repository retains their revision history. Review the terms and documentation when adopting a new version. Changes do not retroactively alter the MIT License applicable to copies you already received.

## Disclaimer and Liability

To the fullest extent permitted by applicable law, the software is provided **"AS IS"**, without warranties of any kind, express or implied, including merchantability, fitness for a particular purpose, and noninfringement, as stated in the MIT License. There is no promise that it will be error-free, uninterrupted, secure against every threat, or suitable for a particular document or workflow.

To the fullest extent permitted by applicable law, the authors and copyright holders are not liable for claims, damages, or other liability arising from the software or its use, including loss or corruption of data, conversion errors, unintended uploads or disclosure, loss of access, or interruptions to third-party services, as provided in the MIT License.

Nothing in these terms excludes or limits rights, warranties, remedies, or liability that cannot lawfully be excluded or limited, including applicable mandatory consumer protections.

## Contact

For questions about these terms, contact the maintainer through [the project's GitHub issues](https://github.com/totalolage/xdg-google-docs/issues). Do not post credentials, private documents, or personal information publicly; ask for a private contact channel if needed. Report security vulnerabilities through [GitHub private vulnerability reporting](https://github.com/totalolage/xdg-google-docs/security/advisories/new).
