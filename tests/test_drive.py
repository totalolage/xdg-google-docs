import hashlib
import os
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import httplib2
import pytest
from googleapiclient.errors import HttpError

from xdg_google_docs import drive, storage
from xdg_google_docs.formats import FORMATS


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "private report.docx"
    path.write_bytes(b"original document bytes")
    return path


@pytest.fixture
def service():
    api = Mock()
    api.files.return_value.list.return_value.execute.return_value = {"files": []}
    imports = {}
    for source, target in FORMATS.values():
        imports.setdefault(source, []).append(target)
    api.about.return_value.get.return_value.execute.return_value = {"importFormats": imports}
    api.files.return_value.create.return_value.next_chunk.return_value = (None, remote())
    return api


def remote(id="doc-1", **kwargs):
    return {
        "id": id,
        "webViewLink": f"https://docs.google.com/document/d/{id}/edit",
        "trashed": False,
        **kwargs,
    }


def cache():
    return storage.read_json(storage.state_dir() / "documents.json", {})


def identity(data, suffix=".docx", convert=True):
    source, target = FORMATS[suffix]
    digest = hashlib.sha256(data).hexdigest()
    return hashlib.sha256(
        f"v1:{digest}:{source}:{target if convert else source}".encode()
    ).hexdigest()


def test_first_upload_conversion_and_snapshot(service, document):
    original = document.read_bytes()
    captured = {}
    request = Mock(next_chunk=Mock(side_effect=[(None, None), (None, remote())]))

    def create(**kwargs):
        document.write_bytes(b"saved while upload starts")
        media = kwargs["media_body"]
        captured["bytes"] = media.getbytes(0, media.size())
        assert media.mimetype() == FORMATS[".docx"][0]
        assert media.resumable()
        assert media.chunksize() == 8 * 1024 * 1024
        return request

    service.files.return_value.create.side_effect = create
    assert drive.open_document(service, "account", document) == (remote()["webViewLink"], True)
    body = service.files.return_value.create.call_args.kwargs["body"]
    assert body == {
        "name": document.stem,
        "mimeType": FORMATS[".docx"][1],
        "appProperties": {"xdgDocsV1": identity(original)},
    }
    assert captured["bytes"] == original
    assert cache() == {f"account:{identity(original)}": "doc-1"}
    service.about.return_value.get.assert_called_once_with(fields="importFormats")
    assert request.next_chunk.call_args_list == [call(num_retries=3), call(num_retries=3)]
    request.execute.assert_not_called()


def test_repeat_verifies_cached_id_and_uses_current_url(service, document):
    drive.open_document(service, "a", document)
    service.reset_mock()
    service.files.return_value.get.return_value.execute.return_value = remote("verified")
    assert drive.open_document(service, "a", document) == (remote("verified")["webViewLink"], False)
    service.files.return_value.get.assert_called_once_with(fileId="doc-1", fields=drive.FIELDS)
    service.files.return_value.get.return_value.execute.assert_called_once_with(num_retries=3)
    service.files.return_value.list.assert_not_called()
    service.files.return_value.create.assert_not_called()
    service.about.assert_not_called()


def test_content_lookup_recovers_without_local_cache(service, document):
    service.files.return_value.list.return_value.execute.return_value = {
        "files": [remote("recovered")]
    }
    assert drive.open_document(service, "a", document)[1] is False
    query = service.files.return_value.list.call_args.kwargs
    assert identity(document.read_bytes()) in query["q"]
    assert "trashed = false" in query["q"]
    assert str(document) not in query["q"]
    assert query["spaces"] == "drive"
    assert query["orderBy"] == "createdTime desc"
    assert list(cache().values()) == ["recovered"]
    service.files.return_value.create.assert_not_called()


def test_changed_bytes_create_distinct_document(service, document):
    drive.open_document(service, "a", document)
    document.write_bytes(b"revised")
    service.files.return_value.create.return_value.next_chunk.return_value = (None, remote("new"))
    assert drive.open_document(service, "a", document)[1] is True
    assert set(cache().values()) == {"doc-1", "new"}
    service.files.return_value.get.assert_not_called()


def test_empty_search_page_follows_continuation(service, document):
    service.files.return_value.list.return_value.execute.side_effect = [
        {"files": [], "nextPageToken": "second-page"},
        {"files": [remote("recovered")]},
    ]
    assert drive.open_document(service, "a", document) == (
        remote("recovered")["webViewLink"],
        False,
    )
    calls = service.files.return_value.list.call_args_list
    assert calls[0].kwargs["pageToken"] is None
    assert calls[1].kwargs["pageToken"] == "second-page"
    assert "nextPageToken" in calls[0].kwargs["fields"]
    service.files.return_value.create.assert_not_called()


def test_identical_bytes_at_another_path_reuse_document(service, document, tmp_path):
    drive.open_document(service, "a", document)
    renamed = tmp_path / "renamed.docx"
    renamed.write_bytes(document.read_bytes())
    service.files.return_value.get.return_value.execute.return_value = remote()
    assert drive.open_document(service, "a", renamed)[1] is False
    assert service.files.return_value.create.call_count == 1


def test_same_bytes_with_different_source_mime_do_not_share_cache(service, document):
    drive.open_document(service, "a", document)
    other = document.with_suffix(".odt")
    other.write_bytes(document.read_bytes())
    assert drive.open_document(service, "a", other)[1] is True
    assert len(cache()) == 2
    service.files.return_value.get.assert_not_called()


@pytest.mark.parametrize("field", ["st_size", "st_mtime_ns", "st_ctime_ns"])
def test_mutation_during_snapshot_aborts_before_google(service, document, field):
    initial = document.stat()
    values = {name: getattr(initial, name) for name in ("st_size", "st_mtime_ns", "st_ctime_ns")}
    values[field] += 1
    with patch.object(os, "fstat", side_effect=[initial, SimpleNamespace(**values)]):
        with pytest.raises(ValueError, match="changed while being read"):
            drive.open_document(service, "a", document)
    assert not service.mock_calls


@pytest.mark.parametrize("stale", ["trashed", 404])
@pytest.mark.parametrize("recover", [False, True])
def test_stale_cache_recovery(service, document, stale, recover):
    drive.open_document(service, "a", document)
    service.reset_mock()
    request = service.files.return_value.get.return_value.execute
    if stale == "trashed":
        request.return_value = remote(trashed=True)
    else:
        request.side_effect = HttpError(httplib2.Response({"status": "404"}), b"not found")
    service.files.return_value.list.return_value.execute.return_value = {
        "files": [remote("recovered")] if recover else []
    }
    assert drive.open_document(service, "a", document)[1] is not recover
    assert service.files.return_value.create.call_count == (0 if recover else 1)


def test_403_is_not_treated_as_missing(service, document):
    drive.open_document(service, "a", document)
    previous = cache()
    service.reset_mock()
    error = HttpError(httplib2.Response({"status": "403"}), b"forbidden")
    service.files.return_value.get.return_value.execute.side_effect = error
    with pytest.raises(HttpError) as caught:
        drive.open_document(service, "a", document)
    assert caught.value is error
    assert cache() == previous
    service.files.return_value.list.assert_not_called()
    service.files.return_value.create.assert_not_called()


def test_forced_new_skips_both_reuse_paths(service, document):
    drive.open_document(service, "a", document)
    service.reset_mock()
    assert drive.open_document(service, "a", document, new=True)[1] is True
    service.files.return_value.get.assert_not_called()
    service.files.return_value.list.assert_not_called()
    service.files.return_value.create.assert_called_once()


def test_office_mode_separate_identity_and_no_conversion_check(service, document):
    drive.open_document(service, "a", document)
    service.reset_mock()
    drive.open_document(service, "a", document, convert=False)
    body = service.files.return_value.create.call_args.kwargs["body"]
    assert body["name"] == document.name
    assert body["mimeType"] == FORMATS[".docx"][0]
    assert body["appProperties"]["xdgDocsV1"] == identity(document.read_bytes(), convert=False)
    assert len(cache()) == 2
    service.about.assert_not_called()
    service.files.return_value.get.assert_not_called()


def test_accounts_never_reuse_each_others_cached_ids(service, document):
    drive.open_document(service, "alice", document)
    drive.open_document(service, "bob", document)
    assert {key.split(":")[0] for key in cache()} == {"alice", "bob"}
    service.files.return_value.get.assert_not_called()
    assert service.files.return_value.list.call_count == 2


@pytest.mark.parametrize("suffix", list(FORMATS))
def test_supported_formats(service, tmp_path, suffix):
    path = tmp_path / ("Report" + suffix.upper())
    path.write_bytes(b"test content")
    drive.open_document(service, "a", path)
    assert (
        service.files.return_value.create.call_args.kwargs["body"]["mimeType"] == FORMATS[suffix][1]
    )


@pytest.mark.parametrize("kind", ["unsupported", "empty", "directory", "missing"])
def test_invalid_files_do_not_contact_google(service, tmp_path, kind):
    path = tmp_path / ("file.zip" if kind == "unsupported" else "file.docx")
    if kind == "directory":
        path.mkdir()
    elif kind != "missing":
        path.write_bytes(b"" if kind == "empty" else b"bytes")
    with pytest.raises((ValueError, FileNotFoundError)):
        drive.open_document(service, "a", path)
    assert not service.mock_calls


@pytest.mark.parametrize(
    "imports",
    [{}, {"importFormats": {}}, {"importFormats": {FORMATS[".docx"][0]: ["wrong-target"]}}],
)
def test_conversion_requires_google_import_support(service, document, imports):
    service.about.return_value.get.return_value.execute.return_value = imports
    with pytest.raises(ValueError, match="keep-office"):
        drive.open_document(service, "a", document)
    service.files.return_value.create.assert_not_called()
    assert cache() == {}


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://docs.google.com/a",
        "https://evil.test/a",
        "https://docs.google.com.evil.test/a",
        "https://docs.google.com@evil.test/a",
        "https://evil@docs.google.com/a",
        "https://docs.google.com:444/a",
        "javascript:alert(1)",
    ],
)
@pytest.mark.parametrize("origin", ["create", "list", "get"])
def test_malicious_returned_urls_are_rejected(service, document, url, origin):
    bad = remote(webViewLink=url)
    if origin == "get":
        drive.open_document(service, "a", document)
        service.files.return_value.get.return_value.execute.return_value = bad
    elif origin == "list":
        service.files.return_value.list.return_value.execute.return_value = {"files": [bad]}
    else:
        service.files.return_value.create.return_value.next_chunk.return_value = (None, bad)
    with pytest.raises(ValueError, match="safe editor URL"):
        drive.open_document(service, "a", document)


@pytest.mark.parametrize(
    "url",
    [
        "https://docs.google.com/document/d/1/edit",
        "https://drive.google.com/file/d/1/view",
        "https://docs.google.com:443/document/d/1/edit",
    ],
)
def test_safe_urls(url):
    assert drive.checked_url({"webViewLink": url}) == url
