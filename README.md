# Website Change Monitor: Watch One CSS Selector, Not the Whole Page
The pages you depend on (a supplier price block, a clause in a terms of service, a status page with no feed) change without telling you.
**Run it on the Apify Store: https://apify.com/lotebo-lab/page-change-monitor**

Give this Actor a list of URLs, each with an optional CSS selector. Every run fetches the pages, compares the watched part with what it stored on the previous run, and returns one row per URL saying whether that part changed, with the old text and the new text side by side.

This repository holds the source code. The Actor runs on the Apify platform, so there is nothing to install and nothing to host.

## Quick start

1. Open https://apify.com/lotebo-lab/page-change-monitor and switch the input to JSON.
2. Paste this input, which is valid against [`.actor/input_schema.json`](.actor/input_schema.json), and start the run:

```json
{
  "urls": [
    {
      "url": "https://en.wikipedia.org/wiki/Main_Page",
      "selector": "#mp-tfa"
    }
  ],
  "requestDelaySeconds": 2,
  "requestTimeoutSeconds": 20,
  "excerptChars": 200
}
```

Price, as read from the public Apify Store API (`currentPricingInfo`) on 2026-09-23 16:25 UTC: US$ 0.05 per `page-checked` event (one URL read with its selector matched) plus US$ 0.02 per `change-detected` event, only when the watched part changed. Apify charges the platform usage of the run on top; that part is set by the platform, not by this Actor. The full table is under "Price".

## Use cases

Each page below is a ready-made run of this Actor: it shows the input used, the fields that come back, and a Run button. The same page is served as Markdown by adding `.md` to the URL.

| question | page |
|---|---|
| How do I get told when one part of a web page changes? | https://apify.com/lotebo-lab/page-change-monitor/examples/watch-one-section-of-a-page-for-changes |
| How do I watch only one section of a page, not the whole page? | https://apify.com/lotebo-lab/page-change-monitor/examples/watch-only-one-section-of-a-page-not-the-whole-page |
| How do I see exactly what changed on a competitor pricing page? | https://apify.com/lotebo-lab/page-change-monitor/examples/see-exactly-what-changed-on-a-competitor-pricing-page |
| Did a supplier terms page change since the last run? | https://apify.com/lotebo-lab/page-change-monitor/examples/check-if-a-supplier-terms-page-changed-since-last-run |
| How do I know when a vendor publishes new release notes? | https://apify.com/lotebo-lab/page-change-monitor/examples/know-when-a-vendor-publishes-new-release-notes |
| How do I check a list of pages in one run and see which ones changed? | https://apify.com/lotebo-lab/page-change-monitor/examples/check-many-pages-in-one-run-and-see-which-changed |
| Which supplier product pages failed the last check? | https://apify.com/lotebo-lab/page-change-monitor/examples/which-supplier-product-pages-failed-the-last-check |

Who runs it: procurement and finance, on a supplier price page or plan table where a number moves quietly; legal and compliance, on the terms or privacy policy of a platform the business depends on; engineering and operations, on a changelog, release or status page that publishes no feed; and anyone tracking a public list that is updated in place rather than appended to.

The selector is what makes it usable: you watch the price block, the version number or the clause, and the menus, banners and cookie notices do not wake you up.

## Run it on a schedule (this is the point)

This Actor answers "did it change since the last check?", and a single run cannot answer that. **The first run on a URL only records the baseline:** every row comes back with `first_check: true` and `changed: false`, no matter how long the page has been sitting there, because there is nothing to compare it against yet. From the second run on, each run compares the page with what the run before stored.

So set it to run again by itself. On the Apify platform you schedule the Actor directly, with no task to create first: in Schedules, "Click on the Add dropdown and select whether you want to schedule an Actor or task", pick this Actor, and write the interval as a cron expression with six positions. There is one prerequisite, and it is the baseline again: "To schedule an Actor, you need to have run it at least once before". So press Start once, let that run be the baseline, then schedule it. The platform's floor is that "The minimum interval between runs is 10 seconds". The steps are in the Apify documentation: https://docs.apify.com/platform/schedules

Schedules are not a paid extra. The Apify limits page lists "Maximum number of schedules per user: 100", and the number is the same in every plan column, including Free: https://docs.apify.com/platform/limits

Daily is the setting most people want: it keeps the bill small and still catches the change on the day it happens.

One thing to know about the memory. The baseline is not stored inside the Actor: it is a named key-value store record in **your own account**, keyed by the pair (URL, selector). It survives between runs and it is yours to read or delete. If that store is deleted, or if you change the URL or the selector, the next run is a first run again for those rows.

## What goes in

These are the fields of [`.actor/input_schema.json`](.actor/input_schema.json), with the defaults and the ranges the schema declares.

| field | type | required | default | range |
|---|---|---|---|---|
| `urls` | array of `{ url, selector }` objects | yes | — | a plain URL string is also accepted and means the whole page body |
| `requestDelaySeconds` | integer | no | 2 | 0 to 60 seconds, waited before each request after the first |
| `requestTimeoutSeconds` | integer | no | 20 | 3 to 120 seconds before a URL is reported as a timeout |
| `excerptChars` | integer | no | 200 | 0 to 5000 characters kept in `previous_excerpt` and `current_excerpt`; `0` stores no page text at all |

An example input, using the value the schema prefills for `urls`. It watches one block of a public page, so the first run is the baseline and a second run tells you whether that block changed in between:

```json
{
  "urls": [
    { "url": "https://en.wikipedia.org/wiki/Main_Page", "selector": "#mp-tfa" }
  ],
  "requestDelaySeconds": 2,
  "requestTimeoutSeconds": 20,
  "excerptChars": 200
}
```

Notes on the input, as the code handles it:

- the `selector` is standard CSS, handled by BeautifulSoup. When it matches several elements, all of them are watched together, in document order;
- without a selector the whole `<body>` is watched, which is noisier: any edit anywhere on the page counts;
- the pair **(URL, selector)** is the identity of a watch. The same page watched with two selectors keeps two independent histories, and changing either one starts a new history;
- if `robots.txt` asks for a longer `Crawl-delay` than your `requestDelaySeconds`, the longer value wins.

## What comes out

One dataset row per URL checked. Every row has exactly these ten fields and nothing else; the same names are declared in [`.actor/dataset_schema.json`](.actor/dataset_schema.json) and checked against what the code writes by `tests/test_schemas.py`.

| field | type | what it holds |
|---|---|---|
| `url` | string | the page that was checked, as given in the input |
| `selector` | string or null | the CSS selector that narrowed the check, `null` when the whole page body was watched |
| `changed` | boolean | `true` when the watched part differs from the previous run. `false` on a first check, because there is nothing to compare against yet |
| `first_check` | boolean | `true` when this run is the first time this URL and selector were seen |
| `previous_excerpt` | string | the text of the watched part as the previous run saw it, cut at `excerptChars`. Empty on a first check |
| `current_excerpt` | string | the text of the watched part in this run, cut at `excerptChars` |
| `fingerprint` | string | `sha256:` of the normalised watched part, the value compared on the next run. Empty when the page could not be read |
| `checked_at` | string | when this check ran, ISO 8601 in UTC |
| `status` | integer or null | the HTTP status of the response, `null` when there was no response |
| `error` | string or null | why this URL could not be checked, `null` when it was checked. Reasons include a timeout, an HTTP error, a selector that matched nothing, a response that is not HTML, and a path closed by the site's `robots.txt` |

The dataset ships three ready-made views, declared in the same schema: **All fields**, **What changed** and **Not checked**. Every run also writes a `SUMMARY` record in the key-value store with `urlsRequested`, `urlsChecked`, `changesDetected`, `firstChecks`, `errors`, `chargedEvents`, `chargeLimitReached` and `chargeFailures`.

### What counts as a change

The fingerprint is taken from the HTML of the watched part after the noise is removed, so a redeploy does not look like an edit:

- HTML comments, `<script>`, `<style>`, `<noscript>` and `<template>` are dropped;
- whitespace and line breaks are collapsed, so reindenting a template is not a change;
- volatile attributes go away: `nonce`, CSRF tokens, request, trace and session ids, render timestamps, `data-reactid`, `integrity`;
- the random-looking numeric or hex suffix frameworks add to `id` and `for` is removed, and `class` tokens are sorted.

What stays inside the fingerprint, on purpose: the tag structure, the tag names, every other attribute and the text. So a changed link target counts as a change, not only visible text. A typo fix counts as a change too: this is not a semantic diff. The rules are in [`src/fingerprint.py`](src/fingerprint.py) and every one of them has a test in `tests/test_fingerprint.py`.

### Real output rows

The three rows below come from an end-to-end run of `src/main.py` recorded on 2026-09-20: the second run of a pair, with the pages served by a **local test server on `127.0.0.1`** from `tests/fixtures/run2`, not by a real site. Between the two runs the starter price changed from EUR 49 to EUR 59, the terms page did not change, and a third URL was left pointing at a page that answers 404 on purpose.

The change, with the old and the new value in the same row:

```json
{"changed": true, "checked_at": "2026-09-20T06:00:56+00:00", "current_excerpt": "EUR 59 per month", "error": null, "fingerprint": "sha256:e58cb5bea6d95283a69822ea1b13730151e07ca8cae7e0354684c177ba26ac4a", "first_check": false, "previous_excerpt": "EUR 49 per month", "selector": "#plan-starter .price", "status": 200, "url": "http://127.0.0.1:8099/pricing.html"}
```

The page that did not change, still returned so you can see it was really checked:

```json
{"changed": false, "checked_at": "2026-09-20T06:00:56+00:00", "current_excerpt": "Terms of service Version 4.2, in force since 1 March 2026. Notice period for cancellation: 30 days.", "error": null, "fingerprint": "sha256:d0e612c7332f52decaecb1e02b9a8402dd5f6d07eb12dea073a17512e7e6a310", "first_check": false, "previous_excerpt": "Terms of service Version 4.2, in force since 1 March 2026. Notice period for cancellation: 30 days.", "selector": "main", "status": 200, "url": "http://127.0.0.1:8099/terms.html"}
```

The URL that failed, reported as an error and never as "no change":

```json
{"changed": false, "checked_at": "2026-09-20T06:00:56+00:00", "current_excerpt": "", "error": "HTTP 404", "fingerprint": "", "first_check": true, "previous_excerpt": "", "selector": "main", "status": 404, "url": "http://127.0.0.1:8099/gone.html"}
```

The `SUMMARY` record of the same run:

```json
{"urlsRequested": 3, "urlsChecked": 2, "changesDetected": 1, "firstChecks": 0, "errors": 1, "chargedEvents": {}, "chargeLimitReached": false, "chargeFailures": 0}
```

The first run of the same pair has `first_check: true` and `changed: false` on every row. That run is the baseline. The log files of both runs are kept in our build workspace and are **not** published here: `logs/` is in `.gitignore`. You can reproduce the pair with `tests/run_local_e2e.py`.

## Price

Pay per event, two events. These prices were read from the public Apify Store API (`currentPricingInfo`) on 2026-09-23 16:25 UTC, and they are what a run of yours is charged:

| event | price | when it is charged |
|---|---|---|
| `page-checked` | US$ 0.05 | once per URL that was fetched and whose selector matched. A fetch that failed, timed out or was closed by `robots.txt` is not charged |
| `change-detected` | US$ 0.02 | on top of the page check, when the watched part differs from the previous run. A first check, and a page that still matches, pay nothing for this event |

A run over ten URLs where two changed is ten `page-checked` events plus two `change-detected`. Apify charges its own Actor start event and the platform usage of the run on top of this; that part is set by the platform, not by this Actor.

If a run reaches the pay-per-event limit you set, it stops there, keeps everything already stored, and writes the reason in the log and in `chargeLimitReached`. The URLs after that point are not in that run's dataset, and `urlsRequested` against `urlsChecked` in `SUMMARY` shows it.

## What this Actor does not do

- **It does not run JavaScript.** It reads the HTML the server sends, so a price drawn in the browser by a script is not seen.
- **It does not read anything that is not HTML.** A URL answering with JSON, a PDF or an image is refused, with the reason in `error`. This Actor watches web pages, not API endpoints.
- **It does not produce a word by word diff**, and it does not tell you what the change means.
- **It does not send e-mail, Slack or any other notification.** It writes a dataset, and you connect that to whatever you already use.
- **It does not run on a schedule by itself.** You set the schedule on the Apify platform.
- **It does not take screenshots** and it does not compare images.
- **It does not report a change on the first check** of a URL, because there is nothing to compare against.
- **It does not follow links or crawl a site.** It checks exactly the URLs you list.
- **It does not get past a login, a paywall or a captcha**, and it does not fill in forms.
- **It does not promise to catch every change.** A change beyond `excerptChars` shows up in `changed` but not in the excerpt text, and a selector that matches nothing is reported as an error, never as "no change".
- **It is not a marketplace scraper.** It is made for a handful of pages you already follow, one HTTP request each.

## Manners, `robots.txt` and your responsibility

- **`robots.txt` is read for each host before the page is fetched, and always respected.** A path closed to our user agent is reported as an error instead of being requested. `Crawl-delay` is obeyed, and when it is longer than your `requestDelaySeconds`, the longer value wins.
- **The Actor identifies itself** on every request as `Mozilla/5.0 (compatible; PageChangeMonitor/0.1; +https://apify.com/lotebo-lab/page-change-monitor)`, and `PageChangeMonitor` is the token to use in a `robots.txt` rule.
- **You are responsible for having the right to access every URL you give this Actor.** Before you add a page, check the terms of the site and its `robots.txt`, and check whether your own contract with that site allows automated access.
- **Keep personal data out of it.** The Actor stores an excerpt of the element you chose to watch, so a page holding someone's personal data would put that data in your dataset. Watch prices, clauses, versions and status text, not people. Set `excerptChars` to `0` to get the change flag with no stored page text.

## How this was checked

**The offline test suite.** Three files, run with the plain interpreter and no network, from the root of this repository on 2026-09-23:

| command | checks | result |
|---|---|---|
| `python tests/test_fingerprint.py` | 12 | all passed |
| `python tests/test_robots.py` | 7 | all passed |
| `python tests/test_schemas.py` | 7 | all passed |

What they cover: `test_fingerprint.py` checks the noise removal, the comparison rules and that the record key for a watch is stable and specific; `test_robots.py` drives the `robots.txt` gate, including that it is fetched once per host and that `Crawl-delay` is read; `test_schemas.py` compares the four files in `.actor/` and the three dataset views against what the code actually writes.

**On the Apify platform, against real pages.** These are runs on Apify, not local fixtures:

- **the comparison between two runs, proven end to end.** Run `jsmZxQCJVSwAdCBVk` recorded the baseline of `https://quotes.toscrape.com/random` with `changed: false` and `first_check: true`; run `GAl88gSWhX6dAxCUg`, 16 seconds later, returned `changed: true` and `first_check: false`, with a different `previous_excerpt`, `current_excerpt` and `sha256` fingerprint. The state does survive between runs and the comparison really happens;
- **state kept per watch.** Run `uz67qW3K2lsh8ax7X` returned, in the same output, one row with `first_check: false` and a `previous_excerpt` filled by an earlier run, and another row with `first_check: true` and no history;
- **the non-HTML refusal, measured and not assumed.** Run `RCwefVAXbQXfGxGkQ` against `https://httpbin.org/uuid` came back with `the response is not HTML (Content-Type: application/json)`, counted 1 error and wrote no row;
- **the input shapes a new buyer uses.** Run `cwQPEXHYOhXCWz34M` mixed a plain URL string, an object with a selector, and a selector that matches nothing; it finished `SUCCEEDED` and wrote 3 rows, with the expected warning for the empty selector.

**What has never been tested, stated plainly:**

- **No paid bill has ever come out of this Actor.** Charging has been exercised on the platform, but no invoice has ever been produced by it. A charge that fails or times out is a warning in the log, never the end of the run.
- **No site has ever refused us in `robots.txt`.** The gate is covered offline, with an injected fetcher; no real page we have run against was closed to this Actor's user agent.
- **No long watch.** The longest sequence we measured on one URL is a handful of consecutive runs inside a single day. This Actor has never watched a page for weeks.
- **Not every page in the wild.** The fingerprint rules were exercised against the documents in `tests/` and the public pages above. A page this Actor cannot read is reported with the reason in `error`, never silently as "no change", but we cannot claim the noise rules cover every framework.

## For developers

```
.actor/              actor.json, input, output and dataset schemas
src/main.py          the run: reads input, robots.txt gate, fetches, compares, charges events
src/fingerprint.py   the noise removal, the sha256 fingerprint and the excerpt
src/state.py         the last fingerprint per (URL, selector), in your own key-value store
tests/               the offline suite, three files plus the local end-to-end runner
```

The Actor is written in Python and was built with the help of AI. A selector that matches nothing is an error for that URL, never a silent "no change".

---

**Actor page on the Apify Store: https://apify.com/lotebo-lab/page-change-monitor**
