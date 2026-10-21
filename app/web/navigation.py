from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    label: str
    path: str
    key: str
    group: int = 0  # visual group; the highest group is pinned to the sidebar bottom


@dataclass(frozen=True)
class MarkedNavItem(NavItem):
    active: bool = False


NAV_ITEMS: list[NavItem] = [
    NavItem("Inbox", "/inbox", "inbox", 0),
    NavItem("Boeken", "/boeken", "boeken", 0),
    NavItem("Bank", "/bank", "bank", 0),
    NavItem("Verkoop", "/verkoop", "verkoop", 1),
    NavItem("Inkoop", "/inkoop", "inkoop", 1),
    NavItem("Relaties", "/relaties", "relaties", 1),
    NavItem("BTW", "/btw", "btw", 2),
    NavItem("Rapportages", "/rapportages", "rapportages", 2),
    NavItem("Activa", "/activa", "activa", 2),
    NavItem("Instellingen", "/instellingen", "instellingen", 3),
]


def is_active(item: NavItem, path: str) -> bool:
    return path == item.path or path.startswith(item.path + "/")


def mark_active(path: str) -> list[MarkedNavItem]:
    return [
        MarkedNavItem(i.label, i.path, i.key, i.group, is_active(i, path))
        for i in NAV_ITEMS
    ]
