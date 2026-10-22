"""End-to-end /bank flow through the real service layer (no fakes)."""

from pathlib import Path

from sqlalchemy import text

FIXTURES = Path(__file__).parent / "bank" / "parsers" / "fixtures"
ABN_IBAN = "NL91ABNA0417164300"


def _upload(client, bank_account_id, content):
    return client.post(
        "/bank/importeren",
        data={"bank_account_id": str(bank_account_id)},
        files={"file": ("afschrift.xml", content, "application/octet-stream")},
        follow_redirects=False,
    )


def test_upload_preview_confirm_and_reimport(client):
    with client.app.state.engine.connect() as conn:
        asset_id = conn.execute(text("SELECT id FROM account WHERE code = '1210'")).scalar()
    r = client.post(
        "/bank/rekeningen/nieuw",
        data={"name": "Zakelijk", "iban": ABN_IBAN, "bank": "abn_amro", "account_id": str(asset_id)},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    with client.app.state.engine.connect() as conn:
        ba_id = conn.execute(text("SELECT id FROM bank_account")).scalar()

    content = (FIXTURES / "camt053_002.xml").read_bytes()
    up = _upload(client, ba_id, content)
    assert up.status_code == 303, up.text
    batch_url = up.headers["location"]
    assert client.get(batch_url).status_code == 200

    done = client.post(batch_url + "/bevestigen", data={}, follow_redirects=True)
    assert done.status_code == 200, done.text
    with client.app.state.engine.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM bank_transaction")).scalar()
    assert n > 0
    assert client.get("/bank").status_code == 200

    again = _upload(client, ba_id, content)
    assert again.status_code in (200, 303)
    if again.status_code == 303:
        preview = client.get(again.headers["location"]).text
        assert "al geïmporteerd" in preview
    with client.app.state.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM bank_transaction")).scalar() == n
