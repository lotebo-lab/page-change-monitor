"""Tests for src/fingerprint.py and the pure comparison in src/state.py.

Plain Python, own runner, no pytest and no network. Every page is literal HTML
written inside this file.

Run it from the Actor folder:

    ../../.venv/bin/python tests/test_fingerprint.py
"""

from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
)

from fingerprint import (  # noqa: E402
    collapse_whitespace,
    fingerprint_html,
    normalize_attributes,
)
from state import compare_records, record_key  # noqa: E402


# --------------------------------------------------------------------------
# Pages used by the tests. Same content, different formatting.
# --------------------------------------------------------------------------

PAGE_TIDY = """
<html>
  <head><title>Status</title></head>
  <body>
    <header class="top bar">Acme status</header>
    <main id="status">
      <h2>Current status</h2>
      <p>All systems operational.</p>
      <ul>
        <li>API: up</li>
        <li>Web: up</li>
      </ul>
    </main>
    <footer>Updated hourly</footer>
  </body>
</html>
"""

# Exactly the same content as PAGE_TIDY, reindented, with line breaks moved,
# extra spaces inside the text and one HTML comment added.
PAGE_MESSY = (
    "<html><head><title>Status</title></head><body>"
    '<header class="top bar">Acme    status</header>'
    '<main id="status"><!-- rendered by template v9 -->\n\n'
    "        <h2>Current\n   status</h2>"
    "<p>   All systems operational.   </p>"
    "<ul><li>API: up</li>\n<li>Web: up</li></ul>"
    "</main><footer>Updated     hourly</footer></body></html>"
)

# Same page, but the text inside #status changed.
PAGE_INSIDE_CHANGED = PAGE_TIDY.replace(
    "All systems operational.", "API degraded since 02:10 UTC."
)

# Same page, but only the part outside #status changed.
PAGE_OUTSIDE_CHANGED = PAGE_TIDY.replace(
    "<footer>Updated hourly</footer>", "<footer>Updated every 5 minutes</footer>"
).replace("Acme status", "Acme status page")

# Same page with volatile attributes added and regenerated ids.
PAGE_VOLATILE_A = """
<html>
  <body>
    <main id="status">
      <div class="card" data-timestamp="1758331200" nonce="a1b2c3d4"
           data-request-id="req-0001" id="panel-482913">
        <p>All systems operational.</p>
      </div>
    </main>
  </body>
</html>
"""

PAGE_VOLATILE_B = """
<html>
  <body>
    <main id="status">
      <div class="card" data-timestamp="1758417600" nonce="z9y8x7w6"
           data-request-id="req-7788" id="panel-905117">
        <p>All systems operational.</p>
      </div>
    </main>
  </body>
</html>
"""

# Same as PAGE_VOLATILE_A but with a non-volatile attribute changed, to prove
# the fingerprint is not simply ignoring every attribute.
PAGE_ATTR_REAL_CHANGE = PAGE_VOLATILE_A.replace('class="card"', 'class="card down"')


# --------------------------------------------------------------------------
# Tiny runner
# --------------------------------------------------------------------------

FAILURES: list[str] = []
PASSED = 0


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(name: str, func) -> None:
    global PASSED
    try:
        func()
    except Exception:  # noqa: BLE001 - the runner reports, it does not crash
        FAILURES.append(name)
        print("FAIL  %s" % name)
        print(traceback.format_exc())
    else:
        PASSED += 1
        print("ok    %s" % name)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_whitespace_does_not_change_the_hash() -> None:
    tidy = fingerprint_html(PAGE_TIDY, "#status")
    messy = fingerprint_html(PAGE_MESSY, "#status")
    check(tidy["found"] and messy["found"], "both pages should be fingerprinted")
    check(
        tidy["fingerprint"] == messy["fingerprint"],
        "reindented HTML with the same content must give the same hash:\n"
        "  tidy  = %s\n  messy = %s" % (tidy["fingerprint"], messy["fingerprint"]),
    )
    check(
        tidy["text"] == messy["text"],
        "normalized text should also match: %r vs %r" % (tidy["text"], messy["text"]),
    )
    check(
        "All systems operational." in tidy["text"],
        "the normalized text should keep the content: %r" % tidy["text"],
    )
    check(
        "rendered by template" not in messy["text"],
        "HTML comments must not reach the normalized text: %r" % messy["text"],
    )


def test_whole_page_hash_also_ignores_formatting() -> None:
    tidy = fingerprint_html(PAGE_TIDY)
    messy = fingerprint_html(PAGE_MESSY)
    check(tidy["found"] and messy["found"], "both pages should be fingerprinted")
    check(
        tidy["fingerprint"] == messy["fingerprint"],
        "without a selector, formatting must still not change the hash",
    )


def test_change_inside_the_selector_changes_the_hash() -> None:
    before = fingerprint_html(PAGE_TIDY, "#status")
    after = fingerprint_html(PAGE_INSIDE_CHANGED, "#status")
    check(before["found"] and after["found"], "both pages should be fingerprinted")
    check(
        before["fingerprint"] != after["fingerprint"],
        "changed text inside the selector must change the hash",
    )
    check(
        "API degraded" in after["excerpt"],
        "the excerpt should show the new text: %r" % after["excerpt"],
    )


def test_change_outside_the_selector_does_not_change_the_hash() -> None:
    before = fingerprint_html(PAGE_TIDY, "#status")
    after = fingerprint_html(PAGE_OUTSIDE_CHANGED, "#status")
    check(before["found"] and after["found"], "both pages should be fingerprinted")
    check(
        before["fingerprint"] == after["fingerprint"],
        "a change in the header and the footer must not change the hash of "
        "#status:\n  before = %s\n  after  = %s"
        % (before["fingerprint"], after["fingerprint"]),
    )
    # The same edit must be visible when nobody narrows the check.
    whole_before = fingerprint_html(PAGE_TIDY)
    whole_after = fingerprint_html(PAGE_OUTSIDE_CHANGED)
    check(
        whole_before["fingerprint"] != whole_after["fingerprint"],
        "without a selector, the footer change must be detected",
    )


def test_volatile_attributes_do_not_change_the_hash() -> None:
    first = fingerprint_html(PAGE_VOLATILE_A, "#status")
    second = fingerprint_html(PAGE_VOLATILE_B, "#status")
    check(first["found"] and second["found"], "both pages should be fingerprinted")
    check(
        first["fingerprint"] == second["fingerprint"],
        "nonce, data-timestamp, data-request-id and a regenerated id must not "
        "change the hash:\n  a = %s\n  b = %s"
        % (first["fingerprint"], second["fingerprint"]),
    )
    real = fingerprint_html(PAGE_ATTR_REAL_CHANGE, "#status")
    check(
        real["fingerprint"] != first["fingerprint"],
        "a real attribute change (class) must still change the hash, "
        "otherwise attributes are just being ignored",
    )


def test_normalize_attributes_rules() -> None:
    cleaned = normalize_attributes(
        {
            "nonce": "abc",
            "data-timestamp": "1758331200",
            "data-csrf-token": "xyz",
            "id": "panel-482913",
            "class": ["beta", "alpha"],
            "href": "  /pricing  ",
        }
    )
    check("nonce" not in cleaned, "nonce must be dropped: %r" % cleaned)
    check("data-timestamp" not in cleaned, "data-timestamp must be dropped")
    check("data-csrf-token" not in cleaned, "data-csrf-token must be dropped")
    check(
        cleaned.get("id") == "panel",
        "the random numeric suffix of id must be stripped: %r" % cleaned.get("id"),
    )
    check(
        cleaned.get("class") == "alpha beta",
        "class tokens must be sorted: %r" % cleaned.get("class"),
    )
    check(
        cleaned.get("href") == "/pricing",
        "attribute values must be trimmed: %r" % cleaned.get("href"),
    )
    check(collapse_whitespace(" a \n\n b ") == "a b", "whitespace must collapse")


def test_missing_selector_is_handled() -> None:
    result = fingerprint_html(PAGE_TIDY, "#does-not-exist")
    check(result["found"] is False, "a selector that matches nothing is not found")
    check(result["fingerprint"] == "", "no fingerprint without a match")
    check(result["matches"] == 0, "no match means zero matches")
    check(
        isinstance(result["error"], str) and "#does-not-exist" in result["error"],
        "the error should name the selector: %r" % result["error"],
    )


def test_broken_input_is_handled() -> None:
    invalid = fingerprint_html(PAGE_TIDY, "a[href=")
    check(invalid["found"] is False, "an invalid CSS selector must not raise")
    check(
        isinstance(invalid["error"], str) and invalid["error"],
        "an invalid selector must come with an error message",
    )
    empty = fingerprint_html("", "#status")
    check(empty["found"] is False, "empty HTML must not raise")
    check(empty["error"] == "empty HTML", "empty HTML should say so")
    none_html = fingerprint_html(None, None)  # type: ignore[arg-type]
    check(none_html["found"] is False, "None must not raise")


def test_multiple_matches_are_fingerprinted_together() -> None:
    page = "<html><body><p class='row'>one</p><p class='row'>two</p></body></html>"
    other = "<html><body><p class='row'>one</p><p class='row'>three</p></body></html>"
    first = fingerprint_html(page, "p.row")
    second = fingerprint_html(other, "p.row")
    check(first["matches"] == 2, "both paragraphs should match: %r" % first["matches"])
    check(
        first["fingerprint"] != second["fingerprint"],
        "a change in the second match must be detected",
    )


def test_excerpt_respects_the_limit() -> None:
    long_page = "<html><body><div id='x'>%s</div></body></html>" % ("ab " * 400)
    short = fingerprint_html(long_page, "#x", excerpt_chars=50)
    check(len(short["excerpt"]) <= 53, "excerpt must respect the limit")
    check(short["excerpt"].endswith("..."), "a trimmed excerpt ends with ...")
    none = fingerprint_html(long_page, "#x", excerpt_chars=0)
    check(none["excerpt"] == "", "excerpt_chars 0 stores no text")
    check(none["fingerprint"], "excerpt_chars 0 still fingerprints")


def test_comparison_rules() -> None:
    current = {"fingerprint": "sha256:aaa", "excerpt": "now"}
    first = compare_records(None, current)
    check(first["changed"] is False, "a first check cannot report a change")
    check(first["first_check"] is True, "a first check is flagged as such")

    same = compare_records({"fingerprint": "sha256:aaa", "excerpt": "before"}, current)
    check(same["changed"] is False, "the same fingerprint is not a change")
    check(same["previous_excerpt"] == "before", "the old excerpt is carried over")

    changed = compare_records(
        {"fingerprint": "sha256:bbb", "excerpt": "before"}, current
    )
    check(changed["changed"] is True, "a different fingerprint is a change")
    check(changed["comparable"] is True, "a real comparison is comparable")

    failed = compare_records(
        {"fingerprint": "sha256:bbb", "excerpt": "before"}, {"fingerprint": ""}
    )
    check(
        failed["changed"] is False,
        "a page we could not read is not a page that changed",
    )
    check(failed["comparable"] is False, "an unreadable page is not comparable")


def test_record_key_is_stable_and_specific() -> None:
    a = record_key("https://example.com", "#status")
    b = record_key("https://example.com", "#status")
    c = record_key("https://example.com", "#other")
    d = record_key("https://example.com", None)
    check(a == b, "the same pair must give the same key")
    check(a != c, "a different selector must give a different key")
    check(a != d, "no selector must give a different key")
    check(a.startswith("WATCH-"), "keys are prefixed: %r" % a)
    check(
        all(ch.isalnum() or ch == "-" for ch in a),
        "the key must be safe for the key-value store: %r" % a,
    )


TESTS = [
    ("whitespace does not change the hash", test_whitespace_does_not_change_the_hash),
    ("whole page hash ignores formatting", test_whole_page_hash_also_ignores_formatting),
    ("change inside the selector changes the hash", test_change_inside_the_selector_changes_the_hash),
    ("change outside the selector does not change the hash", test_change_outside_the_selector_does_not_change_the_hash),
    ("volatile attributes do not change the hash", test_volatile_attributes_do_not_change_the_hash),
    ("normalize_attributes rules", test_normalize_attributes_rules),
    ("missing selector is handled", test_missing_selector_is_handled),
    ("broken input is handled", test_broken_input_is_handled),
    ("multiple matches are fingerprinted together", test_multiple_matches_are_fingerprinted_together),
    ("excerpt respects the limit", test_excerpt_respects_the_limit),
    ("comparison rules", test_comparison_rules),
    ("record key is stable and specific", test_record_key_is_stable_and_specific),
]


def main() -> int:
    print("fingerprint and state tests (no network)")
    for name, func in TESTS:
        run(name, func)
    total = len(TESTS)
    if FAILURES:
        print("RESULT: %d/%d passed, FAILED: %s" % (PASSED, total, ", ".join(FAILURES)))
        return 1
    print("RESULT: %d/%d passed, 0 failed" % (PASSED, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
