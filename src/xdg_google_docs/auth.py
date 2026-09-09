"""Desktop OAuth through the user's browser, initiated only from the CLI."""

import json

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .storage import config_dir, read_json, write_json

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def login(client_file=None, no_browser=False):
    client_path = config_dir() / "client.json"
    if client_file or client_path.exists():
        data = json.loads((client_file or client_path).read_text())
        if "installed" not in data or "web" in data:
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
        if client_file:
            write_json(client_path, data)
    if not client_path.exists():
        raise ValueError("Run: xdg-google-docs auth --client /path/to/client_secret.json")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_path), SCOPES, autogenerate_code_verifier=True
    )
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
    write_json(config_dir() / "token.json", json.loads(credentials.to_json()))


def load_credentials():
    path = config_dir() / "token.json"
    data = read_json(path)
    if not data:
        raise ValueError(
            "Not authenticated. Run xdg-google-docs auth --client /path/to/client.json"
        )
    if not set(SCOPES).issubset(data.get("scopes", [])):
        raise ValueError("Stored credentials lack drive.file access. Run xdg-google-docs auth")
    credentials = Credentials.from_authorized_user_info(data, SCOPES)
    if not credentials.valid:
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            raise ValueError(
                "Google authorization expired or was revoked. Run xdg-google-docs auth"
            ) from error
        write_json(path, json.loads(credentials.to_json()))
    return credentials
