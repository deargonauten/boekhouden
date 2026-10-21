from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    label: str
    path: str
    key: str
    group: int = 0  # visual group; the highest group is pinned to the sidebar bottom
    term_key: str | None = None  # glossary key for the plain-Dutch sub-line
    icon: str = ""  # icon name for the `icon()` macro in partials/_ui.html


@dataclass(frozen=True)
class MarkedNavItem(NavItem):
    active: bool = False


# Section labels shown in the sidebar; groups without a label (the pinned one) show none.
GROUP_LABELS: dict[int, str] = {
    0: "Verwerken",
    1: "Verkoop en inkoop",
    2: "Aangifte en overzicht",
}

NAV_ITEMS: list[NavItem] = [
    NavItem("Inbox", "/inbox", "inbox", 0, "inbox", "inbox"),
    NavItem("Boeken", "/boeken", "boeken", 0, "boeking", "book"),
    NavItem("Bank", "/bank", "bank", 0, "bank", "bank"),
    NavItem("Verkoop", "/verkoop", "verkoop", 1, "debiteuren", "receipt"),
    NavItem("Inkoop", "/inkoop", "inkoop", 1, "crediteuren", "file"),
    NavItem("Relaties", "/relaties", "relaties", 1, "relaties", "users"),
    NavItem("BTW", "/btw", "btw", 2, "btw", "percent"),
    NavItem("Rapportages", "/rapportages", "rapportages", 2, "rapportages", "chart"),
    NavItem("Activa", "/activa", "activa", 2, "activa", "box"),
    NavItem("Instellingen", "/instellingen", "instellingen", 3, None, "settings"),
]


def is_active(item: NavItem, path: str) -> bool:
    return path == item.path or path.startswith(item.path + "/")


def mark_active(path: str) -> list[MarkedNavItem]:
    return [
        MarkedNavItem(i.label, i.path, i.key, i.group, i.term_key, i.icon, is_active(i, path))
        for i in NAV_ITEMS
    ]


@dataclass(frozen=True)
class SettingsItem:
    label: str
    path: str
    term_key: str | None = None  # glossary key: info icon plus plain-Dutch sub-line


@dataclass(frozen=True)
class SettingsGroup:
    label: str  # plain Dutch heading, no bookkeeping term
    items: tuple[SettingsItem, ...]


# Second navigation column on the settings pages (templates/base_settings.html). Only existing pages.
SETTINGS_NAV: list[SettingsGroup] = [
    SettingsGroup(
        "Boekhouding",
        (
            SettingsItem("Grootboek", "/instellingen/grootboek", "grootboek"),
            SettingsItem("Dagboeken", "/instellingen/dagboeken", "dagboek"),
            SettingsItem("Boekjaren", "/instellingen/boekjaren", "boekjaar"),
        ),
    ),
]


def is_settings_active(item: SettingsItem, path: str) -> bool:
    return path == item.path or path.startswith(item.path + "/")
