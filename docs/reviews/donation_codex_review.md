# Codex Review: Donation Feature

## Findings

1. **Uploaded documents are never persisted to storage**
   - In `create_donation`, each uploaded file is validated and a `DonationDoc` record is created, but the file content is never saved to disk or another storage backend. Only the filename metadata is stored, meaning downloads will fail because the referenced files do not exist. Add a file save step (e.g., `uploaded_file.save(path)` or cloud upload) after generating the unique filename so the stored metadata points to an actual asset.
   - Suggested test: create a donation with an attachment and verify the file is written to the configured media location, then downloaded via the UI without a 404.

2. **Total donation value is not reconciled with item costs**
   - The handler computes `total_value` from the donation items but ultimately writes `tot_item_cost_value` from the form directly to the donation header. No check ensures the submitted header total matches the calculated item total, so inconsistent data can be persisted. Either replace the header value with the computed `total_value` or validate that they match before commit.
   - Suggested test: submit a donation where header total differs from the sum of item totals and confirm the request is rejected with a validation error rather than persisting inconsistent data.

## Recommendations

- Add unit tests around `create_donation` to cover both attachment persistence and header/item total reconciliation, so regressions are caught automatically.
- Ensure the document storage path (local or cloud) is configurable through environment settings and validated during startup to avoid silent failures when the path is missing.
