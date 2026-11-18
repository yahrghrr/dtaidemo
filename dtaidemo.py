#!/usr/bin/env python3
"""
dtaidemo - a simulated "3rd-party" telemetry source for Dynatrace.

Sends a few metrics to the Dynatrace Metrics API v2 every INTERVAL seconds.
Most of the time the values look normal. Every now and then it goes into a
"spike" for a few minutes so you can build and test alerts in Dynatrace.

No extra packages needed: only the Python 3 standard library.

Configuration comes from environment variables (the installer writes them to
/etc/dtaidemo/config.env):

  DT_URL              e.g. https://abc12345.live.dynatrace.com   (required)
  DT_API_TOKEN        token with scope metrics.ingest             (required)
  INTERVAL_SECONDS    how often to send data            (default 30)
  SPIKE_EVERY_MIN     min minutes between spikes        (default 15)
  SPIKE_EVERY_MAX     max minutes between spikes        (default 30)
  SPIKE_DURATION_MIN  how long a spike lasts, minutes   (default 5)
  SOURCE_NAME         value of the "source" dimension   (default dtaidemo)
  FORCE_SPIKE_FILE    if this file exists, spike now    (default /var/lib/dtaidemo/force_spike)
  SERVICE_ID          optional, e.g. SERVICE-1A2B3C4D5E6F7A8B. Ties the data natively to that
                      Dynatrace service by adding dt.entity.service and
                      dt.smartscape.service (OpenPipeline can't add these)
  EXTRA_DIMENSIONS    optional, e.g. dt.entity.custom_device=CUSTOM_DEVICE-ABC,team=demo
  HEARTBEAT_LOGS      "true" = also send one log line per cycle to the Logs API
                      (token then also needs logs.ingest)  (default false)
  DRY_RUN             "true" = print lines, don't send   (default false)
"""

import os
import random
import signal
import socket
import json
import ssl
import sys
import time
import urllib.error
import urllib.request

METRIC_PREFIX = "dtaidemo"


def env(name, default=None):
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else value


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def normalise_url(url):
    """Accept the URL people usually copy from the browser and turn it into the API URL."""
    url = url.rstrip("/")
    # The new platform UI lives on *.apps.dynatrace.com, the classic API on *.live.dynatrace.com
    url = url.replace(".apps.dynatrace.com", ".live.dynatrace.com")
    if "/ui" in url:
        url = url.split("/ui")[0]
    if not url.startswith("http"):
        url = "https://" + url
    return url


class Simulator:
    def __init__(self):
        self.every_min = float(env("SPIKE_EVERY_MIN", "15"))
        self.every_max = float(env("SPIKE_EVERY_MAX", "30"))
        self.duration = float(env("SPIKE_DURATION_MIN", "5"))
        self.force_file = env("FORCE_SPIKE_FILE", "/var/lib/dtaidemo/force_spike")
        self.spike_until = 0.0
        self.next_spike = time.time() + self._random_gap()

    def _random_gap(self):
        return random.uniform(self.every_min, self.every_max) * 60

    def in_spike(self):
        now = time.time()
        # Manual trigger: `sudo dtaidemo-spike` creates this file
        if self.force_file and os.path.exists(self.force_file):
            try:
                os.remove(self.force_file)
            except OSError:
                pass
            log(f"Manual spike requested - spiking for {self.duration:g} min")
            self.spike_until = now + self.duration * 60
            self.next_spike = self.spike_until + self._random_gap()
        if now >= self.next_spike and now >= self.spike_until:
            log(f"Starting scheduled spike for {self.duration:g} min")
            self.spike_until = now + self.duration * 60
            self.next_spike = self.spike_until + self._random_gap()
        return now < self.spike_until

    def sample(self, spiking):
        if spiking:
            return {
                "queue_depth": random.uniform(250, 400),
                "response_time_ms": random.uniform(1800, 3500),
                "error_rate_pct": random.uniform(15, 35),
                "throughput_rpm": random.uniform(80, 150),
            }
        return {
            "queue_depth": random.gauss(25, 5),
            "response_time_ms": random.gauss(120, 20),
            "error_rate_pct": abs(random.gauss(0.5, 0.3)),
            "throughput_rpm": random.gauss(600, 50),
        }


def build_lines(values, dims):
    dim_str = ",".join(f'{k}="{v}"' for k, v in dims.items())
    ts = int(time.time() * 1000)
    return "\n".join(
        f"{METRIC_PREFIX}.{name},{dim_str} gauge,{max(0.0, v):.2f} {ts}" for name, v in values.items()
    )


def build_log(values, dims, spiking):
    record = {
        "content": f"dtaidemo heartbeat ({'SPIKE' if spiking else 'normal'})",
        "log.source": "dtaidemo",
        "loglevel": "WARN" if spiking else "INFO",
    }
    record.update(dims)
    record.update({f"{METRIC_PREFIX}.{k}": round(max(0.0, v), 2) for k, v in values.items()})
    return json.dumps([record])


def send(url, token, payload, path="/api/v2/metrics/ingest", ctype="text/plain; charset=utf-8"):
    req = urllib.request.Request(
        url + path,
        data=payload.encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Api-Token {token}",
            "Content-Type": ctype,
        },
    )
    with urllib.request.urlopen(req, timeout=15, context=ssl.create_default_context()) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def main():
    dry_run = env("DRY_RUN", "false").lower() == "true"
    url = env("DT_URL")
    token = env("DT_API_TOKEN")
    if not dry_run and (not url or not token):
        log("ERROR: DT_URL and DT_API_TOKEN must be set (see /etc/dtaidemo/config.env)")
        sys.exit(1)
    url = normalise_url(url) if url else ""
    interval = float(env("INTERVAL_SECONDS", "30"))
    dims = {"source": env("SOURCE_NAME", "dtaidemo"), "host": socket.gethostname()}
    service_id = (env("SERVICE_ID", "") or "").strip('"')
    if service_id:
        if not service_id.startswith("SERVICE-"):
            log(f"WARNING: SERVICE_ID '{service_id}' doesn't look like a service ID (SERVICE-...); using it anyway")
        dims["dt.entity.service"] = service_id
        dims["dt.smartscape.service"] = service_id
    for pair in (env("EXTRA_DIMENSIONS", "") or "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            dims[k.strip()] = v.strip().strip('"')

    heartbeat_logs = env("HEARTBEAT_LOGS", "false").lower() == "true"
    sim = Simulator()
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    log(f"dtaidemo started -> {url or '(dry run)'} every {interval:g}s, dims={dims}")
    if service_id:
        log(f"Data is tied to service {service_id}")
    else:
        log("Not tied to a service yet (optional): run  sudo dtaidemo-set-service SERVICE-...")
    log(f"First automatic spike in ~{(sim.next_spike - time.time()) / 60:.0f} min")

    while running:
        spiking = sim.in_spike()
        values = sim.sample(spiking)
        payload = build_lines(values, dims)
        state = "SPIKE " if spiking else "normal"
        if dry_run:
            log(f"[{state}] would send:\n{payload}")
            if heartbeat_logs:
                log(f"[{state}] would send log: {build_log(values, dims, spiking)}")
        else:
            if heartbeat_logs:
                try:
                    status, _ = send(url, token, build_log(values, dims, spiking),
                                     "/api/v2/logs/ingest", "application/json; charset=utf-8")
                    log(f"[{state}] sent heartbeat log, HTTP {status}")
                except urllib.error.HTTPError as e:
                    log(f"[{state}] log rejected: HTTP {e.code} {e.read().decode('utf-8', 'replace')}")
                    if e.code in (401, 403):
                        log("Hint: HEARTBEAT_LOGS needs the 'logs.ingest' token scope")
                except Exception as e:
                    log(f"[{state}] log send failed: {e}")
            try:
                status, body = send(url, token, payload)
                log(f"[{state}] sent 4 metrics, HTTP {status} {body.strip()}")
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                log(f"[{state}] Dynatrace rejected the data: HTTP {e.code} {detail}")
                if e.code in (401, 403):
                    log("Hint: check DT_API_TOKEN and that it has the 'metrics.ingest' scope")
            except Exception as e:  # network errors etc. - keep going
                log(f"[{state}] send failed: {e}")
        # sleep in small steps so stop/force-spike react quickly
        end = time.time() + interval
        while running and time.time() < end:
            time.sleep(1)

    log("dtaidemo stopped")


if __name__ == "__main__":
    main()
