"""Where the previous fingerprint of each URL is kept, and how it is compared.

The Actor has no database. The memory between two runs is the Actor's named
key-value store: one record per (URL, selector) pair, holding the fingerprint
of the last run, a short excerpt of what was there and when it was checked.

Everything that decides something is a pure function (`record_key`,
`build_record`, `compare_records`), so the tests can exercise the comparison
without a store and without network. The two functions that touch the store
(`load_record`, `save_record`) do nothing but read and write.
"""

from __future__ import annotations

import hashlib
from typing import Any

__all__ = [
    "DEFAULT_STORE_NAME",
    "record_key",
    "build_record",
    "compare_records",
    "load_record",
    "save_record",
]

# A named store survives between runs of the same Actor for the same user.
# The unnamed default store belongs to a single run and would make every run
# look like a first run.
DEFAULT_STORE_NAME = "page-change-monitor-state"


def record_key(url: str, selector: str | None = None) -> str:
    """Key for one watched pair. Safe for the key-value store naming rules.

    Apify keys accept a limited character set, and a URL does not fit it, so
    the key is a prefix plus the sha256 of the URL and the selector. The pair
    (URL, selector) is what identifies a watch: the same page watched with two
    selectors keeps two independent histories.
    """
    raw = "%s\n%s" % (url or "", selector or "")
    return "WATCH-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_record(
    url: str,
    selector: str | None,
    fingerprint: str,
    excerpt: str,
    checked_at: str,
) -> dict[str, Any]:
    """The shape of what is stored. Pure."""
    return {
        "url": url,
        "selector": selector or None,
        "fingerprint": fingerprint or "",
        "excerpt": excerpt or "",
        "checked_at": checked_at,
    }


def compare_records(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> dict[str, Any]:
    """Decide whether the watched part changed. Pure.

    Rules, written out so nobody has to guess:

    * No previous record: this is the first check of this URL. `changed` is
      False and `first_check` is True. A first run has nothing to compare
      against, so it cannot honestly report a change.
    * Previous record with the same fingerprint: `changed` is False.
    * Previous record with a different fingerprint: `changed` is True.
    * Current fingerprint missing (the fetch failed, or the selector matched
      nothing): `changed` is False and `comparable` is False. A page we could
      not read is not a page that changed.

    Returns `changed`, `first_check`, `comparable`, `previous_fingerprint` and
    `previous_excerpt`.
    """
    current_fingerprint = (current or {}).get("fingerprint") or ""
    previous_fingerprint = (previous or {}).get("fingerprint") or ""
    previous_excerpt = (previous or {}).get("excerpt") or ""

    if not current_fingerprint:
        return {
            "changed": False,
            "first_check": previous is None,
            "comparable": False,
            "previous_fingerprint": previous_fingerprint,
            "previous_excerpt": previous_excerpt,
        }

    if previous is None or not previous_fingerprint:
        return {
            "changed": False,
            "first_check": True,
            "comparable": False,
            "previous_fingerprint": "",
            "previous_excerpt": "",
        }

    return {
        "changed": previous_fingerprint != current_fingerprint,
        "first_check": False,
        "comparable": True,
        "previous_fingerprint": previous_fingerprint,
        "previous_excerpt": previous_excerpt,
    }


async def load_record(store: Any, key: str) -> dict[str, Any] | None:
    """Read one record from the store. Anything unreadable reads as None."""
    value = await store.get_value(key)
    if isinstance(value, dict):
        return value
    return None


async def save_record(store: Any, key: str, record: dict[str, Any]) -> None:
    """Write one record to the store."""
    await store.set_value(key, record)
