"""Tests for the robots.txt gate in src/main.py.

Plain Python, own runner, no pytest and no network. Every robots.txt is
literal text written inside this file, served by a fake session that records
which URLs were asked for, so a test can prove that a page was never fetched.

The rule under test is the one the module docstring promises: we read a page
"only when the site's robots.txt allows that path for our user agent". In
robots.txt the group that names our agent wins whenever it exists, and the
`*` group is the fallback for agents no group names. `RobotFileParser.can_fetch`
already resolves that by itself (`_find_entry` looks up the named group first
and only falls back to `*`), so the gate must ask it once and trust the answer.

Run it from the Actor folder:

    ../../.venv/bin/python tests/test_robots.py
"""

from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
)

from main import ROBOTS_AGENT, RobotsGate, fetch_page  # noqa: E402


# --------------------------------------------------------------------------
# A fake session: it answers from a dict of URL -> (status, body) and keeps
# the list of URLs it was asked for.
# --------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status_code = status
        self.text = body
        self.headers = {"Content-Type": "text/html; charset=utf-8"}


class FakeSession:
    def __init__(self, pages: dict) -> None:
        self.pages = pages
        self.asked: list[str] = []

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.asked.append(url)
        if url not in self.pages:
            return FakeResponse(404, "not found")
        status, body = self.pages[url]
        return FakeResponse(status, body)


SITE = "https://example.test"
PAGE = SITE + "/status"
ROBOTS = SITE + "/robots.txt"
HTML = "<html><body><p>ok</p></body></html>"

# Our agent is named and denied; everyone else is allowed. This is the file a
# site owner writes when they want us, and only us, to go away.
ROBOTS_DENIES_US_ALLOWS_STAR = """
User-agent: %s
Disallow: /

User-agent: *
Allow: /
""" % ROBOTS_AGENT

# The mirror image: our agent is named and allowed, everyone else is denied.
ROBOTS_ALLOWS_US_DENIES_STAR = """
User-agent: %s
Allow: /

User-agent: *
Disallow: /
""" % ROBOTS_AGENT

ROBOTS_ONLY_STAR_DENIES = """
User-agent: *
Disallow: /status
"""

ROBOTS_ONLY_STAR_ALLOWS = """
User-agent: *
Disallow: /private
"""


def gate_for(robots_body: str, status: int = 200):
    session = FakeSession({ROBOTS: (status, robots_body), PAGE: (200, HTML)})
    return RobotsGate(session, timeout=5), session


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


def test_named_deny_beats_star_allow() -> None:
    """The group naming us wins over a permissive `*` group."""
    gate, _ = gate_for(ROBOTS_DENIES_US_ALLOWS_STAR)
    check(
        gate.allows(PAGE) is False,
        "robots.txt denies %s by name; the `*` group must not override it"
        % ROBOTS_AGENT,
    )


def test_named_deny_means_the_page_is_never_fetched() -> None:
    """The denial has to stop the HTTP request, not only the return value."""
    gate, session = gate_for(ROBOTS_DENIES_US_ALLOWS_STAR)
    result = fetch_page(session, gate, PAGE, timeout=5, base_delay=0.0)
    check(result["html"] == "", "a denied page must come back with no HTML")
    check(result["status"] is None, "a denied page has no HTTP status")
    check(
        "robots.txt" in (result["error"] or ""),
        "the error must say robots.txt denied it: %r" % result["error"],
    )
    check(
        session.asked == [ROBOTS],
        "only robots.txt may be requested; asked for %r" % session.asked,
    )


def test_named_allow_beats_star_deny() -> None:
    """The fallback must not deny us when our own group allows the path."""
    gate, session = gate_for(ROBOTS_ALLOWS_US_DENIES_STAR)
    check(gate.allows(PAGE) is True, "our own group allows /status")
    result = fetch_page(session, gate, PAGE, timeout=5, base_delay=0.0)
    check(result["error"] is None, "an allowed page must not error: %r" % result)
    check(result["html"] == HTML, "an allowed page returns its HTML")
    check(PAGE in session.asked, "the page must have been requested")


def test_star_rules_apply_when_no_group_names_us() -> None:
    """With no group for our agent, `*` is the rule that counts."""
    denied, _ = gate_for(ROBOTS_ONLY_STAR_DENIES)
    check(denied.allows(PAGE) is False, "`*` disallows /status")
    allowed, _ = gate_for(ROBOTS_ONLY_STAR_ALLOWS)
    check(allowed.allows(PAGE) is True, "`*` disallows only /private")


def test_missing_robots_allows_and_forbidden_robots_denies() -> None:
    """404 means no rules published; 401/403 means everything denied."""
    gate_404, _ = gate_for("", status=404)
    check(gate_404.allows(PAGE) is True, "404 robots.txt: no rules published")
    gate_403, _ = gate_for("", status=403)
    check(gate_403.allows(PAGE) is False, "403 robots.txt: everything denied")


def test_robots_is_fetched_once_per_host() -> None:
    """The parser is cached, so a second URL does not refetch robots.txt."""
    gate, session = gate_for(ROBOTS_ONLY_STAR_ALLOWS)
    gate.allows(PAGE)
    gate.allows(SITE + "/other")
    check(
        session.asked.count(ROBOTS) == 1,
        "robots.txt must be fetched once per host; asked %r" % session.asked,
    )


def test_crawl_delay_is_read() -> None:
    """A Crawl-delay for our agent is honoured."""
    body = "User-agent: %s\nCrawl-delay: 7\nDisallow:\n" % ROBOTS_AGENT
    gate, _ = gate_for(body)
    check(gate.crawl_delay(PAGE) == 7.0, "Crawl-delay: 7 must be read as 7.0")


TESTS = [
    ("a named Disallow beats a permissive `*`", test_named_deny_beats_star_allow),
    ("a named Disallow stops the fetch", test_named_deny_means_the_page_is_never_fetched),
    ("a named Allow beats a restrictive `*`", test_named_allow_beats_star_deny),
    ("`*` applies when no group names us", test_star_rules_apply_when_no_group_names_us),
    ("404 allows, 403 denies", test_missing_robots_allows_and_forbidden_robots_denies),
    ("robots.txt is fetched once per host", test_robots_is_fetched_once_per_host),
    ("crawl delay is read", test_crawl_delay_is_read),
]


def main() -> int:
    print("robots gate tests (no network)")
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
