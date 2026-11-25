"""Smoke tests — verify the app starts and serves pages."""


def test_health_endpoint(client):
    """GET /api/health returns 200 with status ok."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "version" in data


def test_dashboard_page(admin_client):
    """GET / returns 200 with dashboard HTML."""
    client = admin_client
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Imua" in resp.data
    assert b"Dashboard" in resp.data
    assert b"Agents" in resp.data


def test_dashboard_stats_rendered(admin_client):
    """Dashboard shows stat cards for agents, messages, tasks, cron."""
    client = admin_client
    resp = client.get("/")
    assert resp.status_code == 200
    for label in [b"Agents", b"Messages", b"Tasks", b"Cron Jobs"]:
        assert label in resp.data


def test_documents_page(admin_client):
    """GET /documents returns 200 with the documents page."""
    client = admin_client
    resp = client.get("/documents")
    assert resp.status_code == 200
    assert b"Documents" in resp.data
    assert b"Upload" in resp.data
