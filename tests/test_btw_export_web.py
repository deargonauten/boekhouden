"""Download routes of the BTW-aangifte. The router is mounted locally (Part B registers it in routes.py)."""

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.web.btw_export_routes import router
from tests.vat.vat_helpers import Book, make_contact, link_invoice, set_company

BASE = "/btw/2026/quarter/3"


@pytest.fixture
def api(client):
    if not any(getattr(r, "path", "") == f"/btw/{{year}}/{{kind}}/{{number}}/pdf" for r in client.app.routes):
        client.app.include_router(router)
    with Session(client.app.state.engine) as s:
        set_company(s)
        book = Book(s)
        book.sale(100000, 21000, day=date(2026, 8, 15))
        eu = book.post([("1210", 50000, 0), ("8400", 0, 50000, "EU_GOEDEREN")], day=date(2026, 8, 20), journal="VK")
        link_invoice(s, eu, make_contact(s))
        s.commit()
    return client


def test_pdf_download(api):
    r = api.get(f"{BASE}/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'attachment; filename="btw-aangifte-2026-Q3.pdf"'
    assert r.content.startswith(b"%PDF")


def test_rubrieken_csv_download(api):
    r = api.get(f"{BASE}/rubrieken.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="btw-aangifte-2026-Q3-rubrieken.csv"'
    text = r.content.decode("utf-8-sig")
    assert r.content.startswith(b"\xef\xbb\xbf")
    assert "1a;" in text and "210,00" in text
    assert "5g;" in text


def test_icp_csv_download(api):
    r = api.get(f"{BASE}/icp.csv")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="btw-icp-2026-Q3.csv"'
    lines = r.content.decode("utf-8-sig").split("\r\n")
    assert lines[0] == "landcode;btw_nummer;goederen;diensten;driehoek"
    assert lines[1] == "DE;123456789;500;0;0"


def test_kwartaal_alias_and_month(api):
    assert api.get("/btw/2026/kwartaal/3/pdf").status_code == 200
    r = api.get("/btw/2026/month/8/icp.csv")
    assert r.status_code == 200
    assert 'filename="btw-icp-2026-M08.csv"' in r.headers["content-disposition"]


@pytest.mark.parametrize(
    "path",
    [
        "/btw/2026/quarter/5", "/btw/2026/quarter/0", "/btw/2026/month/13", "/btw/2026/week/1",
        "/btw/abcd/quarter/1", "/btw/2026/quarter/x", "/btw/0/quarter/1", "/btw/2026/quarter/-1",
        "/btw/2026/quarter/%00",
    ],
)
@pytest.mark.parametrize("tail", ["pdf", "rubrieken.csv", "icp.csv"])
def test_invalid_period_is_404_with_plain_message(api, path, tail):
    r = api.get(f"{path}/{tail}")
    assert r.status_code == 404
    assert "Deze periode bestaat niet" in r.text
    assert "Traceback" not in r.text


def test_unknown_year_without_fiscal_year_still_exports_empty_concept(api):
    r = api.get("/btw/2031/quarter/1/rubrieken.csv")
    assert r.status_code in (200, 409)
    if r.status_code == 409:
        assert "boekjaar" in r.text.lower()


def test_icp_csv_includes_sale_without_klant(api):
    with Session(api.app.state.engine) as s:
        book = Book.__new__(Book)
        book.s = s
        book.post([("1210", 70_000, 0), ("8400", 0, 70_000, "EU_GOEDEREN")], day=date(2026, 8, 5), desc="Levering", journal="VK")
        s.commit()
    r = api.get(f"{BASE}/icp.csv")
    assert "ONBEKEND;;700;0;0" in r.text
