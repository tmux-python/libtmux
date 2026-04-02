from __future__ import annotations


class _CSS:
    """CSS class name constants used in generated HTML.

    Centralises every ``spf-*`` class name so the extension and stylesheet
    stay in sync.  Tests import this class to assert on rendered output.
    """

    PREFIX = "spf"
    BADGE_GROUP = f"{PREFIX}-badge-group"
    BADGE = f"{PREFIX}-badge"
    BADGE_SCOPE = f"{PREFIX}-badge--scope"
    BADGE_KIND = f"{PREFIX}-badge--kind"
    BADGE_STATE = f"{PREFIX}-badge--state"
    BADGE_FIXTURE = f"{PREFIX}-badge--fixture"
    FACTORY = f"{PREFIX}-factory"
    OVERRIDE = f"{PREFIX}-override"
    AUTOUSE = f"{PREFIX}-autouse"
    DEPRECATED = f"{PREFIX}-deprecated"
    FIXTURE_INDEX = f"{PREFIX}-fixture-index"
    TABLE_SCROLL = f"{PREFIX}-table-scroll"

    @staticmethod
    def scope(name: str) -> str:
        """Return the scope-specific CSS class, e.g. ``spf-scope-session``."""
        return f"{_CSS.PREFIX}-scope-{name}"
