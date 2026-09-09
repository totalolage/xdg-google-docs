"""Content-addressed uploads: remote edits are never overwritten."""

import hashlib
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from .formats import FORMATS
from .storage import read_json, state_dir, write_json

FIELDS = "id,name,mimeType,webViewLink,trashed"


def checked_url(file):
    url = file.get("webViewLink", "")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"docs.google.com", "drive.google.com"}
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Google returned no safe editor URL; refusing to launch it")
    return url


def open_document(service, account_key, filename, *, convert=True, new=False):
    """Caller holds the process lock. Return (Google URL, created).

    Snapshot before hashing/uploading so the identity describes uploaded bytes,
    even when a local editor saves during the upload. No local paths go to Drive.
    """
    path = Path(filename).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"Not a regular file: {path}")
    suffix = path.suffix.lower()
    if suffix not in FORMATS:
        raise ValueError(f"Unsupported extension {suffix!r}: {path.name}")
    source_mime, target = FORMATS[suffix]
    mode = target if convert else source_mime
    cache_path = state_dir() / "documents.json"
    cache = read_json(cache_path, {})
    with tempfile.TemporaryFile() as snapshot, path.open("rb") as source:
        digest = hashlib.sha256()
        initial = os.fstat(source.fileno())
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            snapshot.write(chunk)
        final = os.fstat(source.fileno())
        if (initial.st_size, initial.st_mtime_ns, initial.st_ctime_ns) != (
            final.st_size,
            final.st_mtime_ns,
            final.st_ctime_ns,
        ):
            raise ValueError("File changed while being read. Save it and try again.")
        if snapshot.tell() == 0:
            raise ValueError("Cannot upload an empty document")
        # Include source MIME and conversion mode to avoid incompatible reuse.
        identity = hashlib.sha256(
            f"v1:{digest.hexdigest()}:{source_mime}:{mode}".encode()
        ).hexdigest()
        key = f"{account_key}:{identity}"
        file = None
        if not new and key in cache:
            try:
                candidate = (
                    service.files().get(fileId=cache[key], fields=FIELDS).execute(num_retries=3)
                )
                if not candidate.get("trashed"):
                    file = candidate
            except HttpError as error:
                if error.resp.status != 404:
                    raise
            if file is None:
                del cache[key]
                write_json(cache_path, cache)
        if not new and file is None:
            page_token = None
            while True:
                result = (
                    service.files()
                    .list(
                        q="trashed = false and appProperties has { key='xdgDocsV1' and value='"
                        + identity
                        + "' }",
                        spaces="drive",
                        pageSize=100,
                        pageToken=page_token,
                        orderBy="createdTime desc",
                        fields=f"nextPageToken,files({FIELDS})",
                    )
                    .execute(num_retries=3)
                )
                if result.get("files"):
                    file = result["files"][0]
                    break
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
        created = file is None
        if created:
            if convert:
                imports = service.about().get(fields="importFormats").execute(num_retries=3)
                if target not in imports.get("importFormats", {}).get(source_mime, []):
                    raise ValueError(f"Google cannot currently convert {suffix}; try --keep-office")
            snapshot.seek(0)
            body = {
                "name": path.stem if convert else path.name,
                "mimeType": mode,
                "appProperties": {"xdgDocsV1": identity},
            }
            media = MediaIoBaseUpload(
                snapshot, mimetype=source_mime, chunksize=8 * 1024 * 1024, resumable=True
            )
            request = service.files().create(body=body, media_body=media, fields=FIELDS)
            # Retry resumable chunks, never blindly retry an entire create operation.
            while file is None:
                _, file = request.next_chunk(num_retries=3)
        cache[key] = file["id"]
        write_json(cache_path, cache)
        return checked_url(file), created
