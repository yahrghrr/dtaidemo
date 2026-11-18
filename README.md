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
   - Optional: **Ingest logs** (`logs.ingest`), only needed for the log fallback in Part C.
   - Optional: **Write entities** (`entities.write`), only needed for the classic custom device in Part D.
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
| Update to the latest version (keeps your settings) | `cd ~/dtaidemo && git pull && sudo ./install.sh` |
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

Goal: every `dtaidemo.*` data point gets a dimension holding the service's ID (`SERVICE-XXXX`), so Davis can raise problems on that service.

> **Important:** OpenPipeline does **not** let a processor set or change reserved `dt.entity.*` fields. If you try
> `fieldsAdd dt.entity.service = …` you get *"It is not allowed to remove or modify field 'dt.entity.service'"*.
> So the pipeline adds the ID under **our own field name, `dtaidemo.service_id`**, and the alert (B5) and the Smartscape
> edge (Part C) use that field. If you'd rather have the real `dt.entity.service` dimension, see the box after B4.

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
     fieldsAdd dtaidemo.service_id = "SERVICE-1A2B3C4D5E6F7A8B"
     ```
     **Replace `SERVICE-1A2B3C4D5E6F7A8B` with your real ID from B1.** The value in this README is only an example.
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
timeseries v = avg(dtaidemo.queue_depth), by:{dtaidemo.service_id}
```
The split should show your `SERVICE-…` ID. Enrichment only applies to **new** data, not to data that arrived before the pipeline existed.

> **Want the real `dt.entity.service` dimension too?** Only the data source can set it, not OpenPipeline. The program can
> do that for you: add this line to `/etc/dtaidemo/config.env` and run `sudo systemctl restart dtaidemo`:
> `EXTRA_DIMENSIONS=dt.entity.service=SERVICE-1A2B3C4D5E6F7A8B` (your real ID).
> The metrics are then linked to the service natively (e.g. they appear as the service's metrics). This is optional;
> everything in this README works with `dtaidemo.service_id` alone. It's also the fallback if your tenant doesn't show
> **Metrics** in OpenPipeline at all.

### B5. Alert on it (makes the problem card)
Open the **Anomaly Detection** app and click **+ Custom alert** (older UIs: **Custom anomaly detector**). Use the **Simple** tab.

**1. Set scope, then Query.** Copy both lines:
```
timeseries v = avg(dtaidemo.queue_depth), by:{dtaidemo.service_id}
| fieldsRename dt.smartscape_source.id = dtaidemo.service_id
```
The second line matters. The alert links the problem to an entity through a dimension called **`dt.smartscape_source.id`**
(the hint under the query box says so), so we give our service ID that name.

**2. Define alert condition**
- Use case: **Static threshold**
- Threshold: `150`, Unit: leave as is
- Alert condition: **Alert if metric is above**
- Click **Preview**: you should see one line per service ID, with spikes above 150 if one has happened recently.

**3. Add details**
- **Title:** `dtaidemo`
- **Event name:** `Vendor X queue depth too high`
- **Event description:** plain text for whoever reads the problem, e.g.
  `Queue depth from the Vendor X feed is above 150 for service {dims:dt.smartscape_source.id}.`
- **Event properties:** you only need these two rows. Delete any others.

  | Key | Value |
  |---|---|
  | `dt.smartscape_source.id` | `{dt.smartscape_source.id}` (pre-filled; keep it) |
  | `event.type` | `CUSTOM_ALERT` (or `ERROR_EVENT`) |

  Don't type the README's instructions into these boxes. `event.name` and `event.description` are filled from the fields
  above, so they don't need rows of their own.

Click **Save**.

> **Older tenants:** if your alert screen has no `dt.smartscape_source.id` hint or property, it uses the classic field instead.
> Leave out the `fieldsRename` line and add the property `dt.source_entity` = `{dims:dtaidemo.service_id}`.

Then run `sudo dtaidemo-spike` on the VM to test. A problem should open on the service within a few minutes.

---

## Part C: Create a Smartscape node and link it to the service (OpenPipeline)

Part B only *tags* the metrics with the service ID. That makes problems land on the service, but it does **not** draw anything
new in Smartscape. To get a **node of its own, connected to your service**, you use the two Smartscape stages in OpenPipeline:
**Smartscape node extraction** creates the node, and an **edge** connects it to the service.

> **Before you start:** you need **Smartscape on Grail** and an OpenPipeline version that has the Smartscape stages
> (added in version 1.330). These steps were written from Dynatrace's docs summaries and a working example; exact field
> labels and the list of edge types may look slightly different on your tenant.

**What you'll end up with:**
```
 [ VENDORX_DEVICE: myvm ] ──(edge)──▶ [ SERVICE: my-service ]
          ▲
   created from every dtaidemo data point (one node per VM, identified by "host")
```

### C1. Check which data type to use (metrics or logs)
1. Open the **OpenPipeline** app, then **Metrics**, then your `dtaidemo` pipeline from Part B.
2. Look at the list of stages. Do you see **Smartscape node extraction**?
   - **Yes:** use this Metrics pipeline for the steps below.
   - **No:** use the **log fallback**. On the VM, edit the config (`sudo nano /etc/dtaidemo/config.env`) and set (or add)
     `HEARTBEAT_LOGS=true`, then `sudo systemctl restart dtaidemo`. The program now also sends one small log line
     per cycle with the same `source` and `host` fields. (The token needs **Ingest logs**; see A1.)
     Then in OpenPipeline, open **Logs** (not Metrics) and create a pipeline + route exactly like **B2–B3**
     (same name, same matching condition `source == "dtaidemo"`, same DQL processor). Do steps C2–C4 in that **Logs** pipeline.

### C2. Find the service's Smartscape ID
The edge needs the ID that Smartscape on Grail uses for your service. In a **Notebook**, run:
```
smartscapeNodes "SERVICE"
| filter contains(name, "my-service")
```
Copy the ID shown. It's usually the same `SERVICE-…` value you used in Part B.

### C3. Make sure the service ID is on each record (Processing stage)
- **Same ID as in B2:** nothing to do. The **Attach service entity** processor already adds `dtaidemo.service_id`.
- **Different ID:** edit that processor and add a second field with the C2 value:
  ```
  fieldsAdd dtaidemo.service_id = "SERVICE-1A2B3C4D5E6F7A8B",
            dtaidemo.service_smartscape_id = "<ID from C2>"
  ```
  Then use `dtaidemo.service_smartscape_id` as the target ID field in C4.

The processing stage runs **before** the Smartscape stage, so the field is available when the node and edge are built.

### C4. Create the node and the link (Smartscape node extraction stage)
1. Still in the same pipeline, open the **Smartscape node extraction** stage and click **+ Processor**.
2. Fill it in:

   | Setting | Value | Why |
   |---|---|---|
   | **Name** | `dtaidemo device node` | just a label |
   | **Matching condition** | `source == "dtaidemo"` | only our data |
   | **Node type** | `VENDORX_DEVICE` | capital letters, your own name; this becomes the node type in Smartscape (like `CUSTOM_TERMINALS` in the example) |
   | **ID components** | `host` | one node per VM; the same host always gives the same node ID |
   | **Node name** | `host` | the name shown on the node |
   | **Extract node** | on | actually creates and stores the node |
   | **Node validity** (if shown) | `60` minutes | how long the node stays after the last data point (allowed 60–1440) |

3. In the same processor, add a **static edge** (this is the link to the service):

   | Setting | Value |
   |---|---|
   | **Edge type** | pick the relationship from the list. A device feeding a service usually fits **calls**, or **belongs to** if it's part of that service |
   | **Target type** | `SERVICE` |
   | **Target ID field** | `dtaidemo.service_id` (or `dtaidemo.service_smartscape_id` if the IDs differed in C2) |

4. **Save** the pipeline. The route from B3 already sends the data here, so nothing else needs changing.

> **Static or dynamic edge?** A *static edge* (above) is attached to the node itself and is the simplest choice when the device
> always belongs to the same service. If the device → service relationship changes over time, use the separate
> **Smartscape edge extraction** stage instead. It records the link as it was at each data point, using Smartscape IDs that are
> already on the record.

### C5. Check it worked (wait ~2–5 minutes)
1. **The node exists:** in a Notebook run
   ```
   smartscapeNodes "VENDORX_DEVICE"
   ```
   You should see one row per VM running the program.
2. **The link exists:** open **Smartscape on Grail**, search for your VM name in **Find nodes**, click it, then **View topology**.
   You should see a line to your service. Turn on **Hide unconnected nodes**: if your node still shows, it's linked.
   (In the example screenshot the `CUSTOM_TERMINALS` nodes are loose dots because they have no edges.)
3. **Nothing appears?** Check that:
   - the route's matching condition really matches (`source == "dtaidemo"`)
   - the Processing processor runs (the Notebook query from B4 shows the service ID)
   - the target ID field name in C4 matches the field you added in C3 exactly
   - the program is still sending (`sudo journalctl -u dtaidemo -f` shows `HTTP 202`)

### C6. Alerts and problems
- Keep the anomaly detector from **B5** as it is (it links the problem through `dt.smartscape_source.id`). The problem lands on the
  **service**, and because the device node is now linked to it, the relationship is visible when you open the topology
  around the problem.
- If you'd rather have problems on the **device node**, check in your tenant which dimension the node extraction adds to
  the records. It's typically a field carrying the new node's Smartscape ID. Split the detector's query by that dimension and
  rename it to `dt.smartscape_source.id` (same `fieldsRename` trick as B5).

---

## Part D (alternative, classic): custom device via API

If your tenant doesn't have Smartscape on Grail or the Smartscape stages in OpenPipeline, you can still create a **classic custom
device** entity. It gets its own page with charts and problems, but it is **not linked** to the service in Smartscape.

1. Make sure your token has **`entities.write`** (see A1).
2. On the VM:
   ```bash
   cd ~/dtaidemo && ./create-custom-device.sh
   ```
   It prints an ID like `CUSTOM_DEVICE-ABCDEF0123456789`. Running it again updates the same device rather than creating a duplicate.
3. Attach that ID to the metrics. OpenPipeline can't set `dt.entity.*` fields, so do it on the VM: add this line to
   `/etc/dtaidemo/config.env` and run `sudo systemctl restart dtaidemo`:
   `EXTRA_DIMENSIONS=dt.entity.custom_device=CUSTOM_DEVICE-…`
   (To also send the service ID, separate them with a comma:
   `EXTRA_DIMENSIONS=dt.entity.service=SERVICE-…,dt.entity.custom_device=CUSTOM_DEVICE-…`)
4. Find it in Dynatrace by searching for its display name. For problems on the device, use `{dims:dt.entity.custom_device}` as
   `dt.source_entity` in the detector.
