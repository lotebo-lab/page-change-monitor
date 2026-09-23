"""Apify Actor entry point: Page Change Monitor.

Input is a list of URLs, each with an optional CSS selector. On every run the
Actor fetches each URL, fingerprints the selected part of the HTML
(`fingerprint.py`), compares that fingerprint with the one the previous run
stored in the Actor's named key-value store (`state.py`), and pushes one
dataset row per URL saying whether that part changed.

What it does not do: it does not run JavaScript, it does not log in, and it
does not go around a captcha or a paywall. It reads the HTML a plain HTTP
client receives, and only when the site's robots.txt allows that path for our
user agent.

Privacy: the only text stored is the excerpt of the element the user chose to
watch. Pointing this Actor at a page with personal data would put that data in
the dataset, which is why the README says not to.
"""

from __future__ import annotations

import asyncio
import time
import urllib.parse
import urllib.robotparser
from datetime import datetime, timezone
from typing import Any

import requests
from apify import Actor

try:  # running inside the Actor image (python src/main.py)
    from fingerprint import fingerprint_html
    from state import (
        DEFAULT_STORE_NAME,
        build_record,
        compare_records,
        load_record,
        record_key,
        save_record,
    )
except ImportError:  # running as a package (python -m src.main)
    from .fingerprint import fingerprint_html
    from .state import (
        DEFAULT_STORE_NAME,
        build_record,
        compare_records,
        load_record,
        record_key,
        save_record,
    )


# Pay-per-event. The Actor never charges `actor-start` in code; Apify charges
# that one itself. These two names and prices must match .actor/actor.json.
EVENT_PAGE_CHECKED = "page-checked"
EVENT_CHANGE_DETECTED = "change-detected"

# Hard ceiling for one charge round trip. On the platform every charge is an
# HTTP call to the Apify API. A charge without a timeout is what killed our
# first published Actor in the cloud: one hung call blocked the run until the
# platform timeout and nothing was stored. A charge that does not answer in
# time is treated like any other charging failure: warn and keep going.
CHARGE_TIMEOUT_SECONDS = 5.0

# We identify ourselves. A site owner who wants us gone can block this string
# in robots.txt and we will obey it on the next run.
USER_AGENT = (
    "Mozilla/5.0 (compatible; PageChangeMonitor/0.1; "
    "+https://apify.com/lotebo-lab/page-change-monitor)"
)
ROBOTS_AGENT = "PageChangeMonitor"

# Exactly the fields every dataset row carries. The views in
# .actor/dataset_schema.json are checked against this tuple by
# tests/test_schemas.py, so the store page can never promise a column that the
# run does not produce.
ITEM_FIELDS = (
    "url",
    "selector",
    "changed",
    "first_check",
    "previous_excerpt",
    "current_excerpt",
    "fingerprint",
    "checked_at",
    "status",
    "error",
)

DEFAULTS = {
    "urls": [],
    "requestDelaySeconds": 2,
    "requestTimeoutSeconds": 20,
    "excerptChars": 200,
}


def now_iso() -> str:
    """Current UTC time, ISO 8601, seconds precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_item(
    url: str,
    selector: str | None,
    changed: bool,
    first_check: bool,
    previous_excerpt: str,
    current_excerpt: str,
    fingerprint: str,
    checked_at: str,
    status: int | None,
    error: str | None,
) -> dict[str, Any]:
    """One dataset row. The literal keys here are the contract with the views."""
    return {
        "url": url,
        "selector": selector or None,
        "changed": bool(changed),
        "first_check": bool(first_check),
        "previous_excerpt": previous_excerpt or "",
        "current_excerpt": current_excerpt or "",
        "fingerprint": fingerprint or "",
        "checked_at": checked_at,
        "status": status,
        "error": error or None,
    }


def normalize_targets(raw: Any) -> list[dict[str, Any]]:
    """Accept a list of strings or of {url, selector} objects. Pure."""
    targets: list[dict[str, Any]] = []
    for entry in raw or []:
        if isinstance(entry, str):
            url, selector = entry.strip(), None
        elif isinstance(entry, dict):
            url = str(entry.get("url") or "").strip()
            selector = entry.get("selector")
            if selector is not None and not isinstance(selector, str):
                # A number or a list typed in the JSON editor. Kept as text so
                # the row names what the user wrote and the selector error
                # explains it, instead of a type error further down.
                selector = str(selector)
            selector = (selector or "").strip() or None
        else:
            continue
        if not url:
            continue
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        targets.append({"url": url, "selector": selector})
    return targets


class RobotsGate:
    """Fetches and caches robots.txt per host, and answers allowed/denied.

    A robots.txt that answers 404 or that cannot be fetched is treated as
    "no rules published", which is what the standard says. A robots.txt that
    answers 401 or 403 is treated as "everything denied", also per standard.
    """

    def __init__(self, session: requests.Session, timeout: int) -> None:
        self._session = session
        self._timeout = timeout
        self._cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _parser(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parts = urllib.parse.urlsplit(url)
        origin = "%s://%s" % (parts.scheme, parts.netloc)
        if origin in self._cache:
            return self._cache[origin]

        parser: urllib.robotparser.RobotFileParser | None = None
        try:
            response = self._session.get(
                origin + "/robots.txt", timeout=self._timeout
            )
            if response.status_code in (401, 403):
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(["User-agent: *", "Disallow: /"])
            elif 200 <= response.status_code < 300:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(response.text.splitlines())
            else:
                parser = None  # 404 and friends: no rules published
        except Exception:  # noqa: BLE001 - robots unreachable is not fatal
            parser = None

        self._cache[origin] = parser
        return parser

    def allows(self, url: str) -> bool:
        """True only if robots.txt allows this path for our user agent.

        One call, one answer: `can_fetch` already resolves the precedence the
        standard asks for. Its `_find_entry` looks for the group that names our
        agent and only falls back to the `*` group when no group names us. So a
        site that disallows us by name and allows `*` denies us, which is what
        the module docstring promises. Asking for `*` as well and OR-ing the
        two answers would throw that away.
        """
        parser = self._parser(url)
        if parser is None:
            return True
        return parser.can_fetch(ROBOTS_AGENT, url)

    def crawl_delay(self, url: str) -> float:
        parser = self._parser(url)
        if parser is None:
            return 0.0
        for agent in (ROBOTS_AGENT, "*"):
            try:
                value = parser.crawl_delay(agent)
            except Exception:  # noqa: BLE001
                value = None
            if value:
                return float(value)
        return 0.0


def fetch_page(
    session: requests.Session,
    gate: RobotsGate,
    url: str,
    timeout: int,
    base_delay: float,
) -> dict[str, Any]:
    """Fetch one URL politely. Never raises; returns html, status and error.

    Runs in a worker thread: `requests` is synchronous and the delay sleeps.

    "Never raises" is enforced here and not only hoped for: a malformed URL
    such as `http://[::1` makes urlsplit raise ValueError inside the robots
    gate, and the transport can raise errors that are not RequestException
    (UnicodeError from idna, LocationParseError from urllib3). Before 0.1.13
    any of those escaped to main() and failed the whole run.
    """
    try:
        return _fetch_page(session, gate, url, timeout, base_delay)
    except Exception as exc:  # noqa: BLE001 - one bad URL must not stop a run
        return {
            "html": "",
            "status": None,
            "error": "could not request this URL (%s: %s)"
            % (type(exc).__name__, exc),
        }


def _fetch_page(
    session: requests.Session,
    gate: RobotsGate,
    url: str,
    timeout: int,
    base_delay: float,
) -> dict[str, Any]:
    if not gate.allows(url):
        return {
            "html": "",
            "status": None,
            "error": "robots.txt of this site disallows %s for our user agent"
            % url,
        }

    delay = max(float(base_delay or 0), gate.crawl_delay(url))
    if delay > 0:
        time.sleep(delay)

    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
    except requests.Timeout:
        return {"html": "", "status": None, "error": "request timed out"}
    except requests.RequestException as exc:
        return {"html": "", "status": None, "error": "request failed: %s" % exc}

    status = response.status_code
    if status >= 400:
        return {"html": "", "status": status, "error": "HTTP %d" % status}

    content_type = (response.headers.get("Content-Type") or "").lower()
    if content_type and "html" not in content_type and "xml" not in content_type:
        return {
            "html": "",
            "status": status,
            "error": "the response is not HTML (Content-Type: %s)" % content_type,
        }

    return {"html": response.text, "status": status, "error": None}


async def charge_one(event_name: str, state: dict) -> bool:
    """Charge one event. False means: stop charging and stop the run.

    The only reason to answer False is a real pay-per-event limit: the user's
    budget for this run is spent. A timeout, an API hiccup or charging being
    off lets the run continue, because the work is already done or free.
    """
    if state["limit_reached"]:
        return False
    try:
        result = await asyncio.wait_for(
            Actor.charge(event_name=event_name),
            timeout=CHARGE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        state["failures"] += 1
        Actor.log.warning(
            "Charging %s timed out after %.0f s; continuing the run."
            % (event_name, CHARGE_TIMEOUT_SECONDS)
        )
        return True
    except Exception as exc:  # noqa: BLE001 - never kill a paid run
        state["failures"] += 1
        Actor.log.warning("Could not charge %s: %s" % (event_name, exc))
        return True

    if getattr(result, "event_charge_limit_reached", False):
        state["limit_reached"] = True
        Actor.log.info(
            "Charge limit reached. Keeping every result stored so far and "
            "stopping here."
        )
        return False
    charged = getattr(result, "charged_count", 0) or 0
    if charged < 1:
        # Not a limit: the platform ignored the charge. Keep going.
        state["failures"] += 1
        return True
    state["charged"][event_name] = state["charged"].get(event_name, 0) + charged
    return True


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        options = {
            **DEFAULTS,
            **{k: v for k, v in actor_input.items() if v is not None},
        }

        targets = normalize_targets(options["urls"])
        delay = max(0.0, float(options["requestDelaySeconds"] or 0))
        timeout = max(3, int(options["requestTimeoutSeconds"] or 20))
        excerpt_chars = max(0, int(options["excerptChars"] or 0))

        if not targets:
            Actor.log.warning("No usable URL in the input. Nothing to check.")
            await Actor.set_value(
                "SUMMARY",
                {
                    "urlsRequested": 0,
                    "urlsChecked": 0,
                    "changesDetected": 0,
                    "firstChecks": 0,
                    "errors": 0,
                    "chargedEvents": {},
                    "chargeLimitReached": False,
                    "chargeFailures": 0,
                },
            )
            return

        Actor.log.info(
            "Checking %d URL(s), delay %.1f s, timeout %d s."
            % (len(targets), delay, timeout)
        )

        # Only a run billed per event can be charged. Under any other pricing
        # model the SDK ignores the charge, and that must not stop the check.
        pricing = Actor.get_charging_manager().get_pricing_info()
        is_pay_per_event = pricing.is_pay_per_event
        if not is_pay_per_event:
            Actor.log.info(
                "This run is not billed per event (pricing model: %s). "
                "Checking without charging." % pricing.pricing_model
            )

        store = await Actor.open_key_value_store(name=DEFAULT_STORE_NAME)

        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
        gate = RobotsGate(session, timeout)

        charge_state: dict[str, Any] = {
            "limit_reached": False,
            "charged": {},
            "failures": 0,
        }
        checked = 0
        pushed = 0
        changes = 0
        first_checks = 0
        errors = 0

        for index, target in enumerate(targets):
            url = target["url"]
            selector = target["selector"]
            key = record_key(url, selector)
            checked_at = now_iso()

            fetched = await asyncio.to_thread(
                fetch_page,
                session,
                gate,
                url,
                timeout,
                delay if index > 0 else 0.0,
            )

            error = fetched["error"]
            status = fetched["status"]
            current_fingerprint = ""
            current_excerpt = ""

            if not error:
                shot = fingerprint_html(fetched["html"], selector, excerpt_chars)
                if shot["found"]:
                    current_fingerprint = shot["fingerprint"]
                    current_excerpt = shot["excerpt"]
                else:
                    error = shot["error"]

            previous = await load_record(store, key)
            current_record = build_record(
                url=url,
                selector=selector,
                fingerprint=current_fingerprint,
                excerpt=current_excerpt,
                checked_at=checked_at,
            )
            verdict = compare_records(previous, current_record)

            if current_fingerprint:
                # Only a URL we actually read is a URL we charge for.
                if is_pay_per_event and not await charge_one(
                    EVENT_PAGE_CHECKED, charge_state
                ):
                    break
                checked += 1
                if verdict["first_check"]:
                    first_checks += 1
                if verdict["changed"]:
                    changes += 1
                    if is_pay_per_event and not await charge_one(
                        EVENT_CHANGE_DETECTED, charge_state
                    ):
                        break
                await save_record(store, key, current_record)
            else:
                errors += 1
                Actor.log.warning("%s: %s" % (url, error))

            await Actor.push_data(
                build_item(
                    url=url,
                    selector=selector,
                    changed=verdict["changed"],
                    first_check=verdict["first_check"],
                    previous_excerpt=verdict["previous_excerpt"],
                    current_excerpt=current_excerpt,
                    fingerprint=current_fingerprint,
                    checked_at=checked_at,
                    status=status,
                    error=error,
                )
            )
            pushed += 1

        Actor.log.info(
            f"Wrote {pushed} row(s) to dataset "
            f"{Actor.configuration.default_dataset_id}"
        )

        summary = {
            "urlsRequested": len(targets),
            "urlsChecked": checked,
            "changesDetected": changes,
            "firstChecks": first_checks,
            "errors": errors,
            "chargedEvents": charge_state["charged"],
            "chargeLimitReached": charge_state["limit_reached"],
            "chargeFailures": charge_state["failures"],
        }
        await Actor.set_value("SUMMARY", summary)

        if charge_state["limit_reached"]:
            Actor.log.info(
                "The run stopped early because it reached its pay-per-event "
                "charge limit. Raise the limit to check more URLs."
            )
        Actor.log.info(
            "Finished: %d URL(s) read, %d change(s) detected, %d first check(s), "
            "%d error(s)." % (checked, changes, first_checks, errors)
        )


if __name__ == "__main__":
    asyncio.run(main())
