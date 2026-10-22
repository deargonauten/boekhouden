"""Seed data for the core ledger (plain data; imported by migration 0002).

RGS codes are best-effort references (RGS 3.x). Codes that could not be
verified against the public RGS reference are left None rather than guessed
(TODO verify: all accounts with rgs_code None).
"""
from typing import NamedTuple


class SeedAccount(NamedTuple):
    code: str
    name: str
    type: str  # asset | liability | equity | revenue | expense
    rgs_code: str | None = None
    is_system: bool = False
    default_vat_code: str | None = None


A, L, E, R, X = "asset", "liability", "equity", "revenue", "expense"

SEED_ACCOUNTS: list[SeedAccount] = [
    # Assets
    SeedAccount("0100", "Inventaris", A),
    SeedAccount("0110", "Computers en apparatuur", A),
    SeedAccount("0120", "Bedrijfsauto", A),
    SeedAccount("0190", "Cumulatieve afschrijvingen", A, is_system=True),
    SeedAccount("1100", "Kas", A, "BLimKas", True),
    SeedAccount("1210", "Bank", A, "BLimBan", True),
    SeedAccount("1220", "Spaarrekening", A),
    SeedAccount("1230", "Kruisposten / nog te boeken", A, None, True),
    SeedAccount("1300", "Debiteuren", A, "BVorDeb", True),
    SeedAccount("1310", "Overige vorderingen", A),
    SeedAccount("1320", "Vooruitbetaalde kosten", A),
    SeedAccount("1400", "BTW voorbelasting (te vorderen)", A, None, True),
    SeedAccount("1410", "BTW verlegd - voorbelasting", A, None, True),
    SeedAccount("1500", "Voorraad", A),
    # Equity
    SeedAccount("2000", "Ondernemingsvermogen / Kapitaal", E, None, True),
    SeedAccount("2010", "Privé-opnamen", E, None, True),
    SeedAccount("2020", "Privé-stortingen", E, None, True),
    SeedAccount("2030", "Privégebruik / privé-aandeel kosten", E, None, True),
    SeedAccount("2900", "Beginbalans / overboekingsrekening", E, None, True),
    SeedAccount("2910", "Winst/verlies lopend boekjaar", E, None, True),
    # Liabilities
    SeedAccount("3000", "Crediteuren", L, "BSchCre", True),
    SeedAccount("3100", "BTW af te dragen hoog (21%)", L, None, True),
    SeedAccount("3110", "BTW af te dragen laag (9%)", L, None, True),
    SeedAccount("3120", "BTW af te dragen overig", L, None, True),
    SeedAccount("3130", "BTW verlegd - af te dragen", L, None, True),
    SeedAccount("3140", "BTW privégebruik", L, None, True),
    SeedAccount("3150", "BTW rekening-courant (Belastingdienst)", L, None, True),
    SeedAccount("3200", "Af te dragen loonheffing", L),
    SeedAccount("3300", "Te betalen inkomstenbelasting/ZVW", L),
    SeedAccount("3400", "Overige schulden", L),
    SeedAccount("3500", "Vooruitontvangen bedragen", L),
    SeedAccount("3600", "Lening bank", L),
    # Revenue
    SeedAccount("8000", "Omzet hoog (21%)", R, None, True, "NL_21"),
    SeedAccount("8010", "Omzet laag (9%)", R, None, False, "NL_9"),
    SeedAccount("8020", "Omzet 0% / vrijgesteld", R, None, False, "NL_0"),
    SeedAccount("8030", "Omzet btw verlegd (binnenland)", R, None, False, "VERLEGD"),
    SeedAccount("8040", "Omzet EU (ICP)", R, None, False, "EU_DIENSTEN"),
    SeedAccount("8050", "Omzet buiten EU (export)", R, None, False, "EXPORT"),
    SeedAccount("8900", "Overige bedrijfsopbrengsten", R),
    SeedAccount("8990", "Rente-opbrengsten", R),
    # Expenses (default NL_21, GEEN for 4400/4800/4900/4910/4960)
    SeedAccount("4000", "Inkoopwaarde omzet", X, None, False, "NL_21"),
    SeedAccount("4100", "Huur bedrijfsruimte", X, None, False, "NL_21"),
    SeedAccount("4110", "Gas, water, elektra", X, None, False, "NL_21"),
    SeedAccount("4200", "Kantoorbenodigdheden", X, None, False, "NL_21"),
    SeedAccount("4210", "Telefoon en internet", X, None, False, "NL_21"),
    SeedAccount("4220", "Software en abonnementen", X, None, False, "NL_21"),
    SeedAccount("4230", "Porti en verzendkosten", X, None, False, "NL_21"),
    SeedAccount("4300", "Autokosten brandstof", X, None, False, "NL_21"),
    SeedAccount("4310", "Autokosten overig", X, None, False, "NL_21"),
    SeedAccount("4320", "Reiskosten openbaar vervoer", X, None, False, "NL_21"),
    SeedAccount("4400", "Verzekeringen", X, None, False, "GEEN"),
    SeedAccount("4500", "Reclame en marketing", X, None, False, "NL_21"),
    SeedAccount("4510", "Representatiekosten", X, None, False, "NL_21"),
    SeedAccount("4600", "Advies- en accountantskosten", X, None, False, "NL_21"),
    SeedAccount("4610", "Administratiekosten", X, None, False, "NL_21"),
    SeedAccount("4700", "Opleidingskosten", X, None, False, "NL_21"),
    SeedAccount("4800", "Afschrijvingen", X, None, False, "GEEN"),
    SeedAccount("4900", "Bankkosten", X, None, False, "GEEN"),
    SeedAccount("4910", "Rentelasten", X, None, False, "GEEN"),
    SeedAccount("4950", "Kasverschillen", X, None, True, "NL_21"),
    SeedAccount("4960", "Overige bedrijfskosten", X, None, False, "GEEN"),
    SeedAccount("4999", "Nog te verdelen / suspense kosten", X, None, True, "NL_21"),
]

# (code, name, rate_bp)
SEED_VAT_CODES: list[tuple[str, str, int]] = [
    ("GEEN", "Geen btw", 0),
    ("NL_21", "BTW 21%", 2100),
    ("NL_9", "BTW 9%", 900),
    ("NL_0", "BTW 0%", 0),
    ("VERLEGD", "BTW verlegd", 0),
    ("EU_GOEDEREN", "Intracommunautair goederen", 0),
    ("EU_DIENSTEN", "Intracommunautair diensten", 0),
    ("EXPORT", "Export buiten EU", 0),
]

# (code, name, type, account_code or None)
SEED_JOURNALS: list[tuple[str, str, str, str | None]] = [
    ("VK", "Verkoopboek", "verkoop", None),
    ("IK", "Inkoopboek", "inkoop", None),
    ("BANK", "Bank", "bank", "1210"),
    ("KAS", "Kas", "kas", "1100"),
    ("MEM", "Memoriaal", "memoriaal", None),
]


# System accounts the program uses itself: never shown in pick-lists.
# (Revenue 8000 and the equity privé accounts 2010/2020/2030 are system too,
# but they are not in this list.)
_HIDDEN_SYSTEM_CODES = frozenset(
    {"0190", "1100", "1210", "1230", "1300", "1400", "1410", "2000", "2900", "2910",
     "3000", "3100", "3110", "3120", "3130", "3140", "3150", "4950", "4999"}
)
_ASSET_PURCHASE_CODES = frozenset({"0100", "0110", "0120"})
_EQUITY_BANK_CODES = frozenset({"2010", "2020", "2030"})


def default_contexts(type: str, is_system: bool, code: str) -> tuple[bool, bool, bool]:
    """Where an account shows up by default: (purchase, sales, bank)."""
    if code in _HIDDEN_SYSTEM_CODES:
        return (False, False, False)
    if type == "expense":
        return (True, False, True)
    if type == "revenue":
        return (False, True, True)
    if type == "asset":
        if is_system:
            return (False, False, False)
        return (code in _ASSET_PURCHASE_CODES, False, True)
    if type == "equity":
        return (False, False, code in _EQUITY_BANK_CODES or not is_system)
    if type == "liability":
        return (False, False, not is_system)
    return (False, False, False)
