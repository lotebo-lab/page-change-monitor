"""Run the real Actor entry point once, offline, against a scripted web.

Used by tests/test_failure_paths.py, one subprocess per scenario, so every
scenario gets a fresh Actor lifecycle and a fresh local storage.

Usage:
    python tests/run_scenario.py <run-dir> <scenario.json>

The scenario file holds:
    input:  the Actor input, written to the default store as INPUT.json;
    pages:  {url: [status, content_type, body]} served by a fake transport;
            any URL not listed answers 404 (so robots.txt is "no rules");
    raise:  {url: "ExceptionName"} for URLs whose request must raise.

The environment decides the pricing model, exactly like on the platform:
APIFY_ACTOR_PRICING_INFO, APIFY_CHARGED_ACTOR_EVENT_COUNTS and
ACTOR_MAX_TOTAL_CHARGE_USD are read by the SDK itself.

The last line printed is a JSON object: exit_code, rows, summary.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from pathlib import Path

import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))


class ScriptedAdapter(BaseAdapter):
    def __init__(self, pages: dict, raises: dict) -> None:
        super().__init__()
        self.pages = pages
        self.raises = raises

    def send(self, request, stream=False, timeout=None, verify=True, cert=None,
             proxies=None):  # noqa: D102
        url = request.url
        if url in self.raises:
            name = self.raises[url]
            import builtins  # noqa: PLC0415

            exc_type = getattr(requests.exceptions, name, None) or getattr(
                builtins, name
            )
            raise exc_type("scripted failure for %s" % url)
        status, content_type, body = self.pages.get(
            url, [404, "text/html", "<html><body>404</body></html>"]
        )
        raw = body.encode("utf-8") if isinstance(body, str) else body
        response = requests.Response()
        response.status_code = status
        response.url = url
        response.request = request
        response.encoding = "utf-8"
        response.headers = CaseInsensitiveDict({"Content-Type": content_type})
        response.raw = io.BytesIO(raw)
        return response

    def close(self) -> None:
        return None


def main() -> int:
    run_dir = Path(sys.argv[1]).resolve()
    scenario = json.loads(Path(sys.argv[2]).read_text())

    input_dir = run_dir / "storage" / "key_value_stores" / "default"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "INPUT.json").write_text(json.dumps(scenario["input"]))
    os.chdir(run_dir)

    adapter = ScriptedAdapter(scenario.get("pages", {}), scenario.get("raise", {}))
    requests.Session.get_adapter = lambda self, url: adapter  # type: ignore

    import main as actor_main  # noqa: PLC0415

    exit_code = 0
    error = None
    try:
        asyncio.run(actor_main.main())
    except SystemExit as exc:
        exit_code = 0 if exc.code is None else int(exc.code)
    except BaseException as exc:  # noqa: BLE001 - report, do not hide
        exit_code = 1
        error = "%s: %s" % (type(exc).__name__, exc)

    rows = []
    dataset_dir = run_dir / "storage" / "datasets" / "default"
    for item in sorted(dataset_dir.glob("[0-9]*.json")):
        rows.append(json.loads(item.read_text()))
    summary = None
    for name in ("SUMMARY", "SUMMARY.json"):
        path = input_dir / name
        if path.is_file():
            summary = json.loads(path.read_text())
            break
    from apify import Configuration  # noqa: PLC0415

    config = Configuration()
    pricing = {
        "env": os.environ.get("APIFY_ACTOR_PRICING_INFO"),
        "parsed_model": getattr(config.actor_pricing_info, "pricing_model", None),
        "counts": config.charged_event_counts,
    }
    print(json.dumps({"exit_code": exit_code, "error": error, "rows": rows,
                      "summary": summary, "pricing": pricing}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
