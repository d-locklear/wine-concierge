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
