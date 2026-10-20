# Charlie avatar deployment — October 20, 2026

PR #13 merged as `07c60e17bc3dddb9a8bcf619ca5a6112566af5aa`. Render deploy `dep-dbbqm78473hc738gmjg0` reached terminal `live` at 17:57 UTC on the existing wine-concierge service.

The live standalone and `/embed` pages now use the existing original portrait from `feature/dad-original-portrait`, with “A warm welcome from Charlie” and an AI concierge label. The portrait bytes are unchanged. The Hostinger iframe URL requires no change.

Validation:
- 14 existing customer/catalog tests passed.
- Local Flask route and original-asset checks passed.
- Live `/health` is ready on Postgres; `/wines` still returns 14 wines.
- Live portrait hash matches the original asset.
- Live grilled-pork recommendation returned Carlos Sweet, Lumbee River Red, and Blackberry.
- Browser inspection confirmed the Charlie portrait is visible inside the published locklearwinery.com iframe.
- Local desktop/mobile screenshot automation was unavailable because the browser executable was missing and its download failed. Actual phone layout remains unverified.

This change adds the portrait and welcome only; the microphone/voice work on the preview branch was not merged.
