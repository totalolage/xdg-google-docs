"""Desktop OAuth through the user's browser, initiated only from the CLI."""

import json

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from . import vault

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def login(client_file=None, no_browser=False):
    # The explicit input may itself be a legacy app file that migration removes.
    provided = json.loads(client_file.read_text()) if client_file else None
    saved = vault.credentials()
    data = provided if client_file else saved.get("client")
    if data:
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("installed"), dict)
            or "web" in data
        ):
            raise ValueError("Use an OAuth client of type Desktop app, not Web or Service account.")
        # Do not send authorization codes to endpoints from an arbitrary JSON file.
        client = data["installed"]
        if (
            client.get("auth_uri") != "https://accounts.google.com/o/oauth2/auth"
            and client.get("auth_uri") != "https://accounts.google.com/o/oauth2/v2/auth"
        ):
            raise ValueError("Client JSON has an unexpected Google authorization endpoint")
        if client.get("token_uri") != "https://oauth2.googleapis.com/token":
            raise ValueError("Client JSON has an unexpected Google token endpoint")
    else:
        raise ValueError("Run: xdg-google-docs auth --client /path/to/client_secret.json")
    flow = InstalledAppFlow.from_client_config(data, SCOPES, autogenerate_code_verifier=True)
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=not no_browser,
        timeout_seconds=300,
        prompt="consent",
        access_type="offline",
    )
    if not credentials.refresh_token:
        raise ValueError(
            "Google did not issue a refresh token. Revoke access and authenticate again."
        )
    vault.credentials({"client": data, "token": json.loads(credentials.to_json())})


def load_credentials():
    saved = vault.credentials()
    data = saved.get("token")
    if not data:
        raise ValueError(
            "Not authenticated. Run xdg-google-docs auth --client /path/to/client.json"
        )
    if not isinstance(data, dict):
        raise ValueError("Invalid credentials in the system keyring. Run xdg-google-docs auth")
    scopes = data.get("scopes", [])
    if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
        raise ValueError(
            "Invalid credential scopes in the system keyring. Run xdg-google-docs auth"
        )
    if not set(SCOPES).issubset(scopes):
        raise ValueError("Stored credentials lack drive.file access. Run xdg-google-docs auth")
    credentials = Credentials.from_authorized_user_info(data, SCOPES)
    if not credentials.valid:
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            raise ValueError(
                "Google authorization expired or was revoked. Run xdg-google-docs auth"
            ) from error
        saved["token"] = json.loads(credentials.to_json())
        vault.credentials(saved)
    return credentials
