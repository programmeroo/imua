"""
Projects menu item and /projects list page — task 6.6 (docs/imua_projects_plan_v1.md §5.3).
"""

import re


def test_page_needs_sign_in(client):
    r = client.get("/projects")
    assert r.status_code == 302 and r.headers["Location"].startswith("/login")


def test_page_renders(admin_client):
    html = admin_client.get("/projects").get_data(as_text=True)
    assert 'id="projects-grid"' in html and "projects.js" in html


def test_menu_item_right_after_dashboard(admin_client):
    html = admin_client.get("/").get_data(as_text=True)
    nav = re.findall(r'<a href="(/[a-z]*)" class="nav-item', html)
    assert nav[:3] == ["/", "/projects", "/agents"]


def test_menu_item_active_on_projects_page(admin_client):
    html = admin_client.get("/projects").get_data(as_text=True)
    assert re.search(r'href="/projects" class="nav-item active"', html)


def test_git_site_hosting_unaffected(client):
    assert client.get("/project/").status_code != 302  # /project/ (singular) stays the git site
