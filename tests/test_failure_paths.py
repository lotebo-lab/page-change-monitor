"""Every way we know a run from someone else could end FAILED, reproduced offline.

Why this file exists: on 23/09/2026 the public stats of the Actor showed
FAILED 3, SUCCEEDED 0 for runs by other users, while our own runs succeeded.
Each test below is one candidate path. The rule it enforces is the one the
README sells: a bad page, a bad selector or a bad URL becomes a row with an
`error`, never a failed run. Only the platform (timeout, memory) may kill a run.

Two kinds of test:
* unit probes on the pure functions (fast, in process);
* whole runs of src/main.py through tests/run_scenario.py, one subprocess per
  scenario, with the pricing environment the platform gives a paying user.

Plain Python, own runner, no pytest and no network:

    ../../.venv/bin/python tests/test_failure_paths.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from fingerprint import fingerprint_html  # noqa: E402
from main import RobotsGate, fetch_page, normalize_targets  # noqa: E402

FAILURES: list[str] = []
PASSED = 0

# What the platform puts in the environment of a pay-per-event run started by
# another user: the two events of .actor/actor.json with their prices.
PPE_PRICING = {
    "pricingModel": "PAY_PER_EVENT",
    "pricingPerEvent": {
        "actorChargeEvents": {
            "page-checked": {"eventTitle": "Page checked", "eventPriceUsd": 0.05},
            "change-detected": {"eventTitle": "Change detected", "eventPriceUsd": 0.02},
        }
    },
}

WIKI = "https://en.wikipedia.org/wiki/Main_Page"
WIKI_HTML = (
    "<html><body><div id='mp-tfa'><p>Today's featured article.</p></div>"
    "</body></html>"
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(name: str, func) -> None:
    global PASSED
    try:
        func()
    except Exception:  # noqa: BLE001
        FAILURES.append(name)
        print("FAIL  %s" % name)
        print(traceback.format_exc())
    else:
        PASSED += 1
        print("ok    %s" % name)


def run_actor(scenario: dict, env: dict | None = None, run_dir: str | None = None) -> dict:
    """Run src/main.py once in a subprocess; return exit_code, rows, summary."""
    run_dir = run_dir or tempfile.mkdtemp(prefix="pcm-scenario-")
    scenario_file = os.path.join(run_dir, "scenario.json")
    with open(scenario_file, "w") as handle:
        json.dump(scenario, handle)
    full_env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("APIFY_", "ACTOR_", "CRAWLEE_"))
    }
    full_env.update(env or {})
    proc = subprocess.run(
        [sys.executable, os.path.join(HERE, "run_scenario.py"), run_dir, scenario_file],
        capture_output=True,
        text=True,
        env=full_env,
        timeout=120,
    )
    lines = [line for line in proc.stdout.splitlines() if line.startswith("{")]
    check(lines, "runner printed no result; stderr:\n%s" % proc.stderr[-3000:])
    result = json.loads(lines[-1])
    result["log"] = proc.stderr
    return result


def ppe_env(max_charge: str | None = None) -> dict:
    env = {
        "APIFY_ACTOR_PRICING_INFO": json.dumps(PPE_PRICING),
        # An empty {} reads as "not set" in SDK 4.0.2, so give it one zero.
        "APIFY_CHARGED_ACTOR_EVENT_COUNTS": json.dumps({"page-checked": 0}),
    }
    if max_charge is not None:
        env["ACTOR_MAX_TOTAL_CHARGE_USD"] = max_charge
    return env


def assert_succeeded(result: dict, what: str) -> None:
    check(
        result["exit_code"] == 0 and result["error"] is None,
        "%s: run must succeed, got exit %r error %r\n%s"
        % (what, result["exit_code"], result["error"], result["log"][-2500:]),
    )


# --------------------------------------------------------------------------
# Unit probes
# --------------------------------------------------------------------------


def _deep(tag: str, depth: int) -> str:
    return "<html><body>" + ("<%s>x" % tag) * depth + "</body></html>"


def test_deeply_nested_page_does_not_raise() -> None:
    """Real pages with thousands of unclosed tags nest that deep in html.parser.

    `_serialize` walked the tree recursively, one Python frame per level, so a
    page nested deeper than the recursion limit raised RecursionError out of
    fingerprint_html, which is outside every try in main.py: the run FAILED.
    """
    for tag in ("div", "font", "span"):
        for selector in (None, "body"):
            try:
                shot = fingerprint_html(_deep(tag, 3000), selector)
            except RecursionError:
                raise AssertionError(
                    "fingerprint_html raised RecursionError on %d nested <%s> "
                    "(selector %r)" % (3000, tag, selector)
                )
            check(shot["found"] or shot["error"], "must return a verdict")


def test_deep_fingerprint_is_stable_and_detects_change() -> None:
    a = fingerprint_html(_deep("div", 3000), None)
    b = fingerprint_html(_deep("div", 3000), None)
    c = fingerprint_html(_deep("div", 3000).replace("x</body>", "y</body>"), None)
    check(a["found"] and a["fingerprint"] == b["fingerprint"], "same page, same fingerprint")
    check(a["fingerprint"] != c["fingerprint"], "a changed leaf must change the fingerprint")


def test_iterative_fingerprint_matches_known_value() -> None:
    """Rewriting the walk must not change fingerprints stored by earlier runs.

    The value below was computed by the recursive walk of build 0.1.12.
    """
    html = (
        "<html><body><main id='content-123' class='b a'><!-- c -->"
        "<h1>Title</h1><script>x=1</script><p nonce='zz'>Hello  <b>world</b></p>"
        "</main></body></html>"
    )
    shot = fingerprint_html(html, "main")
    check(
        shot["fingerprint"] == KNOWN_MAIN_FINGERPRINT,
        "fingerprint changed: %s" % shot["fingerprint"],
    )
    check(shot["text"] == "Title Hello world", "text: %r" % shot["text"])


# Computed with the recursive _serialize of build 0.1.12 (see test above).
KNOWN_MAIN_FINGERPRINT = (
    "sha256:0b4188fba5b20a95bd06a5408901de93187d6ac041835585956b477f1ab0d5e9"
)


class _Session:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def get(self, url, **kwargs):  # noqa: ANN001
        self.asked.append(url)
        raise AssertionError("must not be reached for a malformed URL")


def test_malformed_url_is_an_error_row_not_an_exception() -> None:
    """`http://[::1` makes urlsplit raise ValueError inside the robots gate."""
    session = _Session()
    gate = RobotsGate(session, timeout=5)
    for bad in ("http://[::1", "https://[not-an-ip]/x"):
        try:
            result = fetch_page(session, gate, bad, timeout=5, base_delay=0.0)
        except Exception as exc:  # noqa: BLE001
            raise AssertionError("fetch_page raised %s for %r" % (type(exc).__name__, bad))
        check(result["error"], "a malformed URL must come back with an error: %r" % result)


def test_odd_input_shapes_are_normalized() -> None:
    targets = normalize_targets(
        [
            "example.com",
            {"url": "https://a.test", "selector": 123},
            {"url": "https://b.test", "selector": ["#x"]},
            {"url": None},
            {"selector": "#only"},
            42,
            None,
        ]
    )
    urls = [t["url"] for t in targets]
    check(urls == ["https://example.com", "https://a.test", "https://b.test"], urls)
    for target in targets:
        check(
            target["selector"] is None or isinstance(target["selector"], str),
            "selector must be str or None, got %r" % (target["selector"],),
        )


# --------------------------------------------------------------------------
# Whole runs
# --------------------------------------------------------------------------


def test_prefill_as_paying_user_succeeds() -> None:
    result = run_actor(
        {"input": {"urls": [{"url": WIKI, "selector": "#mp-tfa"}]},
         "pages": {WIKI: [200, "text/html; charset=UTF-8", WIKI_HTML]}},
        env=ppe_env(),
    )
    assert_succeeded(result, "prefill, pay per event")
    check(len(result["rows"]) == 1, "one row expected: %r" % result["rows"])
    check(result["summary"]["chargedEvents"].get("page-checked") == 1,
          "%r / pricing seen %r" % (result["summary"], result.get("pricing")))


def test_example_input_all_pages_blocked_succeeds() -> None:
    """Wikipedia answering 403 to a datacenter IP must not fail the run."""
    example = {
        "urls": [
            {"url": WIKI, "selector": "#mp-tfa"},
            {"url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
             "selector": ".price_color"},
            {"url": "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use",
             "selector": "#mw-content-text"},
        ],
        "requestDelaySeconds": 0,
        "requestTimeoutSeconds": 20,
        "excerptChars": 200,
    }
    result = run_actor(
        {"input": example,
         "pages": {WIKI: [403, "text/html", "<html><body>Forbidden</body></html>"],
                   "https://en.wikipedia.org/robots.txt": [200, "text/plain", "User-agent: *\nDisallow: /w/\n"]},
         "raise": {"https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use": "ConnectionError"}},
        env=ppe_env(),
    )
    assert_succeeded(result, "all pages fail")
    check(len(result["rows"]) == 3, "three error rows expected: %r" % result["rows"])


def test_robots_denies_everything_succeeds() -> None:
    result = run_actor(
        {"input": {"urls": [WIKI]},
         "pages": {"https://en.wikipedia.org/robots.txt": [200, "text/plain", "User-agent: *\nDisallow: /\n"]}},
        env=ppe_env(),
    )
    assert_succeeded(result, "robots denies")
    check("robots.txt" in (result["rows"][0]["error"] or ""), result["rows"])


def test_empty_and_useless_input_succeeds() -> None:
    for actor_input in ({"urls": []}, {"urls": [{"selector": "#x"}, ""]}, {}):
        result = run_actor({"input": actor_input}, env=ppe_env())
        assert_succeeded(result, "input %r" % actor_input)


def test_selector_missing_and_invalid_succeeds() -> None:
    page = "https://books.toscrape.com/p"
    result = run_actor(
        {"input": {"urls": [{"url": page, "selector": ".stock-status-badge"},
                            {"url": page, "selector": "div[["},
                            {"url": page, "selector": 7}],
                   "requestDelaySeconds": 0},
         "pages": {page: [200, "text/html", "<html><body><p class='price_color'>1</p></body></html>"]}},
        env=ppe_env(),
    )
    assert_succeeded(result, "bad selectors")
    check(len(result["rows"]) == 3, result["rows"])


def test_charge_limit_below_one_event_succeeds() -> None:
    result = run_actor(
        {"input": {"urls": [{"url": WIKI, "selector": "#mp-tfa"}]},
         "pages": {WIKI: [200, "text/html", WIKI_HTML]}},
        env=ppe_env(max_charge="0.01"),
    )
    assert_succeeded(result, "max charge 0.01")


def test_non_html_and_binary_succeeds() -> None:
    pdf = "https://example.test/file.pdf"
    result = run_actor(
        {"input": {"urls": [pdf, "https://example.test/nocontenttype"],
                   "requestDelaySeconds": 0},
         "pages": {pdf: [200, "application/pdf", "%PDF-1.4 binary"],
                   "https://example.test/nocontenttype": [200, "", "\x00\x01\x02"]}},
        env=ppe_env(),
    )
    assert_succeeded(result, "non html")


def test_deep_page_whole_run_succeeds() -> None:
    page = "https://legacy.example.test/"
    result = run_actor(
        {"input": {"urls": [page]},
         "pages": {page: [200, "text/html", _deep("font", 3000)]}},
        env=ppe_env(),
    )
    assert_succeeded(result, "deep page")
    check(result["rows"] and result["rows"][0]["fingerprint"], result["rows"])


def test_malformed_url_whole_run_succeeds() -> None:
    result = run_actor(
        {"input": {"urls": ["http://[::1", {"url": WIKI, "selector": "#mp-tfa"}],
                   "requestDelaySeconds": 0},
         "pages": {WIKI: [200, "text/html", WIKI_HTML]}},
        env=ppe_env(),
    )
    assert_succeeded(result, "malformed url")
    check(len(result["rows"]) == 2, result["rows"])


def test_unexpected_request_exception_succeeds() -> None:
    """An error that is not a RequestException (e.g. from urllib3 or idna)."""
    page = "https://xn--broken.test/"
    result = run_actor(
        {"input": {"urls": [page, {"url": WIKI, "selector": "#mp-tfa"}],
                   "requestDelaySeconds": 0},
         "pages": {WIKI: [200, "text/html", WIKI_HTML]},
         "raise": {page: "UnicodeError"}},
        env=ppe_env(),
    )
    assert_succeeded(result, "UnicodeError from transport")
    check(len(result["rows"]) == 2, result["rows"])


def test_second_run_reads_state() -> None:
    run_dir = tempfile.mkdtemp(prefix="pcm-state-")
    scenario = {"input": {"urls": [{"url": WIKI, "selector": "#mp-tfa"}]},
                "pages": {WIKI: [200, "text/html", WIKI_HTML]}}
    first = run_actor(scenario, env=ppe_env(), run_dir=run_dir)
    assert_succeeded(first, "first run")
    scenario["pages"][WIKI][2] = WIKI_HTML.replace("Today's", "Tomorrow's")
    second = run_actor(scenario, env=ppe_env(), run_dir=run_dir)
    assert_succeeded(second, "second run")
    check(second["rows"][-1]["changed"] is True, second["rows"])


TESTS = [
    ("deeply nested page does not raise", test_deeply_nested_page_does_not_raise),
    ("deep fingerprint is stable and detects change", test_deep_fingerprint_is_stable_and_detects_change),
    ("fingerprint value unchanged from 0.1.12", test_iterative_fingerprint_matches_known_value),
    ("malformed URL is an error row", test_malformed_url_is_an_error_row_not_an_exception),
    ("odd input shapes are normalized", test_odd_input_shapes_are_normalized),
    ("run: prefill as paying user", test_prefill_as_paying_user_succeeds),
    ("run: example input, every page blocked", test_example_input_all_pages_blocked_succeeds),
    ("run: robots denies everything", test_robots_denies_everything_succeeds),
    ("run: empty and useless input", test_empty_and_useless_input_succeeds),
    ("run: missing, invalid and non-string selectors", test_selector_missing_and_invalid_succeeds),
    ("run: charge limit below one event", test_charge_limit_below_one_event_succeeds),
    ("run: non-HTML and binary bodies", test_non_html_and_binary_succeeds),
    ("run: deeply nested page", test_deep_page_whole_run_succeeds),
    ("run: malformed URL", test_malformed_url_whole_run_succeeds),
    ("run: non-requests exception from transport", test_unexpected_request_exception_succeeds),
    ("run: second run reads state", test_second_run_reads_state),
]


def main() -> int:
    print("failure path tests (no network)")
    only = sys.argv[1:]
    for name, func in TESTS:
        if only and not any(o in name for o in only):
            continue
        run(name, func)
    total = PASSED + len(FAILURES)
    if FAILURES:
        print("RESULT: %d/%d passed, FAILED: %s" % (PASSED, total, ", ".join(FAILURES)))
        return 1
    print("RESULT: %d/%d passed, 0 failed" % (PASSED, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
