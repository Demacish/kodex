from __future__ import annotations

import re

from pydantic import BaseModel, model_validator

# The home page's configurable shelves (home-sections.md, ReadMeABook-
# inspired) — see app/models/user.py's home_sections docstring. Order here
# is the default a user with no customization yet (home_sections is null)
# sees, and web/src/lib/home.ts must keep the same keys in the same order.
HOME_SECTION_KEYS = (
    "ai_recommendations",
    "continue_reading",
    "new_in_followed",
    "newly_added",
    "recently_updated",
    "libraries",
)


# ntfy's own rule for topic names.
_NTFY_TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class OpdsTokenOut(BaseModel):
    opds_token: str


class UserOut(BaseModel):
    id: int
    username: str
    email: str | None
    is_admin: bool
    kindle_email: str | None
    # True once an OPDS token exists — the token itself is only ever
    # returned right after POST /me/opds-token, never echoed back here, so
    # a lost/forgotten token means regenerating rather than looking it up.
    has_opds_token: bool
    # None = never customized (frontend falls back to HOME_SECTION_KEYS'
    # default order, all visible) — see app/models/user.py.
    home_sections: list[str] | None
    # The ntfy topic for push notifications, or None for no push.
    ntfy_topic: str | None = None


class UserUpdate(BaseModel):
    # None/omitted leaves it unchanged; an empty string clears it (e.g. to
    # stop sending to a Kindle without setting a new address).
    kindle_email: str | None = None
    # None/omitted leaves it unchanged; [] hides every section (a valid,
    # if unusual, choice — the "Bibliotek" nav link still works, this only
    # affects the home page's shelves).
    home_sections: list[str] | None = None
    # None/omitted leaves it unchanged; "" turns push notifications off.
    ntfy_topic: str | None = None

    @model_validator(mode="after")
    def _check_home_sections(self) -> UserUpdate:
        if self.home_sections is not None:
            unknown = set(self.home_sections) - set(HOME_SECTION_KEYS)
            if unknown:
                raise ValueError(f"Unknown home section(s): {sorted(unknown)}")
            if len(self.home_sections) != len(set(self.home_sections)):
                raise ValueError("home_sections must not contain duplicates")
        if self.ntfy_topic and not _NTFY_TOPIC_RE.match(self.ntfy_topic.strip()):
            raise ValueError("ntfy_topic may only contain letters, digits, - and _ (max 64)")
        return self
