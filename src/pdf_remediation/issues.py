from __future__ import annotations

from dataclasses import asdict, dataclass, field

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Issue:
    rule: str
    severity: str  # error | warning | info
    message: str
    page: int | None = None  # 1-based for display
    source: str = "qa"  # qa | verapdf | tagger | pipeline
    wcag: list[str] = field(default_factory=list)
    matterhorn: list[str] = field(default_factory=list)
    fix: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def sort_issues(issues: list[Issue]) -> list[Issue]:
    return sorted(issues, key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.page or 0, i.rule))
