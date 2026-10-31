"""Tests for the provenance endpoints (/api/filings, /api/raw-facts, /api/lineage).

The offline tests exercise validation + the curated layers payload with no database and run
everywhere (including CI). The warehouse-backed happy path is gated like the repo's other
DB tests (skipped in CI) and tolerates the pre-rebuild state (503 'warming up') so it does not
fail before the gold view has been rebuilt with the accession column.
"""
import os

import pytest

from api.main import app


@pytest.fixture()
def client():
    return app.test_client()


def test_layers_payload(client):
    r = client.get('/api/lineage/layers')
    assert r.status_code == 200
    layers = r.get_json()["layers"]
    assert [l["id"] for l in layers] == ["bronze", "silver", "gold"]
    for l in layers:
        assert l["explanation"] and l["code"] and l["title"]


def test_lineage_requires_identity(client):
    r = client.get('/api/lineage/AAPL')
    assert r.status_code == 400
    assert r.get_json()["error"] == "bad_request"


def test_raw_facts_requires_accession(client):
    r = client.get('/api/raw-facts/AAPL')
    assert r.status_code == 400
    assert r.get_json()["error"] == "bad_request"


def test_layers_route_wins_over_ticker_route(client):
    # /api/lineage/layers must resolve to the static layers route, not /api/lineage/<ticker>.
    assert client.get('/api/lineage/layers').get_json().get("layers") is not None


@pytest.mark.skipif("CI" in os.environ, reason="needs warehouse")
def test_lineage_traces_aapl_revenue_to_filing(client):
    # Warehouse-backed end-to-end: a real reported number -> its source filing + EDGAR url.
    r = client.get('/api/lineage/AAPL', query_string={
        "concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "fiscal_year": "2024",
    })
    if r.status_code == 503:  # gold view not yet rebuilt with accession
        pytest.skip("gold.v_facts_hierarchical not yet rebuilt with accession")
    if r.status_code == 404:
        pytest.skip("AAPL FY2024 revenue not present in this warehouse")
    assert r.status_code == 200
    body = r.get_json()
    assert body["filing"]["accession"]
    assert body["edgar_url"] and body["edgar_url"].startswith("https://www.sec.gov/Archives/")


@pytest.mark.skipif("CI" in os.environ, reason="needs warehouse")
def test_filings_browser_lists_filings(client):
    r = client.get('/api/filings/AAPL')
    if r.status_code == 404:
        pytest.skip("no AAPL filings in this warehouse")
    assert r.status_code == 200
    body = r.get_json()
    assert body["count"] >= 1
    f = body["filings"][0]
    assert f["accession"] and f["fact_count"] >= 0
    assert f["edgar_url"].startswith("https://www.sec.gov/Archives/")
