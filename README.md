# History Bulk Exporter (Home Assistant Add-on)

## Purpose

This add-on exports Home Assistant history data once per day and sends it to a remote HTTP endpoint.

## What it does

- Pulls history data from Home Assistant using the Supervisor/Core API.
- Runs once daily at a configurable hour.
- Sends the exported data to a configurable destination URL.
- Includes a configurable API key as `Authorization: Bearer <key>`.
- Retries failed uploads up to 5 times with exponential backoff.

## Configuration options

- `upload_hour` (0-23): Hour of day to run in Home Assistant local time.
- `destination_url`: Remote endpoint to receive history data.
- `destination_key`: Secret key sent as `X-Tracking-Key`.
- `history_days` (1-30): Number of trailing days to include per export.
- `verify_tls`: Whether to verify HTTPS certificates when posting.

Example:

```yaml
upload_hour: 2
destination_url: https://example.com/ingest
destination_key: your-secret-key
history_days: 1
verify_tls: true
```

## Installation (local add-on)

1. Copy this folder into Home Assistant's local add-ons directory (for example under `/addons/local/history_bulk_exporter`).
2. In Home Assistant, go to **Settings → Add-ons → Add-on Store**.
3. Refresh/reload local add-ons.
4. Open **History Bulk Exporter**, set options, then start the add-on.

## Payload format

The add-on posts JSON to `destination_url`:

- `meta`: generation and window metadata.
- `history`: raw Home Assistant history response payload.

Authentication header used for destination API:

- `Authorization: Bearer <destination_key>`

## Notes

- First run occurs at the next configured `upload_hour`.
- If a run fails, the add-on logs the error and retries in the next cycle.
