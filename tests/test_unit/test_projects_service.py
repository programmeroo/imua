"""
Projects service — task 6.2 (docs/imua_projects_plan_v1.md §4).
"""

import pytest

from app.models.agent import agents
from app.models.cron import cron_jobs
from app.models.document import documents
from app.models.knowledge import knowledge_entries
from app.models.task import tasks
from app.services import projects as svc
from app.services.projects import Conflict, NotFound, ProjectError


@pytest.fixture
def conn(app):
    with app.config["DB_ENGINE"].begin() as c:
        yield c


@pytest.fixture
def items(conn):
    """One row of each item type, plus agent AKM. Returns {type: id}."""
    conn.execute(agents.insert().values(name="AKM", token_hash="x"))
    return {
        "task": conn.execute(tasks.insert().values(type="build")).inserted_primary_key[0],
        "document": conn.execute(documents.insert().values(filename="a.md", storage_path="/x"))
        .inserted_primary_key[0],
        "cron": conn.execute(cron_jobs.insert().values(name="nightly", schedule="0 2 * * *"))
        .inserted_primary_key[0],
        "knowledge": conn.execute(knowledge_entries.insert().values(chroma_id="k1", source="manual", body="b"))
        .inserted_primary_key[0],
    }


class TestProjects:
    def test_create_makes_slug_from_name(self, conn):
        p = svc.create_project(conn, "  Lead Gen: ABC Mortgage! ", created_by="admin")
        assert p["slug"] == "lead-gen-abc-mortgage" and p["name"] == "Lead Gen: ABC Mortgage!"
        assert p["status"] == "active" and p["agents"] == []
        assert p["counts"] == {"task": 0, "document": 0, "cron": 0, "knowledge": 0}

    @pytest.mark.parametrize("slug", ["a", "-x", "has space", "bad_slug", "x" * 65])
    def test_bad_slug(self, conn, slug):
        with pytest.raises(ProjectError):
            svc.create_project(conn, "Name", slug=slug)

    def test_name_with_no_usable_slug(self, conn):
        with pytest.raises(ProjectError):
            svc.create_project(conn, "!!!")

    @pytest.mark.parametrize("name", ["", "   ", None, "x" * 129])
    def test_bad_name(self, conn, name):
        with pytest.raises(ProjectError):
            svc.create_project(conn, name, slug="ok-slug")

    def test_duplicate_slug(self, conn):
        svc.create_project(conn, "Alpha")
        with pytest.raises(Conflict):
            svc.create_project(conn, "alpha")

    def test_list_and_filter(self, conn):
        svc.create_project(conn, "Beta")
        svc.create_project(conn, "Alpha")
        svc.update_project(conn, "beta", status="archived")
        assert [p["slug"] for p in svc.list_projects(conn)] == ["alpha", "beta"]
        assert [p["slug"] for p in svc.list_projects(conn, status="active")] == ["alpha"]

    def test_update(self, conn):
        svc.create_project(conn, "Alpha")
        p = svc.update_project(conn, "ALPHA", name="Alpha 2", description="d")
        assert (p["slug"], p["name"], p["description"]) == ("alpha", "Alpha 2", "d")
        with pytest.raises(ProjectError):
            svc.update_project(conn, "alpha", status="deleted")

    def test_unknown_project(self, conn):
        for call in (lambda: svc.get_project(conn, "nope"), lambda: svc.update_project(conn, "nope", name="x"),
                     lambda: svc.delete_project(conn, "nope")):
            with pytest.raises(NotFound):
                call()


class TestMembers:
    def test_add_is_idempotent_and_remove(self, conn, items):
        svc.create_project(conn, "Alpha")
        svc.add_agent(conn, "alpha", "AKM")
        assert svc.add_agent(conn, "alpha", "AKM")["agents"] == ["AKM"]
        assert svc.remove_agent(conn, "alpha", "AKM")["agents"] == []
        assert svc.remove_agent(conn, "alpha", "AKM")["agents"] == []

    def test_unknown_agent(self, conn, items):
        svc.create_project(conn, "Alpha")
        with pytest.raises(NotFound):
            svc.add_agent(conn, "alpha", "GHOST")

    def test_agent_in_several_projects(self, conn, items):
        for name in ("Alpha", "Beta"):
            svc.create_project(conn, name)
            svc.add_agent(conn, name.lower(), "AKM")
        assert all(p["agents"] == ["AKM"] for p in svc.list_projects(conn))


class TestItems:
    @pytest.mark.parametrize("item_type", ["task", "document", "cron", "knowledge"])
    def test_put_list_remove(self, conn, items, item_type):
        svc.create_project(conn, "Alpha")
        svc.put_item(conn, "alpha", item_type, items[item_type], added_by="admin")
        assert svc.item_ids(conn, "alpha", item_type) == [items[item_type]]
        assert svc.get_project(conn, "alpha")["counts"][item_type] == 1
        assert svc.projects_of(conn, item_type, [items[item_type], 999]) == {items[item_type]: "alpha"}
        svc.remove_item(conn, "alpha", item_type, items[item_type])
        assert svc.item_ids(conn, "alpha", item_type) == []

    def test_put_moves_between_projects(self, conn, items):
        svc.create_project(conn, "Alpha")
        svc.create_project(conn, "Beta")
        svc.put_item(conn, "alpha", "task", items["task"])
        svc.put_item(conn, "beta", "task", items["task"])
        assert svc.item_ids(conn, "alpha", "task") == []
        assert svc.projects_of(conn, "task", [items["task"]]) == {items["task"]: "beta"}

    def test_same_id_different_types_dont_clash(self, conn, items):
        svc.create_project(conn, "Alpha")
        svc.create_project(conn, "Beta")
        svc.put_item(conn, "alpha", "task", 1)
        svc.put_item(conn, "beta", "document", 1)
        assert svc.projects_of(conn, "task", [1]) == {1: "alpha"}

    def test_unknown_item_or_type(self, conn, items):
        svc.create_project(conn, "Alpha")
        with pytest.raises(NotFound):
            svc.put_item(conn, "alpha", "task", 999)
        with pytest.raises(ProjectError):
            svc.put_item(conn, "alpha", "message", items["task"])
        with pytest.raises(NotFound):
            svc.remove_item(conn, "alpha", "task", items["task"])  # not in the project

    def test_archived_project_takes_no_new_items(self, conn, items):
        svc.create_project(conn, "Alpha")
        svc.update_project(conn, "alpha", status="archived")
        with pytest.raises(Conflict):
            svc.put_item(conn, "alpha", "task", items["task"])

    def test_unlink_on_item_delete(self, conn, items):
        svc.create_project(conn, "Alpha")
        svc.put_item(conn, "alpha", "cron", items["cron"])
        svc.unlink_item(conn, "cron", items["cron"])
        assert svc.get_project(conn, "alpha")["counts"]["cron"] == 0


class TestDelete:
    def test_refused_while_not_empty(self, conn, items):
        svc.create_project(conn, "Alpha")
        svc.put_item(conn, "alpha", "knowledge", items["knowledge"])
        with pytest.raises(Conflict):
            svc.delete_project(conn, "alpha")

    def test_empty_project_deleted_with_members(self, conn, items):
        svc.create_project(conn, "Alpha")
        svc.add_agent(conn, "alpha", "AKM")
        svc.delete_project(conn, "alpha")
        assert svc.list_projects(conn) == []
        svc.create_project(conn, "Alpha")  # no leftover membership rows
        assert svc.get_project(conn, "alpha")["agents"] == []
