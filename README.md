# Website Change Monitor: Track Page Updates by CSS Selector

Run it on Apify Store: https://apify.com/lotebo-lab/page-change-monitor

A supplier changed a price, a platform edited a clause, a vendor shipped a release, and none of them told you: the page just says something different than it did last week.

This Actor takes the URLs you already check by hand, each with an optional **CSS selector**, fetches them on every run, compares the watched part with what it saw on the previous run, and returns one row per URL saying whether that part changed, with the old text and the new text side by side.

The selector is what makes it usable: you watch the price block, the version number or the clause, and the menus, banners and cookie notices do not wake you up.

## Run it on a schedule (this is the point)

This Actor answers "did it change since the last check?", and a single run cannot answer that. **The first run on a URL only records the baseline:** every row comes back with `first_check: true` and `changed: false`, no matter how long the page has been sitting there, because there is nothing to compare it against yet. From the second run on, each run compares the page with what the run before stored, and that is the run that tells you something.

So set it to run again by itself. On the Apify platform you schedule the Actor directly, with no task to create first: in Schedules, "Click on the Add dropdown and select whether you want to schedule an Actor or task", pick this Actor, and write the interval as a cron expression with six positions. There is one prerequisite, and it is the baseline again: "To schedule an Actor, you need to have run it at least once before". So press Start once, let that run be the baseline, then schedule it. The platform's floor is that "The minimum interval between runs is 10 seconds"; how often you actually check is your call and your site's. The steps are in the Apify documentation: https://docs.apify.com/platform/schedules

Schedules are not a paid extra. The Apify limits page lists "Maximum number of schedules per user: 100", and the number is the same in every plan column, including Free: https://docs.apify.com/platform/limits

Two practical notes from the Apify schedules documentation (https://docs.apify.com/platform/schedules). Apify asks you to run an Actor once before you can schedule it: "To schedule an Actor, you need to have run it at least once before." That fits this Actor anyway, because that first run is the one that records your baseline. And the shortest interval the platform accepts is 10 seconds, so the frequency is your call, not a limit of this Actor. Daily is the setting most people want: it keeps the bill small and still catches the change on the day it happens.

One thing to know about the memory. The baseline is not stored inside the Actor: it is a named key-value store record in **your own account**, keyed by the pair (URL, selector). It survives between runs and it is yours to read or delete. If that store is deleted, or if you change the URL or the selector, the next run is a first run again for those rows: baseline recorded, `changed: false`.

## Who runs it, and when

People who depend on a handful of pages that change without notice:

- **procurement and finance**, on a supplier price page or plan table where a number moves quietly;
- **legal and compliance**, on a terms of service or privacy policy of a platform the business depends on;
- **engineering and operations**, on a changelog, release or status page that publishes no feed;
- **anyone tracking a public list**: a tender, grant or vacancy page that is updated in place rather than appended to.

The moment is usually: someone got burned once by a change nobody noticed, and now a person is opening the same five pages every Monday. You schedule this Actor on the Apify platform instead, and read the rows where `changed` is `true`.

## What comes out, field by field

One dataset row per URL checked. Every row has exactly these ten fields, and nothing else; the same names are declared in `.actor/dataset_schema.json` and checked by `tests/test_schemas.py`.

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

Every run also writes a `SUMMARY` record in the key-value store with `urlsRequested`, `urlsChecked`, `changesDetected`, `firstChecks`, `errors`, `chargedEvents`, `chargeLimitReached` and `chargeFailures`.

### What counts as a change

The fingerprint is taken from the HTML of the watched part after the noise is removed, so a redeploy does not look like an edit:

- HTML comments, `<script>`, `<style>`, `<noscript>` and `<template>` are dropped;
- whitespace and line breaks are collapsed, so reindenting a template is not a change;
- volatile attributes go away: `nonce`, CSRF tokens, request, trace and session ids, render timestamps, `data-reactid`, `integrity`;
- the random-looking numeric or hex suffix frameworks add to `id` and `for` is removed, and `class` tokens are sorted.

What stays inside the fingerprint, on purpose: the tag structure, the tag names, every other attribute and the text. So a changed link target counts as a change, not only visible text. A typo fix counts as a change too: this is not a semantic diff.

### Real output rows

Lines 23, 24 and 25 of `logs/corrida-local-2026-09-20-run2.log` in this repository: an end-to-end run of `src/main.py`, the second run of a pair, with the pages served from `tests/fixtures/run2`. Between the two runs the starter price changed from EUR 49 to EUR 59, the terms page did not change, and a third URL was left pointing at a page that answers 404 on purpose.

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

The `SUMMARY` record of the same run, lines 27 to 36:

```json
{"urlsRequested": 3, "urlsChecked": 2, "changesDetected": 1, "firstChecks": 0, "errors": 1, "chargedEvents": {}, "chargeLimitReached": false, "chargeFailures": 0}
```

The first run of the same pair, in `logs/corrida-local-2026-09-20-run1.log`, has `first_check: true` and `changed: false` on every row. That run is the baseline.

## Input

The example below is the input this Actor is prefilled with, so you can press Start and read a real result before pointing it at your own pages. It watches one block of a public page: the first run is the baseline, and a second run tells you whether that block changed in between.

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

| field | type | required | default | range |
|---|---|---|---|---|
| `urls` | array of `{ url, selector }` objects | yes | — | a plain URL string is also accepted and means the whole page body |
| `requestDelaySeconds` | integer | no | 2 | 0 to 60 |
| `requestTimeoutSeconds` | integer | no | 20 | 3 to 120 |
| `excerptChars` | integer | no | 200 | 0 to 5000; `0` stores no page text at all |

Notes on the input, as the code handles it:

- the `selector` is standard CSS, handled by BeautifulSoup. When it matches several elements, all of them are watched together, in document order;
- without a selector the whole `<body>` is watched, which is noisier: any edit anywhere on the page counts;
- the pair **(URL, selector)** is the identity of a watch. The same page watched with two selectors keeps two independent histories, and changing either one starts a new history;
- `requestDelaySeconds` is the wait before each request after the first one. If `robots.txt` asks for a longer `Crawl-delay`, the longer value wins.

The memory between runs is a named key-value store record per (URL, selector) pair, in your own account, holding the last fingerprint, the excerpt and the time of the check.

## What this Actor does not do

- **It does not run JavaScript.** It reads the HTML the server sends, so a price drawn in the browser by a script is not seen.
- **It does not produce a word by word diff**, and it does not tell you what the change means.
- **It does not send e-mail, Slack or any other notification.** It writes a dataset, and you connect that to whatever you already use.
- **It does not run on a schedule by itself.** You set the schedule on the Apify platform.
- **It does not take screenshots** and it does not compare images.
- **It does not report a change on the first check** of a URL, because there is nothing to compare against.
- **It does not follow links or crawl a site.** It checks exactly the URLs you list.
- **It does not get past a login, a paywall or a captcha**, and it does not fill in forms.
- **It does not promise to catch every change.** A change beyond `excerptChars` shows up in `changed` but not in the excerpt text, and a selector that matches nothing is reported as an error, never as "no change".
- **It is not a marketplace scraper.** It is made for a handful of pages you already follow, one HTTP request each.

## Limits

This Actor reads HTML pages. A URL that answers with something else, such as JSON, a PDF or an image, is refused and its row carries the reason in `error`, for example `the response is not HTML (Content-Type: application/json)`. A URL refused this way is not charged: only a page that was read and whose selector matched produces a `page-checked` event.

## Manners, `robots.txt` and your responsibility

- **`robots.txt` is read for each host before the page is fetched, and always respected.** A path closed to our user agent is reported as an error instead of being requested. `Crawl-delay` is obeyed.
- **The Actor identifies itself** on every request as `Mozilla/5.0 (compatible; PageChangeMonitor/0.1; +https://apify.com/lotebo-lab/page-change-monitor)`, and `PageChangeMonitor` is the token to use in a `robots.txt` rule.
- **You are responsible for having the right to access every URL you give this Actor.** Before you add a page, check the terms of the site and its `robots.txt`, and check whether your own contract with that site allows automated access.
- **Keep personal data out of it.** The Actor stores an excerpt of the element you chose to watch, so a page holding someone's personal data would put that data in your dataset. Watch prices, clauses, versions and status text, not people. Set `excerptChars` to `0` to get the change flag with no stored page text.

## Price

Pay per event, two events, exactly as declared in `.actor/actor.json`:

| event | price | when it is charged |
|---|---|---|
| `page-checked` | US$ 0.05 | once per URL that was fetched and whose selector matched. A fetch that failed, timed out or was closed by `robots.txt` is not charged |
| `change-detected` | US$ 0.02 | on top of the page check, when the watched part differs from the previous run |

A run over ten URLs where two changed is ten `page-checked` events plus two `change-detected`. Apify charges its own Actor start event and the platform usage of the run on top of this; those are not set by this Actor.

If a run reaches your pay-per-event limit, it stops there, keeps everything already stored, and writes the reason in the log and in `chargeLimitReached`. The URLs after that point are not in that run's dataset, and `urlsRequested` against `urlsChecked` in `SUMMARY` shows it.

## About this Actor

The code, the tests and the run logs quoted here are in this repository. A selector that matches nothing is an error for that URL, never a silent "no change". The Actor is written in Python and was built with the help of AI.

## Example tasks

Each page below is a published example task of this Actor. It shows the input used and the fields the run returns. The same page is served as Markdown by adding `.md` to the URL.

- [See exactly what changed on a competitor pricing page](https://apify.com/lotebo-lab/page-change-monitor/examples/see-exactly-what-changed-on-a-competitor-pricing-page): point the Actor at a pricing page and a CSS selector and it returns the text before and after, so a number that moved is easy to spot.
- [Check if a supplier terms page changed since last run](https://apify.com/lotebo-lab/page-change-monitor/examples/check-if-a-supplier-terms-page-changed-since-last-run): watches the terms and policy pages of the vendors you use and returns one row per page saying whether the text changed.
- [Which supplier product pages failed the last check?](https://apify.com/lotebo-lab/page-change-monitor/examples/which-supplier-product-pages-failed-the-last-check): runs a long list of pages on a set delay and returns the ones that timed out, answered an error or lost the selector you asked for.
- [How do I get told when one part of a web page changes?](https://apify.com/lotebo-lab/page-change-monitor/examples/watch-one-section-of-a-page-for-changes): give the URL and a CSS selector for the block you care about, and every run says whether that block changed since the run before, with the old text next to the new one.
- [Know when a vendor publishes new release notes](https://apify.com/lotebo-lab/page-change-monitor/examples/know-when-a-vendor-publishes-new-release-notes): fetches each download or release page and shows the text before and after for the ones that moved.
- [Check a list of pages in one run and see which ones changed](https://apify.com/lotebo-lab/page-change-monitor/examples/check-many-pages-in-one-run-and-see-which-changed): one table with which pages changed, which did not and which could not be read, with the status and the error side by side.
- [Watch only one section of a page, not the whole page](https://apify.com/lotebo-lab/page-change-monitor/examples/watch-only-one-section-of-a-page-not-the-whole-page): only the part matched by your CSS selector is fingerprinted, so a rotating banner never counts as a change.
