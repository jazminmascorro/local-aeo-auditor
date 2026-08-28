"""Workspace / CSV ingest tests."""

from __future__ import annotations

from pathlib import Path

from aeo_auditor.workspaces import WorkspaceStore
from aeo_auditor.workspaces.ingest import ingest_csv, ingest_url_list, parse_locations_csv


def test_parse_locations_csv_aliases():
    csv_text = """store_id,store_name,state,location_url
A1,Main St,AZ,https://example.com/locations/az/x/main
A2,Bad Row,AZ,not-a-url
"""
    locs, meta = parse_locations_csv(csv_text)
    assert len(locs) == 1
    assert locs[0].location_id == "A1"
    assert locs[0].region == "AZ"
    assert meta["rows_skipped"] == 1


def test_workspace_csv_upsert(tmp_path: Path):
    store = WorkspaceStore(root=tmp_path / "workspaces")
    ws = store.create_workspace("Test Co", slug="test-co", allowed_domains=["example.com"])
    ingest_url_list(store, ws, ["https://example.com/locations/a"], source_label="demo")
    csv_text = "url,city,location_name\nhttps://example.com/locations/a,Phoenix,Store A\nhttps://example.com/locations/b,Tempe,Store B\n"
    result = ingest_csv(store, ws, csv_text, filename="t.csv")
    assert result["added"] == 1
    assert result["updated"] == 1
    locs = store.load_locations("test-co")
    assert len(locs) == 2
    a = next(l for l in locs if l.url.endswith("/a"))
    assert a.city == "Phoenix"
    assert "csv" in a.sources and "demo" in a.sources


def test_sample_dutch_bros_csv_parses():
    path = Path("clients/dutch-bros/sample_locations.csv")
    locs, meta = parse_locations_csv(path.read_text(encoding="utf-8"))
    assert len(locs) == 5
    assert all(l.in_csv for l in locs)
    assert meta["mapped_columns"]["url"] == "url"
