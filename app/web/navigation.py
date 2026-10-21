from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    label: str
    path: str
    key: str
    group: int = 0  # visual group; the highest group is pinned to the sidebar bottom
    term_key: str | None = None  # glossary key for the plain-Dutch sub-line


@dataclass(frozen=True)
class MarkedNavItem(NavItem):
    active: bool = False


NAV_ITEMS: list[NavItem] = [
    NavItem("Inbox", "/inbox", "inbox", 0, "inbox"),
    NavItem("Boeken", "/boeken", "boeken", 0, "boeking"),
    NavItem("Bank", "/bank", "bank", 0, "bank"),
    NavItem("Verkoop", "/verkoop", "verkoop", 1, "debiteuren"),
    NavItem("Inkoop", "/inkoop", "inkoop", 1, "crediteuren"),
    NavItem("Relaties", "/relaties", "relaties", 1, "relaties"),
    NavItem("BTW", "/btw", "btw", 2, "btw"),
    NavItem("Rapportages", "/rapportages", "rapportages", 2, "rapportages"),
    NavItem("Activa", "/activa", "activa", 2, "activa"),
    NavItem("Instellingen", "/instellingen", "instellingen", 3),
]


def is_active(item: NavItem, path: str) -> bool:
    return path == item.path or path.startswith(item.path + "/")


def mark_active(path: str) -> list[MarkedNavItem]:
    return [
        MarkedNavItem(i.label, i.path, i.key, i.group, i.term_key, is_active(i, path))
        for i in NAV_ITEMS
    ]
