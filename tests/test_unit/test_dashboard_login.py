"""
Dashboard pages need a signed-in admin — task 5.7 (docs/imua_admin_security_plan_v1.md).
"""

import pytest

from app.services.admin_accounts import create_admin

PAGES = ["/", "/agents", "/messages", "/tasks", "/documents", "/knowledge", "/cron", "/cron/1",
         "/issues", "/settings"]


@pytest.mark.parametrize("page", PAGES)
def test_signed_out_redirects_to_sign_in(client, page):
    r = client.get(page)
    assert r.status_code == 302
    assert r.headers["Location"].startswith("/login?next=")
    assert b"Imua" not in r.data or b"Redirecting" in r.data  # no page content leaks


def test_next_keeps_the_query_string(client):
    assert client.get("/tasks?status=pending").headers["Location"] == "/login?next=%2Ftasks%3Fstatus%3Dpending"


def test_unknown_paths_are_gated_too(client):
    assert client.get("/some-future-page").status_code == 302


@pytest.mark.parametrize("page", [p for p in PAGES if p != "/cron/1"])
def test_signed_in_pages_render(admin_client, page):
    assert admin_client.get(page).status_code == 200


@pytest.mark.parametrize("path,status", [("/login", 200), ("/api/health", 200), ("/api/projects", 200),
                                         ("/static/css/main.css", 200)])
def test_open_paths(client, path, status):
    assert client.get(path).status_code == status


def test_git_site_is_not_gated(client):
    assert client.get("/project/").status_code != 302


def test_agent_api_unaffected(client):
    token = client.post("/api/agents/register", json={"name": "AKM"}).get_json()["token"]
    r = client.patch("/api/agents/AKM/heartbeat", json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_sign_in_lands_on_the_requested_page(app, client):
    """The real flow: redirect to /login?next=..., the form carries next as a hidden field."""
    import re
    with app.config["DB_ENGINE"].begin() as conn:
        create_admin(conn, "admin", "correct horse battery")
    form = client.get(client.get("/tasks").headers["Location"]).get_data(as_text=True)
    fields = dict(re.findall(r'name="(next|csrf_token)" value="([^"]*)"', form))
    assert fields["next"] == "/tasks"
    r = client.post("/login", data={"username": "admin", "password": "correct horse battery", **fields})
    assert r.headers["Location"] == "/tasks"
    assert client.get("/tasks").status_code == 200


def test_first_run_hint_until_an_admin_exists(app, client):
    assert b"No admin account yet" in client.get("/login").data
    with app.config["DB_ENGINE"].begin() as conn:
        create_admin(conn, "admin", "correct horse battery")
    assert b"No admin account yet" not in client.get("/login").data
