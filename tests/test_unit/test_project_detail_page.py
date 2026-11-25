"""
/projects/<slug> detail page — task 6.7 (docs/imua_projects_plan_v1.md §5.3).
"""

import re

import pytest

ADMIN = {"Authorization": "Bearer op-test-key"}


@pytest.fixture
def lead_gen(app, admin_client):
    app.config["OPERATOR_KEY"] = "op-test-key"
    admin_client.post("/api/projects", json={"name": "Lead Gen", "description": "ABC Mortgage <site>"},
                      headers=ADMIN)
    return admin_client


def test_needs_sign_in(app, client):
    app.config["OPERATOR_KEY"] = "op-test-key"
    client.post("/api/projects", json={"name": "Lead Gen"}, headers=ADMIN)
    assert client.get("/projects/lead-gen").status_code == 302


def test_renders_header_and_all_tabs(lead_gen):
    html = lead_gen.get("/projects/lead-gen").get_data(as_text=True)
    assert "Lead Gen" in html and 'data-slug="lead-gen"' in html
    for tab in ("overview", "task", "document", "knowledge", "cron", "agents"):
        assert f'data-tab="{tab}"' in html
    assert "project_detail.js" in html


def test_description_is_escaped(lead_gen):
    html = lead_gen.get("/projects/lead-gen").get_data(as_text=True)
    assert "ABC Mortgage &lt;site&gt;" in html and "<site>" not in html


def test_tab_counts_come_from_the_project(lead_gen):
    token = lead_gen.post("/api/agents/register", json={"name": "AKM"},
                          headers={"X-CSRF-Token": _csrf(lead_gen)}).get_json()["token"]
    lead_gen.post("/api/tasks", json={"type": "build", "assigned_to": "AKM", "project": "lead-gen"},
                  headers={"Authorization": f"Bearer {token}"})
    html = lead_gen.get("/projects/lead-gen").get_data(as_text=True)
    assert re.search(r'data-tab="task">Tasks\s*<span class="project-tab-count">1</span>', html)
    assert re.search(r'data-tab="document">Documents\s*<span class="project-tab-count">0</span>', html)


def test_unknown_project_is_404(admin_client):
    assert admin_client.get("/projects/nope").status_code == 404


def test_slug_is_case_insensitive(lead_gen):
    assert lead_gen.get("/projects/LEAD-GEN").status_code == 200


def _csrf(client):
    with client.session_transaction() as s:
        return s.setdefault("csrf", "test-csrf")


class TestAdminControls:
    """Task 6.8a: new / edit / archive / delete controls (behaviour is browser-tested)."""

    def test_list_page_has_new_project_form(self, admin_client):
        html = admin_client.get("/projects").get_data(as_text=True)
        assert 'id="new-project-btn"' in html and 'id="new-project-form"' in html
        assert "project_form.js" in html

    def test_detail_page_has_edit_archive_delete(self, lead_gen):
        html = lead_gen.get("/projects/lead-gen").get_data(as_text=True)
        for control in ("edit-project-btn", "archive-project-btn", "delete-project-btn", "edit-project-form"):
            assert f'id="{control}"' in html
        assert re.search(r'id="archive-project-btn" data-status="active">\s*Archive<', html)

    def test_edit_form_is_prefilled_and_escaped(self, lead_gen):
        html = lead_gen.get("/projects/lead-gen").get_data(as_text=True)
        assert 'value="Lead Gen"' in html and ">ABC Mortgage &lt;site&gt;</textarea>" in html

    def test_archived_project_offers_unarchive(self, lead_gen):
        lead_gen.patch("/api/projects/lead-gen", json={"status": "archived"}, headers=ADMIN)
        html = lead_gen.get("/projects/lead-gen").get_data(as_text=True)
        assert re.search(r'data-status="archived">\s*Unarchive<', html)

    def test_page_tells_the_script_the_project_status(self, lead_gen):
        """Task 6.8b: the add controls are hidden for archived projects (browser-tested)."""
        assert 'data-status="active"' in lead_gen.get("/projects/lead-gen").get_data(as_text=True)
        lead_gen.patch("/api/projects/lead-gen", json={"status": "archived"}, headers=ADMIN)
        assert 'data-slug="lead-gen" data-status="archived"' in lead_gen.get("/projects/lead-gen").get_data(as_text=True)
