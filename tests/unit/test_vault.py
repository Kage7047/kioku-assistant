"""Vault: path confinement, mutations, transactional writes, BM25 search and the audit."""
import pytest

from kioku.memory import vault as V
from tests.conftest import write_note


# ---- confinement -----------------------------------------------------------------------
@pytest.mark.parametrize("rel", ["../outside.md", "notes/../../outside.md", "/etc/passwd"])
def test_reads_cannot_escape_the_vault(vault, rel):
    (vault.parent / "outside.md").write_text("secret")
    with pytest.raises(ValueError):
        V.read(rel)


@pytest.mark.parametrize("rel", ["../escape.md", "a/../../escape.md"])
def test_writes_cannot_escape_the_vault(vault, rel):
    with pytest.raises(ValueError):
        V.write(rel, "x")
    assert not (vault.parent / "escape.md").exists()


def test_symlink_out_of_the_vault_is_refused(vault, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keys.md").write_text("secret")
    (vault / "link").symlink_to(outside)
    with pytest.raises(ValueError):
        V.read("link/keys.md")


# ---- mutations -------------------------------------------------------------------------
def test_write_read_round_trip_creates_parents(vault):
    assert V.write("inbox/2026/idea.md", "# Idea") == "inbox/2026/idea.md"
    assert V.read("inbox/2026/idea.md") == "# Idea"


def test_list_dir_is_sorted_and_relative(vault):
    write_note(vault, "b.md", "")
    write_note(vault, "a.md", "")
    assert V.list_dir() == ["a.md", "b.md"]


def test_delete_and_move(vault):
    write_note(vault, "inbox/x.md", "x")
    V.move("inbox/x.md", "projects/x.md")
    assert (vault / "projects/x.md").read_text() == "x"
    V.delete("projects/x.md")
    assert not (vault / "projects/x.md").exists()


@pytest.mark.parametrize("rel", ["system/persona.md", "system", ".git/config"])
def test_protected_paths_cannot_be_deleted(vault, rel):
    write_note(vault, "system/persona.md", "persona")
    write_note(vault, ".git/config", "cfg")
    with pytest.raises(PermissionError):
        V.delete(rel)
    assert (vault / "system/persona.md").exists()


def test_protected_paths_cannot_be_moved_away(vault):
    write_note(vault, "system/persona.md", "persona")
    with pytest.raises(PermissionError):
        V.move("system/persona.md", "trash/persona.md")


def test_apply_writes_rolls_back_everything_on_failure(vault):
    write_note(vault, "a.md", "original")
    with pytest.raises(ValueError):
        V.apply_writes([
            {"path": "a.md", "content": "changed"},
            {"path": "new.md", "content": "new"},
            {"path": "../escape.md", "content": "boom"},     # fails → whole batch rolls back
        ])
    assert (vault / "a.md").read_text() == "original"
    assert not (vault / "new.md").exists()


# ---- search ----------------------------------------------------------------------------
def test_search_ranks_the_matching_note_first(vault):
    write_note(vault, "infra/queue.md", "Celery worker uses Redis as the broker and the result backend.")
    write_note(vault, "life/garden.md", "Tomatoes need sun. Water the basil every morning.")
    write_note(vault, "life/trip.md", "Lisbon trip: flights booked, hotel near Alfama.")
    hits = V.search("redis broker", k=3)
    assert hits[0]["path"] == "infra/queue.md"
    assert all(h["score"] > 0 for h in hits)


def test_search_skips_obsidian_internals_and_empty_vaults(vault):
    assert V.search("anything") == []
    write_note(vault, ".obsidian/workspace.md", "redis redis redis")
    assert V.search("redis") == []


def test_bm25_index_is_cached_until_the_vault_changes(vault):
    write_note(vault, "a.md", "alpha")
    write_note(vault, "b.md", "beta")
    V.search("alpha")
    first = V._bm25_cache["bm25"]
    V.search("beta")
    assert V._bm25_cache["bm25"] is first                # unchanged vault → reused
    write_note(vault, "c.md", "gamma")
    assert V.search("gamma")[0]["path"] == "c.md"        # new file → rebuilt
    assert V._bm25_cache["bm25"] is not first


# ---- audit -----------------------------------------------------------------------------
def test_audit_finds_orphans_and_dead_links(vault):
    write_note(vault, "hub.md", "See [[spoke]] and [[missing note]].")
    write_note(vault, "spoke.md", "Back to [[hub|the hub]].")
    write_note(vault, "lonely.md", "Nobody links here.")
    inv = V.audit_inventory()
    assert inv["file_count"] == 3
    assert inv["orphans"] == ["lonely.md"]
    assert inv["dead_links"] == ["hub.md -> [[missing note]]"]


def test_note_titles_maps_stems_to_paths(vault):
    write_note(vault, "people/Anna Kowalska.md", "")
    assert V.note_titles() == {"anna kowalska": "people/Anna Kowalska.md"}
