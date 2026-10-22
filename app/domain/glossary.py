"""Central glossary of bookkeeping terms shown in the UI.

Every bookkeeping/tax term that appears on a screen is explained here once
(plain Dutch first, the term second). Pure Python: no web or DB imports.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    key: str  # lowercase ascii slug, [a-z][a-z0-9_]*
    term: str  # bookkeeping term as displayed
    plain: str  # short plain-Dutch phrase
    explanation: str  # 1-2 sentences, max 220 chars
    detect: tuple[str, ...] = ()  # regexes (case-insensitive) that signal the term on a screen

    def patterns(self) -> tuple[str, ...]:
        """Detection regexes; defaults to the whole term as a word."""
        return self.detect or (rf"\b{re.escape(self.term)}\b",)


# A regex that never matches: for terms too generic to demand an icon wherever they occur.
_NEVER = r"(?!x)x"

_TERMS: list[Term] = [
    Term("grootboek", "Grootboek", "Lijst met al je rekeningen",
         "Het grootboek is de complete lijst van rekeningen waarop alles wordt vastgelegd, zoals Bank, Omzet en Kantoorkosten. Het programma stelt meestal zelf de juiste rekening voor."),
    Term("grootrekening", "Grootrekening", "Rekening",
         "Eén rekening uit het grootboek, bijvoorbeeld Bank of Kantoorkosten. Bij elke boeking geef je aan op welke rekeningen geld erbij of eraf gaat."),
    Term("dagboek", "Dagboek", "Map voor boekingen van dezelfde soort",
         "Een map waarin boekingen van dezelfde soort bij elkaar staan, bijvoorbeeld alle bankmutaties of alle verkoopfacturen.",
         (r"\bdagboek(en)?\b",)),
    Term("memoriaal", "Memoriaal", "Overige boekingen",
         "De map voor boekingen die nergens anders bij horen, zoals correcties of de beginbalans. Hier leg je ook zelf handmatig iets vast."),
    Term("verkoopdagboek", "Verkoopdagboek", "Verkoopfacturen",
         "Hier staan de facturen die jij aan klanten stuurt. Zo zie je wat klanten je nog moeten betalen."),
    Term("inkoopdagboek", "Inkoopdagboek", "Inkoopfacturen",
         "Hier staan de facturen die jij van leveranciers krijgt. Zo zie je wat je nog moet betalen."),
    Term("bankdagboek", "Bankdagboek", "Bankmutaties",
         "Hier staan de bij- en afschrijvingen van één bankrekening. Elke bankrekening heeft zijn eigen map."),
    Term("kasdagboek", "Kasdagboek", "Contant geld",
         "Hier staat het geld dat je contant ontvangt of uitgeeft. Het saldo hoort overeen te komen met wat er echt in de kas zit."),
    Term("boeking", "Boeking", "Vastgelegde gebeurtenis",
         "Een boeking legt vast dat er geld is ontvangen, uitgegeven of verschoven, met datum en omschrijving. Je kunt een boeking niet wijzigen, maar wel ongedaan maken.",
         (_NEVER,)),
    Term("boekstuk", "Boekstuk", "Volgnummer van de boeking",
         "Het unieke nummer van een boeking, bijvoorbeeld 2026-0001. Zo vind je een boeking altijd terug en ontbreekt er nooit een nummer."),
    Term("debet", "Debet", "Linkerkant van een boeking",
         "De ene kant van een boeking. Hier staat waar het geld naartoe gaat of wat je erbij krijgt, zoals geld op je bank of een gemaakte kost."),
    Term("credit", "Credit", "Rechterkant van een boeking",
         "De andere kant van een boeking. Hier staat waar het geld vandaan komt, zoals een verkoop of een schuld die erbij komt."),
    Term("storno", "Storno", "Boeking ongedaan maken",
         "Een boeking verwijderen mag niet. Met een stornoboeking maak je hem ongedaan: er komt een tegengestelde boeking bij en de eerste blijft zichtbaar."),
    Term("boekjaar", "Boekjaar", "Jaar van je administratie",
         "Het jaar waarover je je administratie bijhoudt, meestal een kalenderjaar. Elk boekjaar bestaat uit 12 maanden waarin je kunt boeken."),
    Term("periode", "Periode", "Maand in een boekjaar",
         "Een maand van het boekjaar. Is een maand vergrendeld, dan kun je er niets meer in boeken; zo blijven afgesloten cijfers kloppen.",
         (r"\bperiodes?\b",)),
    Term("vergrendelen", "Vergrendelen", "Maand dichtzetten",
         "Je zet een maand definitief op slot. Daarna kun je er niets meer in boeken, wijzigen of ongedaan maken, en je kunt het zelf niet terugdraaien.",
         (r"\bvergrendel(en)?\b",)),
    Term("afsluiten", "Afsluiten", "Jaar dichtzetten",
         "Je zet alle maanden van het jaar op slot. Doe dit pas als je alle boekingen van dat jaar hebt gecontroleerd; terugdraaien kan niet.",
         (r"\bafsluiten\b",)),
    Term("btw", "Btw", "Omzetbelasting",
         "Belasting die je over verkopen rekent en over inkopen betaalt. Het verschil draag je af aan de Belastingdienst, meestal per kwartaal.",
         (r"\bbtw\b(?!-code|-nummer|-identificatie)",)),
    Term("btw_code", "Btw-code", "Btw-tarief van de regel",
         "Bepaalt welk btw-percentage bij een regel hoort, bijvoorbeeld 21%, 9% of 0%. Hiermee vult het programma later je btw-aangifte in.",
         (r"\bbtw-code\b",)),
    Term("rgs", "RGS", "Standaardnummering van rekeningen",
         "Referentiegrootboekschema: een landelijke standaard voor rekeningnummers en namen, zodat je boekhouder en de Belastingdienst alles herkennen."),
    Term("activa", "Activa", "Wat je bezit",
         "Alles wat je bezit of nog tegoed hebt, zoals geld op de bank, een laptop of een factuur die nog betaald moet worden."),
    Term("passiva", "Passiva", "Wat je schuldig bent",
         "Alles wat je schuldig bent aan anderen, zoals een nog te betalen factuur of een lening. Ook de btw die je nog moet afdragen hoort hier."),
    Term("eigen_vermogen", "Eigen vermogen", "Wat van jou is",
         "Wat er overblijft als je alles wat je schuldig bent aftrekt van wat je bezit. Dit is het geld dat in je onderneming zit."),
    Term("opbrengsten", "Opbrengsten", "Wat je verdient",
         "Het geld dat je verdient met je werk of producten, zoals omzet uit verkopen. Dit telt mee voor je winst."),
    Term("kosten", "Kosten", "Wat je uitgeeft",
         "Het geld dat je uitgeeft om je bedrijf te laten draaien, zoals kantoorbenodigdheden of huur. Dit verlaagt je winst."),
    Term("systeemrekening", "Systeemrekening", "Standaardrekening van het programma",
         "Standaardrekening die het programma zelf nodig heeft; je kunt hem niet hernoemen of verwijderen.",
         (r"\bsysteem(rekening)?\b",)),
    Term("debiteuren", "Debiteuren", "Klanten die nog moeten betalen",
         "Het bedrag dat klanten je nog schuldig zijn voor facturen die je hebt gestuurd."),
    Term("crediteuren", "Crediteuren", "Leveranciers die je nog moet betalen",
         "Het bedrag dat je nog moet betalen voor facturen die je hebt ontvangen."),
    Term("balans_evenwicht", "Debet = credit", "Beide kanten even groot",
         "Elke boeking heeft twee kanten die samen precies even groot moeten zijn. Is dat niet zo, dan zegt het programma hoeveel er ontbreekt.",
         (_NEVER,)),
    Term("referentie", "Referentie", "Kenmerk van de boeking",
         "Een eigen kenmerk, zoals een factuurnummer, zodat je de boeking later makkelijk terugvindt."),
    Term("inbox", "Inbox", "Nog te verwerken documenten",
         "Hier komen facturen en bonnen binnen die nog verwerkt moeten worden, bijvoorbeeld door ze zelf toe te voegen of uit je mailbox."),
    Term("status_nieuw", "Nieuw", "Nog niet bekeken",
         "Het document staat in je inbox maar is nog niet uitgelezen of geboekt.",
         (_NEVER,)),
    Term("status_herkend", "Herkend", "Gegevens uitgelezen, wacht op jouw controle",
         "De gegevens van de factuur (leverancier, datum, bedragen) zijn uitgelezen. Controleer ze voordat je boekt.",
         (_NEVER,)),
    Term("status_geboekt", "Geboekt", "Vastgelegd in je administratie",
         "Van dit document is een boeking gemaakt. Het document blijft bij de boeking bewaard.",
         (_NEVER,)),
    Term("bewaarplicht", "Bewaarplicht", "Je moet administratie 7 jaar bewaren",
         "De wet verplicht je facturen en bonnen 7 jaar te bewaren. Daarom kun je documenten hier niet verwijderen.",
         (r"\bbewaarplicht\b",)),
    Term("vingerafdruk", "Vingerafdruk van het bestand", "Unieke code van de inhoud",
         "Een korte code die bij de inhoud van het bestand hoort. Hetzelfde bestand krijgt altijd dezelfde code, zo ziet het programma dat je iets dubbel toevoegt.",
         (r"\bvingerafdruk\b",)),
    Term("relaties", "Relaties", "Klanten en leveranciers",
         "De bedrijven en personen met wie je zakendoet: je klanten en je leveranciers."),
    Term("kvk", "KvK-nummer", "Inschrijfnummer van je bedrijf",
         "Het nummer van 8 cijfers waarmee een bedrijf bij de Kamer van Koophandel staat ingeschreven. Je vindt het op facturen van bedrijven en in het Handelsregister.",
         (r"\bkvk(-nummer)?\b",)),
    Term("btw_nummer", "Btw-nummer", "Btw-identificatienummer van een bedrijf",
         "Een nummer als NL123456789B01 waarmee een bedrijf bekend is voor de btw. Je hebt het nodig voor een kloppende btw-aangifte en voor inkopen in andere EU-landen.",
         (r"\bbtw-nummer\b",)),
    Term("iban", "IBAN", "Bankrekeningnummer",
         "Het internationale bankrekeningnummer, bijvoorbeeld NL91 ABNA 0417 1643 00. Hiermee herkent het programma van wie een betaling komt of aan wie je betaalt.",
         (r"\biban\b",)),
    Term("bedrijfsgegevens", "Mijn bedrijfsgegevens", "Wie jij als ondernemer bent",
         "Je eigen naam, adres, KvK-nummer, btw-id en bankrekening. Ze komen op je verkoopfacturen en in je btw-aangifte, dus vul ze één keer goed in.",
         (_NEVER,)),  # the word is also a plain heading on the relatie form
    Term("btw_id", "Btw-id", "Jouw btw-identificatienummer",
         "Een nummer als NL123456789B01. Je zet het op elke verkoopfactuur en je hebt het nodig voor je btw-aangifte. Je vindt het op brieven van de Belastingdienst.",
         (r"\bbtw-id\b",)),
    Term("handelsnaam", "Handelsnaam", "Naam waaronder je zaken doet",
         "De naam waaronder je naar buiten treedt, als die anders is dan je eigen naam. Heb je geen aparte naam, dan laat je dit leeg.",
         (r"\bhandelsnaam\b",)),
    Term("rechtsvorm", "Rechtsvorm", "Soort onderneming",
         "Eenmanszaak als je alleen onderneemt, VOF als je samen met een partner een bedrijf runt. Een BV hoort hier niet bij.",
         (r"\brechtsvorm\b",)),
    Term("klant", "Klant", "Iemand aan wie je verkoopt",
         "Een persoon of bedrijf aan wie jij producten of diensten levert en een factuur stuurt.",
         (_NEVER,)),
    Term("leverancier", "Leverancier", "Iemand bij wie je inkoopt",
         "Een persoon of bedrijf bij wie jij producten of diensten afneemt en van wie je een factuur krijgt.",
         (_NEVER,)),
    Term("archiveren", "Archiveren", "Verbergen zonder te verwijderen",
         "De relatie verdwijnt uit je lijsten, maar blijft bewaard. Bestaande boekingen en facturen houden hun koppeling; de wet vraagt om je administratie 7 jaar te bewaren."),
    Term("rapportages", "Rapportages", "Overzichten en cijfers",
         "Overzichten van je cijfers, zoals winst en verlies en wat je bezit en schuldig bent."),
    Term("bank", "Bank", "Bij- en afschrijvingen",
         "Hier verwerk je de bij- en afschrijvingen van je bankrekening."),
    Term("kas", "Kas", "Contant geld",
         "Het geld dat je contant hebt, bijvoorbeeld in een kassa of portemonnee van het bedrijf."),
    # Invoice extraction (uitlezen en nakijken)
    Term("uitlezen", "Uitlezen", "Door Claude laten lezen",
         "Het programma leest leverancier, datum en bedragen uit je PDF of foto. Jij controleert altijd het resultaat voordat er iets wordt vastgelegd.",
         (_NEVER,)),
    Term("nakijken", "Nakijken", "Controleren wat is uitgelezen",
         "Je legt de uitgelezen gegevens naast de originele factuur, past aan wat niet klopt en bevestigt dan met 'Klaar met nakijken'.",
         (_NEVER,)),
    Term("btw_tarief", "BTW-tarief", "Hoeveel procent BTW",
         "Het percentage BTW dat op de factuur staat: 21%, 9% of 0%. Soms staat er 'BTW verlegd': dan rekent jouw klant de BTW af.",
         (_NEVER,)),
    Term("verlegd", "BTW verlegd", "De klant rekent de BTW af",
         "Bij 'BTW verlegd' staat er geen BTW op de factuur. De klant geeft de BTW zelf aan bij de Belastingdienst, niet de leverancier.",
         (_NEVER,)),
    Term("creditnota", "Creditnota", "Een factuur die geld terugtelt",
         "Een creditnota maakt een eerdere factuur helemaal of deels ongedaan, bijvoorbeeld bij een retour of korting achteraf."),
    Term("factuurdatum", "Factuurdatum", "Datum op de factuur",
         "De datum die op de factuur staat. Aan die datum zie je in welke maand en in welk btw-kwartaal de factuur hoort.",
         (_NEVER,)),
    Term("vertrouwen", "Controleer-markering", "Hier is het programma niet zeker van",
         "Bij 'Controleer' of 'Onzeker' heeft het programma de waarde lastig kunnen lezen of klopt de som niet. Kijk dit veld extra goed na.",
         (_NEVER,)),
    Term("claude_abonnement", "Claude-abonnement", "Uitlezen via je eigen Claude-account",
         "Het uitlezen gebruikt je eigen Claude-account, zonder extra kosten buiten je abonnement. Alternatief: zet een API-sleutel in .env en betaal per factuur.",
         (_NEVER,)),
    Term("rubriek", "Rubriek", "Vakje in de btw-aangifte",
         "Een genummerd vakje op het btw-formulier, zoals 1a of 5b. Het programma zet elk bedrag in het juiste vakje op basis van de btw-code.",
         (r"\brubriek(?:en)?\b",)),
    Term("standaard_btw", "Standaard btw-tarief", "Tarief dat vooraf wordt ingevuld",
         "Het btw-tarief dat het programma voorstelt als je deze rekening kiest. Je kunt het bij elke boeking nog aanpassen."),
    Term("selecteerbaar_bij", "Selecteerbaar bij", "Waar de rekening in de lijst staat",
         "Bepaalt in welke keuzelijsten de rekening verschijnt: bij inkoop, verkoop of bank. Zo houd je de lijst kort en kies je sneller de goede rekening."),
    Term("voorbelasting", "Voorbelasting", "Btw die je terugkrijgt",
         "De btw op je inkopen en kosten, die je mag aftrekken van de btw die je zelf afdraagt. Hij komt op rekening 1400 (BTW voorbelasting).",
         (r"\bvoorbelasting\b",)),
    # Inkoop booking (inkoopfactuur boeken, crediteuren)
    Term("inkoopfactuur", "Inkoopfactuur", "Factuur van een leverancier",
         "Een factuur die je van een leverancier hebt gekregen en nog moet betalen. Na het boeken staat hij bij Inkoop, met een link naar de boeking en het bestand.",
         (_NEVER,)),
    Term("goedkeuren_boeken", "Boeken", "Vastleggen in je administratie",
         "Met boeken leg je de factuur definitief vast. Daarna pas je hem niet meer aan: is er iets fout, dan maak je een stornoboeking (ongedaan maken).",
         (_NEVER,)),
    Term("openstaand", "Openstaand", "Nog te betalen",
         "Het deel van een factuur dat je nog niet hebt betaald. Een creditnota telt negatief mee, want die verlaagt wat je schuldig bent.",
         (_NEVER,)),
    Term("leerfunctie", "Leerfunctie", "Onthouden per leverancier",
         "Het programma onthoudt welke rekening en btw-code je de vorige keer bij deze leverancier koos en stelt die voor. Jij bevestigt altijd zelf.",
         (_NEVER,)),
    Term("kor", "KOR", "Kleineondernemersregeling",
         "Met de KOR reken je geen btw aan en trek je ook geen btw af, zolang je omzet onder de grens blijft. Je doet dan geen btw-aangifte."),
    # Bankafschriften importeren
    Term("bankrekening", "Bankrekening", "Je rekening bij de bank",
         "Je zakelijke rekening bij de bank. Elke bankrekening hoort bij precies één grootboekrekening, zodat het programma later weet waar het geld heen gaat.",
         (_NEVER,)),
    Term("bankafschrift", "Bankafschrift", "Overzicht van bij- en afschrijvingen",
         "Een bestand met alle bij- en afschrijvingen van je rekening over een bepaalde tijd. Je downloadt het in het internetbankieren van je bank.",
         (r"\bbankafschrift(en)?\b",)),
    Term("camt053", "CAMT.053", "Bankbestand (XML)",
         "Het standaard XML-bestand dat de meeste banken aanbieden voor afschriften. Het is het betrouwbaarste formaat: kies dit als je bank het heeft.",
         (r"\bcamt\.?053\b",)),
    Term("mt940", "MT940", "Bankbestand (oud formaat)",
         "Een ouder formaat voor bankafschriften, vaak met de extensie .sta of .txt. Het programma kan het lezen als je bank geen CAMT.053 aanbiedt.",
         (r"\bmt940\b",)),
    Term("csv_export", "CSV", "Bankbestand voor Excel",
         "Een tabel als tekstbestand, zoals je die uit internetbankieren voor Excel downloadt. Het programma herkent de exports van ING, Rabobank, ABN AMRO en bunq.",
         (r"\bcsv\b",)),
    Term("bijschrijving_afschrijving", "Bij / Af", "Geld erbij / geld eraf",
         "Bij betekent dat er geld op je rekening kwam, Af dat er geld van je rekening ging. In de lijst staat bij in groen en af in rood.",
         (_NEVER,)),
    Term("saldo_na_mutatie", "Saldo na mutatie", "Bedrag op je rekening erna",
         "Het bedrag dat na deze bij- of afschrijving op je bankrekening stond, zoals je bank het op het afschrift zet. Niet elk bestand bevat dit; dan blijft het leeg.",
         (_NEVER,)),
    Term("dubbele_transactie", "Dubbele transactie", "Staat er al",
         "Het programma controleert of een regel al eerder is ingelezen. 'Mogelijk dubbel' betekent: zelfde datum, bedrag en tegenpartij, maar andere tekst. Kijk of het echt dezelfde betaling is.",
         (_NEVER,)),
    Term("transactie", "Transactie", "Een bij- of afschrijving",
         "Eén regel op je bankafschrift: geld dat op je rekening kwam of eraf ging. Ingelezen transacties kun je niet meer wijzigen.",
         (_NEVER,)),
]

GLOSSARY: dict[str, Term] = {t.key: t for t in _TERMS}
if len(GLOSSARY) != len(_TERMS):
    raise RuntimeError("Duplicate glossary key")


def get_term(key: str) -> Term:
    try:
        return GLOSSARY[key]
    except KeyError:
        raise KeyError(f"Unknown glossary key: {key!r}") from None


def all_terms() -> list[Term]:
    return list(GLOSSARY.values())


def terms_alphabetical() -> list[Term]:
    """All terms sorted by the plain-Dutch phrase first, for the help page."""
    return sorted(_TERMS, key=lambda t: (t.plain.lower(), t.term.lower()))
