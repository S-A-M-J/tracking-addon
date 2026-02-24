import datetime as dt
import json
import logging
import os
import ssl
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo


OPTIONS_PATH = "/data/options.json"
SUPERVISOR_URL = "http://supervisor"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("history_bulk_exporter")

MAX_UPLOAD_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 1


def load_options() -> dict:
    with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    required = ["upload_hour", "destination_url", "destination_key", "history_days", "verify_tls"]
    for key in required:
        if key not in data:
            raise ValueError(f"Missing required option: {key}")

    # Enforce upload_hour is between 0 and 23
    upload_hour = data.get("upload_hour")
    if not isinstance(upload_hour, int) or not (0 <= upload_hour <= 23):
        raise ValueError("upload_hour must be an integer between 0 and 23")

    return data


def supervisor_headers() -> dict:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("SUPERVISOR_TOKEN is not available")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def get_homeassistant_timezone(headers: dict) -> ZoneInfo:
    url = f"{SUPERVISOR_URL}/core/api/config"
    payload = http_get_json(url, headers=headers, timeout=30)
    timezone_name = payload.get("time_zone", "UTC")
    logger.info("Using Home Assistant timezone: %s", timezone_name)
    return ZoneInfo(timezone_name)


def next_run_at(hour: int, tz: ZoneInfo) -> dt.datetime:
    now = dt.datetime.now(tz)
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += dt.timedelta(days=1)
    return candidate


def fetch_history(headers: dict, start: dt.datetime, end: dt.datetime):
    start_iso = start.isoformat()
    end_iso = end.isoformat()

    url = f"{SUPERVISOR_URL}/core/api/history/period/{start_iso}"
    params = {
        "end_time": end_iso,
        "no_attributes": False,
    }

    logger.info("Fetching history window: %s -> %s", start_iso, end_iso)
    query = urllib.parse.urlencode(params)
    request_url = f"{url}?{query}"
    return http_get_json(request_url, headers=headers, timeout=300)


def http_get_json(url: str, headers: dict, timeout: int):
    request = urllib.request.Request(url=url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return json.loads(body)


def upload_payload(destination_url: str, destination_key: str, verify_tls: bool, payload: dict):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {destination_key}",
    }

    data = json.dumps(payload).encode("utf-8")
    payload_size = len(data)
    logger.info("Uploading payload to %s (%d bytes)", destination_url, payload_size)

    request = urllib.request.Request(
        url=destination_url,
        headers=headers,
        data=data,
        method="POST",
    )

    ssl_context = None
    if not verify_tls:
        ssl_context = ssl._create_unverified_context()

    last_error = None
    backoff = INITIAL_BACKOFF_SECONDS

    for attempt in range(1, MAX_UPLOAD_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=300, context=ssl_context) as response:
                logger.info("Upload completed with status %s", response.status)
                return
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            last_error = exc
        except Exception as exc:
            # Retry unknown network/runtime errors as well.
            last_error = exc

        if attempt >= MAX_UPLOAD_RETRIES:
            break

        logger.warning(
            "Upload attempt %d/%d failed: %s. Retrying in %ds",
            attempt,
            MAX_UPLOAD_RETRIES,
            last_error,
            backoff,
        )
        time.sleep(backoff)
        backoff *= 2

    raise RuntimeError(
        f"Upload failed after {MAX_UPLOAD_RETRIES} attempts"
    ) from last_error


def run_once(options: dict, headers: dict, tz: ZoneInfo):
    end = dt.datetime.now(tz)
    start = end - dt.timedelta(days=int(options["history_days"]))

    history = fetch_history(headers, start, end)
    payload = {
        "meta": {
            "generated_at": end.isoformat(),
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "history_days": int(options["history_days"]),
            "source": "home_assistant_history_bulk_exporter",
        },
        "history": history,
    }

    upload_payload(
        destination_url=options["destination_url"],
        destination_key=options["destination_key"],
        verify_tls=bool(options["verify_tls"]),
        payload=payload,
    )


import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/manual_export":
            self.handle_manual_export()
        elif self.path == "/test_endpoint":
            self.handle_test_endpoint()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def handle_manual_export(self):
        try:
            options = load_options()
            headers = supervisor_headers()
            tz = get_homeassistant_timezone(headers)
            run_once(options, headers, tz)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Manual export triggered successfully.")
        except Exception as exc:
            logger.exception("Manual export failed: %s", exc)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Manual export failed: {exc}".encode())

    def handle_test_endpoint(self):
        try:
            options = load_options()
            # Only test the endpoint, don't send real data
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {options['destination_key']}"
            }
            data = json.dumps({"test": True}).encode("utf-8")
            request = urllib.request.Request(
                url=options["destination_url"],
                headers=headers,
                data=data,
                method="POST",
            )
            ssl_context = None
            if not bool(options["verify_tls"]):
                ssl_context = ssl._create_unverified_context()
            with urllib.request.urlopen(request, timeout=10, context=ssl_context) as response:
                status = response.status
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"Test endpoint responded with status {status}".encode())
        except Exception as exc:
            logger.exception("Test endpoint failed: %s", exc)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Test endpoint failed: {exc}".encode())

def start_http_server():
    server = HTTPServer(("0.0.0.0", 8080), SimpleHandler)
    logger.info("HTTP server started on port 8080 for manual export and test endpoint.")
    server.serve_forever()

def main():
    logger.info("Starting History Bulk Exporter add-on")

    # Start HTTP server in a separate thread
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    options = load_options()
    headers = supervisor_headers()
    tz = get_homeassistant_timezone(headers)

    while True:
        try:
            schedule_time = next_run_at(int(options["upload_hour"]), tz)
            sleep_seconds = max(1, int((schedule_time - dt.datetime.now(tz)).total_seconds()))
            logger.info("Next export scheduled at %s", schedule_time.isoformat())
            time.sleep(sleep_seconds)

            options = load_options()
            run_once(options, headers, tz)
        except Exception as exc:
            logger.exception("Export cycle failed: %s", exc)
            time.sleep(60)


if __name__ == "__main__":
    main()
