"""Stable fingerprint of a piece of an HTML page.

Pure functions, no network, no Apify. The Actor calls `fingerprint_html` once
per URL; the tests call the same function with literal HTML.

The point of a fingerprint is that it changes when the content changes and
does not change when only the noise changes. The noise we remove here:

* HTML comments (build stamps, template markers);
* `<script>`, `<style>`, `<noscript>` and `<template>` elements, which are not
  content the reader sees and which very often carry inline timestamps;
* whitespace and line breaks, collapsed to one space and dropped when empty,
  so reindenting a template does not look like a change;
* volatile attributes: `nonce`, CSRF tokens, request ids, render timestamps
  (see `VOLATILE_ATTR_NAMES` and `VOLATILE_ATTR_PREFIXES`);
* the random-looking numeric or hex suffix of `id` and `for` attributes, which
  many frameworks regenerate on every render;
* the order of the tokens inside `class`, which is sorted.

What stays inside the fingerprint, on purpose: the tag structure, the tag
names, every attribute that is not on the volatile list, and the text. So a
changed link target or a changed price attribute counts as a change, not only
visible text.

Limits, stated plainly: this compares the HTML the server sends. It does not
run JavaScript, so a page that builds its content in the browser looks empty
or unchanged here. A page that legitimately rotates content on every render
(a random quote, a "last visited" line, an ad slot) will report a change every
run unless a CSS selector narrows the check to a stable part of the page.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from bs4 import BeautifulSoup, Comment
from bs4.element import Doctype, NavigableString, ProcessingInstruction, Tag

__all__ = [
    "VOLATILE_ATTR_NAMES",
    "VOLATILE_ATTR_PREFIXES",
    "collapse_whitespace",
    "normalize_attributes",
    "excerpt",
    "fingerprint_html",
]

# Elements dropped before fingerprinting: not reader-visible content.
DROPPED_TAGS = ("script", "style", "noscript", "template")

# Attributes dropped entirely, by exact name (lowercase).
VOLATILE_ATTR_NAMES = frozenset(
    {
        "nonce",
        "csrf",
        "csrftoken",
        "csrf-token",
        "csrfmiddlewaretoken",
        "data-csrf",
        "data-csrf-token",
        "data-nonce",
        "data-timestamp",
        "data-time",
        "data-ts",
        "data-updated",
        "data-updated-at",
        "data-render-time",
        "data-rendered-at",
        "data-request-id",
        "data-trace-id",
        "data-session-id",
        "data-reactid",
        "data-react-checksum",
        "data-turbo-track",
        "integrity",
    }
)

# Attributes dropped by prefix (lowercase), for the framework-specific names
# we cannot list one by one.
VOLATILE_ATTR_PREFIXES = (
    "data-timestamp",
    "data-ts-",
    "data-nonce",
    "data-csrf",
    "data-request-id",
    "data-session",
    "data-trace",
)

# Attributes whose value is an identifier that frameworks regenerate.
IDENTIFIER_ATTRS = ("id", "for", "aria-labelledby", "aria-controls", "aria-describedby")

# A trailing run of digits, or a long hex run, optionally after - _ or :.
_RANDOM_SUFFIX = re.compile(r"[-_:]?(?:[0-9]{3,}|[0-9a-fA-F]{8,})$")

_WHITESPACE = re.compile(r"\s+")


def collapse_whitespace(text: str) -> str:
    """Every run of whitespace becomes one space; the ends are trimmed."""
    return _WHITESPACE.sub(" ", text or "").strip()


def _is_volatile_attr(name: str) -> bool:
    lowered = name.lower()
    if lowered in VOLATILE_ATTR_NAMES:
        return True
    return any(lowered.startswith(prefix) for prefix in VOLATILE_ATTR_PREFIXES)


def _strip_random_suffix(value: str) -> str:
    return _RANDOM_SUFFIX.sub("", collapse_whitespace(value))


def normalize_attributes(attrs: dict[str, Any]) -> dict[str, str]:
    """Drop the volatile attributes and normalize the ones that stay.

    Pure: takes and returns plain data, so the test can check the rules
    without building a page.
    """
    normalized: dict[str, str] = {}
    for raw_name, raw_value in (attrs or {}).items():
        name = str(raw_name).lower()
        if _is_volatile_attr(name):
            continue
        if isinstance(raw_value, (list, tuple)):
            value = " ".join(str(part) for part in raw_value)
        elif raw_value is None:
            value = ""
        else:
            value = str(raw_value)
        if name == "class":
            # Class order is decoration, not content.
            value = " ".join(sorted(collapse_whitespace(value).split()))
        elif name in IDENTIFIER_ATTRS:
            value = _strip_random_suffix(value)
            if not value:
                continue
        else:
            value = collapse_whitespace(value)
        normalized[name] = value
    return normalized


class _Close:
    """Marker on the walk stack: emit the closing tag of an element."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name


def _serialize(root: Any, markup: list[str], text: list[str]) -> None:
    """Walk the tree, appending the canonical markup and the visible text.

    Iterative on purpose. The first version recursed once per nesting level,
    and a real page with a few thousand unclosed tags (old <font> or <div>
    soup, which html.parser nests instead of closing) went past Python's
    recursion limit and raised RecursionError, which failed the whole run.
    The output is byte-for-byte what the recursive walk produced, so stored
    fingerprints stay valid.
    """
    stack: list[Any] = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, _Close):
            markup.append("</%s>" % node.name)
            continue
        if isinstance(node, (Comment, ProcessingInstruction, Doctype)):
            continue
        if isinstance(node, NavigableString):
            piece = collapse_whitespace(str(node))
            if piece:
                markup.append(piece)
                text.append(piece)
            continue
        if not isinstance(node, Tag):
            continue
        name = (node.name or "").lower()
        if name in DROPPED_TAGS:
            continue

        attrs = normalize_attributes(node.attrs)
        rendered = "".join(
            ' %s="%s"' % (attr, attrs[attr]) for attr in sorted(attrs)
        )
        markup.append("<%s%s>" % (name, rendered))
        stack.append(_Close(name))
        stack.extend(reversed(list(node.children)))


def excerpt(text: str, limit: int = 200) -> str:
    """First `limit` characters of the normalized text, with an ellipsis."""
    if limit is None or limit <= 0:
        return ""
    clean = collapse_whitespace(text)
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "..."


def fingerprint_html(
    html: str,
    selector: str | None = None,
    excerpt_chars: int = 200,
) -> dict[str, Any]:
    """Fingerprint a page, or the part of it that matches `selector`.

    Returns a dict, always, never raising for bad input:

    * `found`: True when there was something to fingerprint. False when the
      selector matched nothing, the selector is not valid CSS, or the HTML is
      empty.
    * `error`: a short sentence when `found` is False, otherwise None.
    * `matches`: how many elements the selector matched (0 or 1 when there is
      no selector: the whole document counts as one).
    * `text`: the normalized text of the matched part.
    * `excerpt`: the first `excerpt_chars` characters of that text.
    * `fingerprint`: `sha256:<hex>` of the canonical markup, or "" when
      `found` is False.

    When several elements match the selector, all of them are fingerprinted
    together, in document order.
    """
    result: dict[str, Any] = {
        "found": False,
        "error": None,
        "selector": selector or None,
        "matches": 0,
        "text": "",
        "excerpt": "",
        "fingerprint": "",
    }

    if not html or not str(html).strip():
        result["error"] = "empty HTML"
        return result

    try:
        soup = BeautifulSoup(str(html), "html.parser")
    except Exception as exc:  # noqa: BLE001 - one bad page must not stop a run
        result["error"] = "could not parse the HTML: %s" % exc
        return result

    if selector:
        try:
            nodes = soup.select(selector)
        except RecursionError:
            result["error"] = (
                "the page is nested too deeply to apply selector %r" % selector
            )
            return result
        except Exception as exc:  # noqa: BLE001 - invalid CSS is user input
            result["error"] = "invalid CSS selector %r: %s" % (selector, exc)
            return result
        if not nodes:
            result["error"] = "selector %r matched nothing on this page" % selector
            return result
    else:
        nodes = [soup.body or soup]

    result["matches"] = len(nodes)

    markup: list[str] = []
    text: list[str] = []
    try:
        for node in nodes:
            _serialize(node, markup, text)
    except Exception as exc:  # noqa: BLE001 - one bad page must not stop a run
        result["matches"] = 0
        result["error"] = "could not read the page structure: %s" % exc
        return result

    canonical = "".join(markup)
    normalized_text = collapse_whitespace(" ".join(text))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    result["found"] = True
    result["text"] = normalized_text
    result["excerpt"] = excerpt(normalized_text, excerpt_chars)
    result["fingerprint"] = "sha256:%s" % digest
    return result
