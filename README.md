# dtaidemo: simulated 3rd-party telemetry for Dynatrace

A small program that runs on a Linux VM and sends metrics to Dynatrace **every 30 seconds**.
Most of the time the values are normal. **Every 15–30 minutes it spikes for 5 minutes**, which gives you something to alert on.
You can also trigger a spike yourself at any time.

| Metric | Normal | During a spike |
|---|---|---|
| `dtaidemo.queue_depth` | ~25 | 250–400 |
| `dtaidemo.response_time_ms` | ~120 | 1,800–3,500 |
| `dtaidemo.error_rate_pct` | ~0.5 | 15–35 |
| `dtaidemo.throughput_rpm` | ~600 | 80–150 |

Every data point has the dimensions `source="dtaidemo"` and `host="<vm name>"`.

---

## Part A: Deploy it on your Azure VM

### A1. Create a Dynatrace API token (2 minutes)
1. In Dynatrace, open the **Access tokens** app (search "Access tokens" with Ctrl+K / Cmd+K).
2. Click **Generate new token**. Name it `dtaidemo`.
3. Add the scope **Ingest metrics** (`metrics.ingest`).
   - Optional: also add **Write entities** (`entities.write`) if you want the custom device in Part C.
4. Click **Generate** and **copy the token** (it starts with `dt0c01.`). You will only see it once.

You also need your **environment URL**. It's the address in your browser, e.g. `https://abc12345.apps.dynatrace.com`.
You can paste it as-is; the program converts it to the API address (`https://abc12345.live.dynatrace.com`) automatically.

### A2. Connect to the VM
In the **Azure portal**: open your VM, then **Connect**, and pick one of:
- **SSH using Azure CLI / Cloud Shell**, or
- **Bastion**, or
- the SSH command shown there, run from a terminal on your PC (e.g. `ssh azureuser@<public-ip>`).

You should now see a Linux prompt like `azureuser@myvm:~$`.

### A3. Install (copy & paste these 3 lines)
```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/yahrghrr/dtaidemo.git
cd dtaidemo && sudo ./install.sh
```
(On RHEL/Alma/Rocky VMs use `sudo dnf install -y git` in the first line.)

The installer asks for the **URL** and the **token** (the token is hidden while you paste it; that's expected).
It then starts the service and shows the first few log lines. **`HTTP 202` means it's working.**

It runs in the background and **starts automatically after a reboot**. No outbound firewall changes are needed
on a standard Azure VM (outbound HTTPS is allowed by default).

### A4. Everyday commands
| What | Command |
|---|---|
| Watch it live (Ctrl+C to exit) | `sudo journalctl -u dtaidemo -f` |
| **Force a spike now** (lasts 5 min) | `sudo dtaidemo-spike` |
| Stop / start | `sudo systemctl stop dtaidemo` / `sudo systemctl start dtaidemo` |
| Change settings (interval, spike timing, …) | `sudo nano /etc/dtaidemo/config.env` then `sudo systemctl restart dtaidemo` |
| Remove everything | `cd ~/dtaidemo && sudo ./uninstall.sh` |

### A5. Check the data arrived in Dynatrace
Open a **Notebook**, add a DQL section and run:
```
timeseries v = avg(dtaidemo.queue_depth), by:{host, source}
```
You should see a line within 1–2 minutes.

**Troubleshooting:** `HTTP 401/403` means the token is wrong or missing the `metrics.ingest` scope.
To fix it, run `sudo rm /etc/dtaidemo/config.env && sudo ./install.sh` and enter the details again.

---

## Part B: Attach the service entity ID in OpenPipeline

Goal: every `dtaidemo.*` data point gets the dimension `dt.entity.service = SERVICE-XXXX`, so Davis can raise problems on that service.

### B1. Find your service's entity ID
Either open the service in Dynatrace and copy the `SERVICE-…` part of the browser URL, or run in a Notebook:
```
fetch dt.entity.service
| filter contains(entity.name, "my-service")
| fields id, entity.name
```

### B2. Create the pipeline
1. Open the **OpenPipeline** app (Ctrl+K, then "OpenPipeline"). On older UIs it's under **Settings → Process and contextualize → OpenPipeline**.
2. Choose **Metrics**, open the **Pipelines** tab, and click **+ Pipeline**. Name it `dtaidemo`.
3. In the **Processing** stage click **+ Processor**, then **DQL**:
   - **Name:** `Attach service entity`
   - **Matching condition:** `source == "dtaidemo"`
   - **DQL processor definition:**
     ```
     fieldsAdd dt.entity.service = "SERVICE-1A2B3C4D5E6F7A8B"
     ```
     (replace with your real ID from B1)
   - Optional, if you do Part C, add the custom device too:
     ```
     fieldsAdd dt.entity.service = "SERVICE-1A2B3C4D5E6F7A8B",
               dt.entity.custom_device = "CUSTOM_DEVICE-ABCDEF0123456789"
     ```
4. **Save** the pipeline.

### B3. Route the data into the pipeline
1. Still in **Metrics**, open the **Dynamic routing** tab and click **+ Dynamic route**.
   - **Name:** `dtaidemo`
   - **Matching condition:** `source == "dtaidemo"`
   - **Pipeline:** `dtaidemo`
2. Make sure the route sits **above** any catch-all route, then **Save**.

### B4. Verify
After 1–2 minutes, run in a Notebook:
```
timeseries v = avg(dtaidemo.queue_depth), by:{dt.entity.service}
```
The split should show your `SERVICE-…` ID. Enrichment only applies to **new** data, not to data that arrived before the pipeline existed.

> **Fallback:** if your tenant doesn't show **Metrics** in OpenPipeline, you can skip Part B and have the program
> add the ID itself. Add this line to `/etc/dtaidemo/config.env` and restart:
> `EXTRA_DIMENSIONS=dt.entity.service=SERVICE-1A2B3C4D5E6F7A8B`

### B5. Alert on it (makes the problem card)
**Anomaly Detection** app, then **+ Custom anomaly detector**:
- Query: `timeseries v = avg(dtaidemo.queue_depth), by:{dt.entity.service}`
- Model: **Static threshold**, alert **above `150`**, e.g. 3 of 5 violating samples
- Event template: `event.type = ERROR_EVENT` (or `CUSTOM_ALERT`), `dt.source_entity = {dims:dt.entity.service}`,
  `event.name = "Vendor X queue depth too high"`

Then run `sudo dtaidemo-spike` on the VM to test. A problem should open on the service within a few minutes.

---

## Part C: Does this create its own node in Smartscape?

**No.** Sending metrics, even with `dt.entity.service` attached, **does not create any new entity or Smartscape node**.
The dimension only *points at* the existing service. The metric becomes "about" that service: it can be charted per service
and the problem lands on the service node, but nothing new appears in the topology.

If you want the 3rd-party source to show up as **its own entity**, register a **custom device**:

1. Make sure your token has **`entities.write`** (see A1).
2. On the VM:
   ```bash
   cd ~/dtaidemo && ./create-custom-device.sh
   ```
   It prints an ID like `CUSTOM_DEVICE-ABCDEF0123456789`. Running it again updates the same device instead of making a duplicate.
3. Attach that ID to the metrics: either add `dt.entity.custom_device` in the OpenPipeline processor (B2, step 3 optional), or use
   `EXTRA_DIMENSIONS=dt.entity.custom_device=CUSTOM_DEVICE-…` in the config.
4. Find it in Dynatrace by searching for its display name. It has its own page with the metrics and any problems raised on it.
   Check with: `fetch dt.entity.custom_device | filter contains(entity.name, "Vendor X")`

**Caveat about the edge to the service:** a custom device is created **on its own**. It is *not* automatically connected to your
service in Smartscape. Dynatrace only draws edges it detects itself, for example from network traffic seen by OneAgent.
So, in practice:
- **Alert on the service:** use `dt.source_entity = {dims:dt.entity.service}` (problem shows on the service).
- **Alert on the device:** use `{dims:dt.entity.custom_device}`. The problem shows on the custom device, which then appears in the problem's affected entities.
- An explicit "device → service" relationship needs topology rules (Settings → Topology model, or the Smartscape extraction options in
  OpenPipeline on newer tenants). These options differ by tenant version, so check what your tenant offers before relying on them.
