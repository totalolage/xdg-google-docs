"""Command-line interface and noninteractive desktop entry point."""

import argparse
import hashlib
import shutil
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import google_auth_httplib2
import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import auth, desktop
from .drive import open_document
from .storage import config_dir, locked, read_json, state_dir, write_json


def notify(message):
    if shutil.which("notify-send"):
        try:
            subprocess.run(
                [
                    "notify-send",
                    "--app-name=Google Docs Opener",
                    "--",
                    "Google Docs Opener",
                    message,
                ],
                check=False,
                timeout=5,
                capture_output=True,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def parser():
    result = argparse.ArgumentParser(description="Open local office files in Google's web editors.")
    commands = result.add_subparsers(dest="command", required=True)
    login = commands.add_parser("auth", help="Authenticate using desktop OAuth")
    login.add_argument("--client", type=Path, help="Downloaded Desktop app OAuth client JSON")
    login.add_argument(
        "--no-browser", action="store_true", help="Print URL instead of launching browser"
    )
    commands.add_parser(
        "logout", help="Delete local tokens (does not delete documents or revoke grant)"
    )
    status = commands.add_parser("status", help="Show local setup; optionally verify Google access")
    status.add_argument("--check", action="store_true")
    opening = commands.add_parser("open", help="Upload/reopen documents and launch their web URLs")
    mode = opening.add_mutually_exclusive_group()
    mode.add_argument(
        "--keep-office", action="store_true", help="Upload original format, without conversion"
    )
    mode.add_argument("--convert", action="store_true", help="Convert even if configured otherwise")
    opening.add_argument(
        "--new", action="store_true", help="Intentionally create a fresh cloud copy"
    )
    opening.add_argument("--print-url", action="store_true", help="Do not launch browser")
    opening.add_argument("--desktop", action="store_true", help=argparse.SUPPRESS)
    opening.add_argument("files", nargs="+", type=Path)
    install = commands.add_parser(
        "install", help="Install per-user desktop entry and MIME defaults"
    )
    install.add_argument("--include-csv", action="store_true")
    install.add_argument("--no-defaults", action="store_true", help="Only add Open With menu entry")
    commands.add_parser("uninstall", help="Remove desktop integration and restore owned defaults")
    config = commands.add_parser("config", help="Set the default mode for desktop and CLI opening")
    config.add_argument("mode", choices=["convert", "office"])
    return result


def drive_service():
    credentials = auth.load_credentials()
    service = build(
        "drive",
        "v3",
        cache_discovery=False,
        http=google_auth_httplib2.AuthorizedHttp(credentials, http=httplib2.Http(timeout=60)),
    )
    # Scope cache IDs to both Google account and OAuth app, never just local path.
    user = (
        service.about().get(fields="user(permissionId,emailAddress)").execute(num_retries=3)["user"]
    )
    account = hashlib.sha256(f"{credentials.client_id}:{user['permissionId']}".encode()).hexdigest()
    return service, account, user


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        # Desktop installation manages its own lock; flock is not reentrant.
        with nullcontext() if args.command in {"install", "uninstall"} else locked():
            if args.command == "auth":
                auth.login(args.client, args.no_browser)
                print("Authenticated. You can now open documents.")
            elif args.command == "logout":
                (config_dir() / "token.json").unlink(missing_ok=True)
                print(
                    "Local token deleted. Revoke the app in your Google Account to remove its grant."
                )
            elif args.command == "status":
                print(f"Config: {config_dir()}\nState: {state_dir()}")
                print(
                    "Token: "
                    + (
                        "present (not verified)"
                        if (config_dir() / "token.json").exists()
                        else "missing"
                    )
                )
                if args.check:
                    service, _, user = drive_service()
                    try:
                        print(
                            f"Google access verified: {user.get('emailAddress', 'authenticated user')}"
                        )
                    finally:
                        service.close()
            elif args.command == "install":
                executable = shutil.which("xdg-google-docs") or sys.argv[0]
                desktop.install(
                    str(Path(executable).absolute()), args.include_csv, not args.no_defaults
                )
                print(
                    "Desktop integration installed. Opening an associated file uploads it to Google."
                )
            elif args.command == "uninstall":
                desktop.uninstall()
                print("Desktop integration removed; credentials and cloud documents were kept.")
            elif args.command == "config":
                write_json(config_dir() / "settings.json", {"mode": args.mode})
                print(f"Default mode: {args.mode}")
            elif args.command == "open":
                settings = read_json(config_dir() / "settings.json", {})
                convert = args.convert or (
                    not args.keep_office and settings.get("mode", "convert") == "convert"
                )
                service, account, _ = drive_service()
                failures = 0
                try:
                    for file in args.files:
                        try:
                            if args.desktop:
                                notify(f"Preparing {file.name} in Google Drive...")
                            url, created = open_document(
                                service, account, file, convert=convert, new=args.new
                            )
                            print(url, flush=True)
                            if not args.print_url:
                                subprocess.run(["xdg-open", url], check=True, timeout=30)
                            if args.desktop:
                                notify(
                                    "Uploaded a cloud copy."
                                    if created
                                    else "Opened the existing cloud copy."
                                )
                        except Exception as error:
                            failures += 1
                            report(error, args.desktop)
                finally:
                    service.close()
                return int(bool(failures))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        report(error, getattr(args, "desktop", False))
        return 1


def report(error, desktop_mode):
    # HttpError's string can include a request URI; never persist that or OAuth errors.
    if isinstance(error, HttpError):
        message = f"Google Drive request failed (HTTP {error.resp.status}). Check API enablement, permissions, quota and network; retry."
    elif isinstance(error, (OSError, ValueError, subprocess.SubprocessError)):
        message = str(error)
    else:
        message = f"{type(error).__name__}: operation failed. Check your connection or run xdg-google-docs auth again."
    print(f"xdg-google-docs: {message}", file=sys.stderr)
    if desktop_mode:
        notify(message)
        write_json(state_dir() / "last-error.json", {"message": message})


if __name__ == "__main__":
    sys.exit(main())
