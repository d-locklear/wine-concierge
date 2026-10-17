# Working on Wine Concierge

The owner requested on October 17, 2026 that ongoing project work be stored in GitHub. Treat this repository as the durable home for application source, reviewed public catalog data, tests, implementation notes, deployment records and open decisions. Commit completed changes to a project branch and keep reviewable pull requests; do not leave the only copy in a chat or temporary workspace.

Read `docs/wine-catalog.md` before changing catalog behavior or deployment imports. Record material changes and verified deployment outcomes there. Keep unconfirmed facts explicit and distinguish online prices and stock observations from winery prices and inventory. Do not map similarly named products without evidence.

Never commit API keys, credentials, connection strings, customer records, or private assistant memories. Keep secrets in Render's environment configuration. This repository is public; project notes must contain only suitable public technical information.

Preserve `/ask` response compatibility with the existing Hostinger widget. Use `/embed` for the newer customer interface. Keep wine data separate from the private assistant tables.

Run the relevant tests before merging; report skipped integration tests and unresolved failures. Never point disposable database tests at production. After an authorized deployment, verify its terminal live state, `/health`, the catalog readback and customer recommendations. A successful build or merge alone is not a verified deployment.

The code, catalog and embed instructions can be stored here. Changes made directly in Hostinger still require access to that builder; do not claim a widget has been replaced unless the published page has been checked.
