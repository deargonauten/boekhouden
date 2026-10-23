"""Result types of the controle voor aangifte (pure dataclasses, no database)."""

from dataclasses import dataclass

from app.domain.vat.periods import VatPeriod

LEVEL_OK = "ok"
LEVEL_LET_OP = "let_op"
LEVEL_FOUT = "fout"

OK_HEADLINE = "Alles lijkt in orde. Dit is een hulpmiddel, geen garantie."


@dataclass(frozen=True)
class CheckItem:
    """One example the user can open."""

    label: str
    href: str


@dataclass(frozen=True)
class Check:
    key: str
    title: str  # plain Dutch
    explanation: str  # plain Dutch, says what is wrong and what to do
    level: str  # ok | let_op | fout
    count: int
    items: tuple[CheckItem, ...]  # at most 5 examples
    fix_href: str
    fix_label: str
    amount_cents: int | None = None  # only for bank_ongeboekt: sum of the absolute amounts


@dataclass(frozen=True)
class CheckReport:
    period: VatPeriod
    checks: tuple[Check, ...]

    @property
    def verdict(self) -> str:
        levels = {c.level for c in self.checks}
        if LEVEL_FOUT in levels:
            return LEVEL_FOUT
        if LEVEL_LET_OP in levels:
            return LEVEL_LET_OP
        return LEVEL_OK

    @property
    def problem_count(self) -> int:
        return sum(1 for c in self.checks if c.level != LEVEL_OK)

    @property
    def headline(self) -> str:
        n = self.problem_count
        if n == 0:
            return OK_HEADLINE
        return "1 ding om te controleren" if n == 1 else f"{n} dingen om te controleren"
