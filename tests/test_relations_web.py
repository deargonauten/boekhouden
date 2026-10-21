"""Web tests for /relaties (UI part). Domain validation is tested in tests/domain."""

import re

import pytest

KVK = "12345678"
BTW = "NL123456789B01"
IBAN = "NL91ABNA0417164300"


def data(**over):
    base = {"name": "Jansen Installatie", "is_supplier": "1"}
    base.update(over)
    return base


def add(client, **over):
    r = client.post("/relaties/nieuw", data=data(**over), follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rsplit("=", 1)[1])


def test_sidebar_relaties_is_not_the_placeholder(client):
    r = client.get("/relaties")
    assert r.status_code == 200
    assert "nog in ontwikkeling" not in r.text


def test_empty_state_explains_relations(client):
    html = client.get("/relaties").text
    assert "Je hebt nog geen relaties" in html
    assert 'href="/relaties/nieuw"' in html


def test_new_form_defaults(client):
    html = client.get("/relaties/nieuw").text
    assert re.search(r'name="is_supplier"[^>]*\schecked', html)
    assert not re.search(r'name="is_customer"[^>]*\schecked', html)
    assert 'name="country" value="NL"' in html
    assert "Bedrijfsnummer Kamer van Koophandel (KvK-nummer)" in html
    assert "8 cijfers, staat op de factuur of in het Handelsregister." in html
    assert "Begint met NL, bijvoorbeeld NL123456789B01." in html
    assert "Wordt gebruikt om betalingen straks automatisch" in html


def test_new_form_prefill_from_query(client):
    html = client.get("/relaties/nieuw?soort=klant&naam=Bakkerij+Piet").text
    assert re.search(r'name="is_customer"[^>]*\schecked', html)
    assert not re.search(r'name="is_supplier"[^>]*\schecked', html)
    assert 'value="Bakkerij Piet"' in html


def test_create_redirects_with_confirmation(client):
    r = client.post("/relaties/nieuw", data=data(kvk=KVK), follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/relaties")
    page = client.get(r.headers["location"]).text
    assert "Relatie Jansen Installatie is toegevoegd." in page
    assert "Jansen Installatie" in page and KVK in page


def test_invalid_post_lists_all_errors_and_keeps_values(client):
    r = client.post(
        "/relaties/nieuw",
        data={"name": "Foutief", "kvk": "123", "city": "Utrecht"},
    )
    assert r.status_code == 422
    assert 'role="alert"' in r.text
    assert "Een KvK-nummer bestaat uit 8 cijfers" in r.text
    assert "Kies of dit een klant, een leverancier of allebei is." in r.text
    assert 'value="Foutief"' in r.text and 'value="123"' in r.text
    assert 'value="Utrecht"' in r.text


def test_duplicate_kvk_gives_409_with_other_name(client):
    add(client, kvk=KVK)
    r = client.post("/relaties/nieuw", data=data(name="Tweede", kvk=KVK))
    assert r.status_code == 409
    assert "Jansen Installatie" in r.text
    assert 'value="Tweede"' in r.text


def test_edit_prefilled_and_saves(client):
    cid = add(client, kvk=KVK, city="Zwolle")
    html = client.get(f"/relaties/{cid}/bewerken").text
    assert 'value="Jansen Installatie"' in html and f'value="{KVK}"' in html
    r = client.post(
        f"/relaties/{cid}/bewerken",
        data=data(name="Jansen BV", kvk=KVK, city="Kampen"),
        follow_redirects=False,
    )
    assert r.status_code == 303
    page = client.get("/relaties").text
    assert "Jansen BV" in page and "Kampen" in page and "Zwolle" not in page


def test_edit_invalid_rerenders_422(client):
    cid = add(client)
    r = client.post(f"/relaties/{cid}/bewerken", data=data(kvk="12"))
    assert r.status_code == 422
    assert "Een KvK-nummer bestaat uit 8 cijfers" in r.text


def test_unknown_id_is_404(client):
    assert client.get("/relaties/999/bewerken").status_code == 404
    assert client.post("/relaties/999/bewerken", data=data()).status_code == 404
    assert client.post("/relaties/999/archiveren").status_code == 404
    assert client.post("/relaties/999/herstellen").status_code == 404


def test_archive_and_restore(client):
    cid = add(client)
    r = client.post(f"/relaties/{cid}/archiveren", follow_redirects=False)
    assert r.status_code == 303
    assert "Jansen Installatie" not in client.get("/relaties").text
    shown = client.get("/relaties?gearchiveerd=1").text
    assert "Jansen Installatie" in shown and "Gearchiveerd" in shown
    assert 'class="inactive"' in shown
    client.post(f"/relaties/{cid}/herstellen")
    page = client.get("/relaties").text
    assert "Jansen Installatie" in page and "Gearchiveerd" not in page


def test_archive_button_explains_itself(client):
    add(client)
    html = client.get("/relaties").text
    assert (
        'title="Verbergt de relatie in lijsten; bestaande boekingen en facturen blijven bewaard."'
        in html
    )


def test_filter_on_soort_and_search(client):
    add(client, name="Leverancier Een", is_supplier="1", city="Delft")
    add(client, name="Klant Twee", is_customer="1", is_supplier="", kvk=KVK, iban=IBAN)
    add(client, name="Beide Drie", is_customer="1", is_supplier="1")
    klanten = client.get("/relaties?soort=klant").text
    assert "Klant Twee" in klanten and "Beide Drie" in klanten and "Leverancier Een" not in klanten
    lev = client.get("/relaties?soort=leverancier").text
    assert "Leverancier Een" in lev and "Beide Drie" in lev and "Klant Twee" not in lev
    assert "Klant Twee" in client.get(f"/relaties?q={KVK}").text
    assert "Leverancier Een" in client.get("/relaties?q=delft").text
    assert "Leverancier Een" not in client.get("/relaties?q=delft&soort=klant").text


def test_list_shows_soort_and_formatted_iban(client):
    add(client, name="Beide", is_customer="1", is_supplier="1", iban=IBAN)
    html = client.get("/relaties").text
    assert "Beide" in html
    assert "NL91 ABNA 0417 1643 00" in html


def test_no_delete_route_or_button(client):
    cid = add(client)
    for method, path in (
        ("delete", f"/relaties/{cid}"),
        ("post", f"/relaties/{cid}/verwijderen"),
        ("delete", f"/relaties/{cid}/verwijderen"),
        ("get", f"/relaties/{cid}/verwijderen"),
    ):
        assert getattr(client, method)(path).status_code in (404, 405), (method, path)
    html = client.get("/relaties?gearchiveerd=1").text + client.get(f"/relaties/{cid}/bewerken").text
    assert "verwijder" not in html.lower()


@pytest.mark.parametrize("path", ["/relaties", "/relaties/nieuw"])
def test_pages_render(client, path):
    assert client.get(path).status_code == 200


def add_many(client, n, **over):
    for i in range(n):
        add(client, name=f"Relatie {i:03d}", **over)


def test_list_uses_tabs_pills_and_icon_actions(client):
    add(client, name="Beide", is_customer="1", is_supplier="1")
    html = client.get("/relaties").text
    assert 'class="tabs"' in html and "Klanten" in html and "Leveranciers" in html
    assert html.count('aria-current="page"') == 2  # sidebar + active tab
    assert "pill--success" in html and ">Actief<" in html
    assert 'aria-label="Relatie bewerken"' in html and 'aria-label="Relatie archiveren"' in html
    assert "Toont 1-1 van 1 relaties" in html
    assert 'href="/static/css/relations.css"' in html


def test_soort_tab_is_current_and_keeps_params(client):
    add(client, name="Klant Een", is_customer="1", is_supplier="")
    html = client.get("/relaties?soort=klant&q=klant&gearchiveerd=1").text
    assert re.search(r'<a href="[^"]*soort=klant[^"]*" aria-current="page"', html)
    assert re.search(r'<a href="/relaties\?q=klant&amp;gearchiveerd=1"', html)
    assert re.search(r'name="gearchiveerd"[^>]*\schecked', html)


def test_pagination_50_per_page_and_total(client):
    add_many(client, 53)
    first = client.get("/relaties").text
    assert "Toont 1-50 van 53 relaties" in first
    assert "Relatie 000" in first and "Relatie 049" in first and "Relatie 050" not in first
    second = client.get("/relaties?page=2").text
    assert "Toont 51-53 van 53 relaties" in second
    assert "Relatie 050" in second and "Relatie 049" not in second


def test_page_is_clamped_and_garbage_ignored(client):
    add_many(client, 51)
    assert "Toont 51-51 van 51 relaties" in client.get("/relaties?page=999").text
    for bad in ("0", "-3", "abc", ""):
        r = client.get(f"/relaties?page={bad}")
        assert r.status_code == 200
        assert "Toont 1-50 van 51 relaties" in r.text


def test_pager_links_keep_filters(client):
    add_many(client, 51, is_customer="1", is_supplier="")
    html = client.get("/relaties?soort=klant&q=relatie").text
    assert re.search(r'href="/relaties\?soort=klant&amp;q=relatie&amp;page=2"', html)


def test_no_match_shows_wis_filters(client):
    add(client)
    html = client.get("/relaties?q=nietbestaand").text
    assert "Geen relaties gevonden" in html
    assert ">Wis filters<" in html and 'href="/relaties"' in html


def test_restore_button_for_archived(client):
    cid = add(client)
    client.post(f"/relaties/{cid}/archiveren")
    html = client.get("/relaties?gearchiveerd=1").text
    assert 'aria-label="Relatie herstellen"' in html and "Gearchiveerd" in html


def test_form_has_cards_and_breadcrumb(client):
    html = client.get("/relaties/nieuw").text
    for heading in ("Algemeen", "Bedrijfsgegevens", "Adres en contact"):
        assert f"<h2>{heading}</h2>" in html
    assert 'class="breadcrumb"' in html and "Nieuwe relatie" in html
    assert 'class="form-actions"' in html


@pytest.mark.parametrize(
    "path", ["/relaties", "/relaties/nieuw", "/relaties?soort=klant", "/relaties?q=zzz"]
)
def test_relations_pages_are_plain_language(client, path):
    from tests.web_helpers import assert_plain_language

    add(client)
    assert_plain_language(client, path)
