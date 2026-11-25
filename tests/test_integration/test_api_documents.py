"""Integration tests for the Document Store API — upload, list, download, archive."""

import io


def _register(client, name="akm"):
    resp = client.post("/api/agents/register", json={"name": name})
    return resp.get_json()["token"]


def _upload(client, token, filename="notes.md", content=b"hello world", uploaded_by="akm"):
    return client.post(
        "/api/documents",
        data={"file": (io.BytesIO(content), filename), "uploaded_by": uploaded_by},
        content_type="multipart/form-data",
        headers={"Authorization": f"Bearer {token}"},
    )


class TestUploadDocumentApi:
    def test_upload_returns_201_with_metadata(self, client):
        token = _register(client)
        resp = _upload(client, token)

        assert resp.status_code == 201
        data = resp.get_json()
        assert data["filename"] == "notes.md"
        assert data["size"] == len(b"hello world")
        assert data["uploaded_by"] == "akm"
        assert data["archived"] is False

    def test_upload_missing_file_returns_422(self, client):
        token = _register(client)
        resp = client.post("/api/documents", data={}, content_type="multipart/form-data",
                            headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 422

    def test_upload_without_token_returns_401(self, client):
        resp = client.post(
            "/api/documents",
            data={"file": (io.BytesIO(b"hello"), "notes.md")},
            content_type="multipart/form-data",
        )

        assert resp.status_code == 401
        assert resp.get_json()["error"] == "unauthorized"


class TestListDocumentsApi:
    """GET /api/documents stays open (no auth) by design — matches every
    other read-only endpoint in the API."""

    def test_list_includes_uploaded_document(self, client):
        token = _register(client)
        _upload(client, token, filename="a.md")

        resp = client.get("/api/documents")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 1
        assert data["documents"][0]["filename"] == "a.md"

    def test_list_filter_by_archived(self, client):
        token = _register(client)
        _upload(client, token, filename="active.md")
        upload_resp = _upload(client, token, filename="old.md")
        doc_id = upload_resp.get_json()["id"]
        client.post(f"/api/documents/{doc_id}/archive",
                     headers={"Authorization": f"Bearer {token}"})

        active_only = client.get("/api/documents?archived=false").get_json()
        archived_only = client.get("/api/documents?archived=true").get_json()

        assert [d["filename"] for d in active_only["documents"]] == ["active.md"]
        assert [d["filename"] for d in archived_only["documents"]] == ["old.md"]


class TestDownloadDocumentApi:
    """GET /api/documents/<id>/download stays open (no auth) by design —
    matches every other read-only endpoint in the API."""

    def test_download_returns_original_content(self, client):
        token = _register(client)
        upload_resp = _upload(client, token, filename="report.txt", content=b"the actual content")
        doc_id = upload_resp.get_json()["id"]

        resp = client.get(f"/api/documents/{doc_id}/download")

        assert resp.status_code == 200
        assert resp.data == b"the actual content"

    def test_download_nonexistent_returns_404(self, client):
        resp = client.get("/api/documents/999/download")

        assert resp.status_code == 404


class TestArchiveDocumentApi:
    def test_archive_marks_document_archived(self, client):
        token = _register(client)
        upload_resp = _upload(client, token)
        doc_id = upload_resp.get_json()["id"]

        resp = client.post(f"/api/documents/{doc_id}/archive",
                            headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        assert resp.get_json()["archived"] is True

    def test_unarchive_restores_document(self, client):
        token = _register(client)
        upload_resp = _upload(client, token)
        doc_id = upload_resp.get_json()["id"]
        client.post(f"/api/documents/{doc_id}/archive",
                     headers={"Authorization": f"Bearer {token}"})

        resp = client.post(f"/api/documents/{doc_id}/unarchive",
                            headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        assert resp.get_json()["archived"] is False

    def test_archive_nonexistent_returns_404(self, client):
        token = _register(client)
        resp = client.post("/api/documents/999/archive",
                            headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 404

    def test_archive_without_token_returns_401(self, client):
        token = _register(client)
        upload_resp = _upload(client, token)
        doc_id = upload_resp.get_json()["id"]

        resp = client.post(f"/api/documents/{doc_id}/archive")

        assert resp.status_code == 401
        assert resp.get_json()["error"] == "unauthorized"

    def test_unarchive_without_token_returns_401(self, client):
        token = _register(client)
        upload_resp = _upload(client, token)
        doc_id = upload_resp.get_json()["id"]
        client.post(f"/api/documents/{doc_id}/archive",
                     headers={"Authorization": f"Bearer {token}"})

        resp = client.post(f"/api/documents/{doc_id}/unarchive")

        assert resp.status_code == 401
        assert resp.get_json()["error"] == "unauthorized"
