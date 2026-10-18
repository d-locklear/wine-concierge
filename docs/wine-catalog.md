# Wine catalog and Postgres rollout

The customer concierge now supports a catalog in `wine_concierge.wines`, separate
from the private assistant's memories, sessions, encryption keys and audit tables.
`wine_concierge.catalog_imports` records each committed import and its checksum.
Imports are explicit: use the CLI or enable the deployment bootstrap flag below.

## Source and review

`data/wine_catalog_2026.json` contains all 13 wines from the September 10 version
of `Locklear_Winery_Wine_Portfolio.pdf` (Library version 1). The August sales
portfolio contains the same 13 wines and two cider packages. Cider is outside
this initial wine import. Each record retains source filename, version and page.
Descriptions, style, ABV, serving and pairing suggestions are transcribed from
the portfolio. Autumn in a Bottle is 12% ABV; the other 12 wines are 9%.

Lumbee River Red's page mixes a fruit-wine heading with a red-table-wine TYPE.
Its berry-blend description is included; classification is omitted pending review.
Prices, stock and product purchase URLs are absent from the source. They remain
unknown, and the app must not treat a portfolio entry as proof of current stock.
Other wines in the legacy Sheet need reconciliation before completing the cutover.

The importer accepts only customer-facing fields and provenance; it rejects
wholesale costs, unknown columns, bad UPC check digits, duplicates and invalid
values. Names and slugs are stable identifiers. Reimporting updates supplied
fields while preserving omitted price, stock, link and active fields. Setting
an optional commercial field to null explicitly clears it. Imports never delete
existing wines missing from a file; use `active: false` to retire a record.

## Validate locally

Install `requirements.txt`, then run from the repository root:

```bash
python import_wine_catalog.py data/wine_catalog_2026.json
```

The default only validates the file. It needs no database or API credentials.

## Import production and switch the app

1. Merge this change and make the updated source available on the Render service.
   Keep `WINE_CATALOG_SOURCE=google_sheets` during staging so recommendations
   continue to use the existing source until the Postgres import is verified.
2. Set `WINE_CATALOG_BOOTSTRAP=1` before deploying the updated app. On worker
   startup, it imports the bundled portfolio using the service's existing
   `DATABASE_URL`. The schema and rows are verified atomically before commit;
   failure stops the new worker with a sanitized error. Concurrent workers
   serialize imports. A committed checksum and all 13 slugs cause subsequent
   starts to skip the import, preserving later edits. Disable the flag after
   confirming the import. Alternatively, in a Render shell run:

   ```bash
   python import_wine_catalog.py data/wine_catalog_2026.json --apply
   ```

   This creates only the `wine_concierge` schema/tables, imports all 13 records in
   one transaction, reads them back, and commits only if verification succeeds.
   A separate `WINE_DATABASE_URL` may be used; otherwise `DATABASE_URL` is reused.
   Never commit credentials to GitHub or paste them into conversation.
3. Compare the 13 source wines with `Locklear Wine Data`. Add any missing current
   wines with approved source details. Populate confirmed retail prices (integer
   cents), approved HTTPS winery/Vinoshipper product links and availability as needed.
4. Set `WINE_CATALOG_SOURCE=postgres`, `WINE_CATALOG_BOOTSTRAP=0`, and restart
   the service after verifying the database and reconciling the legacy Sheet.
5. Check `/health` for `ready`, `catalog_source: postgres`, and the expected count;
   check `/wines` for all active records. Check `/ask` with peach, barbecue,
   tropical wine, holiday wine and dry-wine requests. Verify the actual model
   response and product links. Missing prices and stock must stay unconfirmed.
   `/health` checks catalog connectivity and key presence, not OpenAI account billing.
6. Existing clients still receive the `response` string. They can also use the
   new `wines` array to display authoritative catalog details, prices and links.
   This change does not create or modify a Hostinger widget.

The app initializes database, Sheets and OpenAI clients on demand. Missing Sheets
credentials therefore cannot prevent the private assistant or Flask from starting.
Postgres reads use fully qualified table names and never read private assistant
tables. Database failure returns a generic 503, with no automatic source fallback.
Rollback: set `WINE_CATALOG_SOURCE=google_sheets`, retain the existing Sheets
credentials, and restart. The imported wine records can remain in Postgres.

The concierge retains the existing `gpt-4` default; `CONCIERGE_MODEL` can select
another supported Chat Completions model. JSON is requested in the prompt and
validated server-side, without adding an unsupported JSON-mode parameter to
the legacy model. Product IDs must match the catalog; price and link fields in
the returned `wines` array come from the database, never generated model fields.
Generated prose still needs live accuracy checks before publication.

## Tests

```bash
python -m pytest -q
```

For actual SQL coverage, set `TEST_DATABASE_URL` to a fresh disposable Postgres
database before running `tests/test_wine_catalog.py`. Those tests create and drop
the `wine_concierge` schema and a sentinel table. Never use production for tests.
Existing memory tests also use `TEST_DATABASE_URL` and isolate their tables in
temporary schemas.

## October 17 shopping update

The original September portfolio stays unchanged. `data/wine_shop_2026-10-17.json`
contains eight exact product-name matches plus the previously missing Raspberry
Rosé, verified against the public Vinoshipper storefront on October 17. Eight
matched bottles were $14 online; Raspberry Rosé was $15. Christmas in a Bottle
was marked sold out online. These are dated online observations, not winery
inventory or winery retail prices. No checkout or purchase was made.

Set `WINE_SHOP_BOOTSTRAP=1` for a deployment to import this reviewed snapshot,
then disable it after verifying nine updated records and fourteen total wines.
The import uses the existing transaction, readback and checksum protection. It
preserves omitted fields and does not change the assistant's private tables.
Scream in a Bottle and Pineapple Cider remain pending an approved current source.
Noblos, Fun in a Bottle and Summer in a Bottle are not silently mapped to
portfolio wines. Several older storefront vintages list different ABVs from the
September portfolio; the portfolio values remain and the UI directs customers
to the label on their bottle. Resolve vintage and ABV differences with the owner
before harmonizing those sources.

`online_price_cents`, `online_status`, and `online_checked_on` are public fields.
The importer requires a dated approved source URL for online commercial facts.
`availability` and `retail_price_cents` retain their prior meanings and stay
unknown until separately confirmed. All online prices are labeled by channel
and check date. Stock observations are never advertised as live inventory.

The root URL now serves the customer concierge. `/embed` uses the same page in
a compact layout. The legacy `/ask` response string and `wines` array remain
compatible. For Hostinger, replace the old custom-code widget with:

```html
<iframe src="https://wine-concierge.onrender.com/embed"
  title="Locklear Wine Concierge" loading="lazy"
  style="display:block;width:100%;height:950px;border:0;border-radius:18px;"
  allow="" referrerpolicy="strict-origin-when-cross-origin"></iframe>
```

Keep it below the existing homepage buttons. The iframe scrolls when results
exceed its height. It uses no microphone, local storage, tracking cookies, or
access to private assistant history. Recommendation text and catalog fields are
inserted as text, not HTML. Questions are sent only after the visitor submits.

### Live rollout and response-format correction

PR #10 deployed October 17 to the existing Render service. Nine shopping records
were verified field-for-field against Postgres, with fourteen total wines and
checksum `27e075995c674f9a9008fd06bbb473296e9656ab03c81d9356f71d36f0ad7654`.
`WINE_SHOP_BOOTSTRAP` was then disabled. The hosted screen and peach, raspberry,
tropical, sold-out-online and no-dry-match scenarios passed live checks.

A further test of the legacy Hostinger widget returned a 502 because the legacy
model's answer failed validation. The concierge now defaults to `gpt-4o-mini`
with strict JSON-schema output whose slug enum is built from the active catalog.
Server-side validation still rejects unknown, duplicate or excessive wine picks.
An explicit legacy `CONCIERGE_MODEL=gpt-4` override retains prompt-only JSON
compatibility; it does not receive an unsupported structured-output parameter.
The default supersedes the older gpt-4 rollout note above. Source: OpenAI's
Structured Outputs guide, verified October 17, 2026:
https://developers.openai.com/api/docs/guides/structured-outputs

GitHub is the project's durable home as requested by the owner; see `AGENTS.md`.
Hostinger still contains the old text-only widget. Replacing it with the `/embed`
iframe remains a separate website-builder step; the app deployment does not
change Hostinger's saved HTML.

### October 18 Charlie phone-test preview

A separate Render free service, `charlie-concierge-preview`, was created from
`feature/dad-original-portrait` in the existing winery workspace. It serves
`preview_app:app`; it has no database credentials, AI-provider key or owner
assistant routes. Validated guest prompts use the existing public `/ask` service,
and catalog reads use its public `/wines` endpoint. Production configuration,
main and Hostinger remain unchanged.

Preview URL: https://charlie-concierge-preview.onrender.com/
Initial deployment `dep-dbaf5be7bikc73ed92a0` reached `live` on October 18.
HTTP checks returned 200 for `/health`, `/wines` (14 wines), the original portrait
(SHA-256 `977be9e3b0d53b8a42d46f149ecff7e24e5808948a4fe1f1dd7c2e012d7c5fb0`),
and a peach recommendation with Peach, Love in a Bottle and Strawberry. Browser
inspection confirmed Charlie wording, preview disclosure and microphone control.
Screenshot capture timed out, so no screenshot-based visual approval is claimed.
The owner had already approved the earlier portrait design preview.

The focused suite passed 28 Python and 7 JavaScript checks. Physical iPhone
microphone capture and permission handling remain pending owner testing. Replies
remain text; no recognizable voice has been created. Free service cold starts
can take about a minute after idle. The workspace display name is unchanged;
Locklear Winery was recommended as a clearer name.
