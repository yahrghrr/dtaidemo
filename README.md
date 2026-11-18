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

> **You need a service to tie the metrics to.** Parts B and C attach the Vendor X metrics, alert and Smartscape node to an
> existing Dynatrace **service**. If you don't have one, deploy the companion app
> **[yahrghrr/dynatrace-demo](https://github.com/yahrghrr/dynatrace-demo)** as a separate application monitored by
> Dynatrace OneAgent. See [Don't have a service yet?](#dont-have-a-service-yet) below.

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

## Don't have a service yet?

Parts B and C need an existing Dynatrace **service** for the Vendor X metrics to belong to. If you don't have one, deploy
**[yahrghrr/dynatrace-demo](https://github.com/yahrghrr/dynatrace-demo)**. It's a small Spring Boot web app with a `/normal`
endpoint (HTTP 200) and an `/error` endpoint (HTTP 500), built to be monitored by Dynatrace OneAgent.

1. **Install OneAgent on the VM first.** In Dynatrace: **Deploy Dynatrace → Start installation → Linux**, then run the
   generated command on the VM. (It can be the same VM as dtaidemo or a different one.)
2. **Deploy the app:**
   ```bash
   git clone https://github.com/yahrghrr/dynatrace-demo.git
   ```
   ```bash
   cd dynatrace-demo && sudo bash setup.sh
   ```
   If OneAgent was installed *after* the app, restart the app so OneAgent can monitor it:
   `sudo systemctl restart dynatrace-demo`
3. **Send some traffic** so Dynatrace sees requests and creates the service:
   ```bash
   bash scripts/trigger.sh baseline 30
   ```
   (30 minutes of healthy traffic. Press Ctrl+C to stop early.)
4. After a few minutes, a service called **dynatrace-demo** appears in the **Services** app. Use **its** `SERVICE-…` ID in
   step B1.

Full instructions, including the firewall and troubleshooting, are in that repository's README.

**Bonus: test Vendor X and service problems together.** With both apps running, run `sudo dtaidemo-spike` and, in the same few
minutes, `bash scripts/trigger.sh storm 10` in the dynatrace-demo folder (10 minutes of ~50% errors). If both events are
open at the same time, Dynatrace usually puts them on one problem card: check its **Events** tab. After Part C (C4 + C6),
Vendor X can also be shown as the **root cause** of the service's issues.

---

## Part B: Attach the service entity ID in OpenPipeline

Goal: every `dtaidemo.*` data point gets a dimension holding the service's ID (`SERVICE-XXXX`), so Davis can raise problems on that service.

> **Important:** OpenPipeline does **not** let a processor set or change reserved `dt.entity.*` fields. If you try
> `fieldsAdd dt.entity.service = …` you get *"It is not allowed to remove or modify field 'dt.entity.service'"*.
> So the pipeline adds the ID under **our own field name, `dtaidemo.service_id`**, and the alert (B5) and the Smartscape
> edge (Part C) use that field. If you'd rather have the real `dt.entity.service` dimension, see the box after B4.

### B1. Find your service's entity ID
(No service yet? Deploy the demo app first: see [Don't have a service yet?](#dont-have-a-service-yet).)

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

In the **Simple** tab this step only has two boxes:
- **Title:** `dtaidemo`
- **Event name:** `Vendor X queue depth too high on {dt.smartscape_source.id}`

That's all Simple needs. It fills in the link to the entity (`dt.smartscape_source.id`) and the event type for you, which
is why the `fieldsRename` line in the query matters.

*Optional, for full control:* switch to the **Advanced** tab. That's where the **Event description** box and the
**Event properties** rows are. If you use it:
- **Event description:** plain text for whoever reads the problem, e.g.
  `Queue depth from the Vendor X feed is above 150 for service {dt.smartscape_source.id}.`
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
new in Smartscape. To get a **node of its own, connected to your service**, you use the two Smartscape stages in your
OpenPipeline pipeline: **Smartscape node** creates the Vendor X node, and **Smartscape edge** connects the service to it.

**Which way the link points matters.** We model Vendor X as something the service **depends on**: the service *calls* Vendor X.
This is the direction Dynatrace follows when it looks for a root cause. When the service has problems, Dynatrace looks
**downstream** at what the service depends on, and if Vendor X has an open problem at the same time, Vendor X can be
reported as the root cause.

> **Before you start:** you need **Smartscape on Grail** and an OpenPipeline version that has the Smartscape stages
> (added in version 1.330). Field labels below match the pipeline editor as of late 2026; your tenant may differ slightly.

**What you'll end up with:**
```
 [ SERVICE: my-service ] ──(calls)──▶ [ CUSTOM_VENDORX_DEVICE: myvm ]
   the service depends on Vendor X        created from every dtaidemo data point
                                          (one node per VM, identified by "host")
```

### C1. Check which data type to use (metrics or logs)
1. Go to **Settings → Process and contextualize → OpenPipeline → Metrics** and open your `dtaidemo` pipeline from Part B.
2. Look at the list of stages. Directly below **Processing** you should see **Smartscape node** and **Smartscape edge**.
   - **Yes (most tenants):** use this Metrics pipeline for the steps below.
   - **No:** use the **log fallback**. On the VM, edit the config (`sudo nano /etc/dtaidemo/config.env`) and set (or add)
     `HEARTBEAT_LOGS=true`, then `sudo systemctl restart dtaidemo`. The program now also sends one small log line
     per cycle with the same `source` and `host` fields. (The token needs **Ingest logs**; see A1.)
     Then in OpenPipeline, open **Logs** (not Metrics) and create a pipeline + route exactly like **B2–B3**
     (same name, same matching condition `source == "dtaidemo"`, same DQL processor). Do steps C2–C5 in that **Logs** pipeline.

### C2. Check the service ID the link will point to
The link needs the ID that Smartscape on Grail uses for your service.
1. Open a **Notebook**, add a **DQL** section and run (put part of your service's name in the quotes):
   ```
   smartscapeNodes "SERVICE"
   | filter contains(name, "my-service")
   ```
2. Compare the ID shown with the `SERVICE-…` value you typed in B2.
   - **Same (usual case):** nothing to do. The **Attach service entity** processor already puts it on every record as
     `dtaidemo.service_id`.
   - **Different:** open the **Processing** stage, click **Attach service entity**, and change the definition to:
     ```
     fieldsAdd dtaidemo.service_id = "SERVICE-<your ID from B1>",
               dtaidemo.service_smartscape_id = "<ID from this step>"
     ```
     Then wherever C4 says `dtaidemo.service_id`, use `dtaidemo.service_smartscape_id` instead.

### C3. Create the node, field by field (Smartscape node stage)
1. In the pipeline, click **+ Smartscape node** (or the **+** at the right of the **Smartscape node** row).
   A **New Processor** panel opens on the right.
2. **Name:** type `dtaidemo device node`.
3. **Matching condition:** it says `true` by default. Replace it with:
   ```
   source == "dtaidemo"
   ```
4. **Node type:** type `CUSTOM_VENDORX_DEVICE`.
   Keep the `CUSTOM_` start, as the greyed-out example `CUSTOM_NodeType` shows. This is the type name you'll see in Smartscape.
5. **Node ID field name:** type `dtaidemo.device_id`.
   This is *where Dynatrace writes the new node's ID* on each record. It's a new field name, not something that already
   exists. You use it again in C4 (the link) and C6 (alerts).
6. **ID components:** these decide what makes one node different from another. We want one node per VM:
   - in the left box (**ID component**) type `host`
   - in the right box (**Referenced field name**) type `host`
   - click **Add**. The list below should change from *No ID components defined* to show `host → host`.
7. **Extract node:** switch the toggle **on** (*"Generate a smartscape event based on this signal"*).
   Without this, the node is never actually created.
8. **Scroll down** in the panel. Fill in whatever appears there:
   - a **node name** (or similar) field: `host`, so the node is labelled with the VM name
   - a **validity** / lifetime setting: `60` minutes (the program sends every 30 seconds, so the node stays alive)
   - **Recommended fields**: leave it as it is. Dynatrace copies those fields (e.g. `aws.region`) onto the node only when the
     data has them, and ours doesn't, so they're harmless.
   - **Static edges to extract**: **leave it empty.** A static edge can only point *from* this node *to* something else,
     which would make Vendor X depend on the service, the wrong way round. C4 adds the link in the other direction.
9. Click **Save** at the **top right** of the pipeline (blue button).

### C4. Make the service depend on Vendor X (Smartscape edge stage)
This link goes in the separate **Smartscape edge** stage, because it starts at the **service** and points **to** the Vendor X node.

> **Already added a static edge earlier?** (Older versions of this README linked Vendor X → service with **calls**.)
> Remove it first, or you'll have links in both directions: open **Smartscape node → dtaidemo device node**, scroll to
> **Static edges to extract**, delete the `calls → SERVICE` entry, and save.

1. In the pipeline, click **+ Smartscape edge** (or the **+** at the right of the **Smartscape edge** row).
2. **Name:** `dtaidemo service depends on vendor x`
3. **Matching condition:** replace `true` with
   ```
   source == "dtaidemo"
   ```
4. Fill in the **source** (the side the link starts from: the service):
   - **Source type:** `SERVICE`
   - **Source ID field name:** `dtaidemo.service_id`
     (or `dtaidemo.service_smartscape_id` if your IDs differed in C2)
5. **Edge type:** choose **calls**, meaning "the service calls Vendor X" (the service depends on it).
   If **calls** isn't offered, choose **uses**.
6. Fill in the **target** (the side the link points to: the Vendor X node):
   - **Target type:** `CUSTOM_VENDORX_DEVICE` (same as the node type in C3)
   - **Target ID field name:** `dtaidemo.device_id` (the node ID field from C3, step 5)
7. Click **Save** at the top right of the pipeline.

The node stage runs before the edge stage, so `dtaidemo.device_id` is already filled in when the edge is built.
When you're done, the pipeline should show **Processing 1**, **Smartscape node 1** and **Smartscape edge 1**.

> Exact labels in the edge panel may differ slightly (e.g. *Source node type* / *Target node type*). What matters is:
> **from** `SERVICE` using `dtaidemo.service_id`, **to** `CUSTOM_VENDORX_DEVICE` using `dtaidemo.device_id`, type **calls**.

### C5. Check it worked (wait ~2–5 minutes)
1. **The node exists:** in a Notebook run
   ```
   smartscapeNodes "CUSTOM_VENDORX_DEVICE"
   ```
   You should see one row per VM running the program.
2. **The link exists and points the right way:** open **Smartscape**, find your service (e.g. `dynatrace-demo`) and open
   **View topology → Related nodes**. `CUSTOM_VENDORX_DEVICE` should now appear under **Target**, with the arrow going
   from the service to it labelled **calls**. If it appears under **Source** instead, the old static edge is still there
   (see the note at the start of C4).
3. **Nothing appears?** Check that:
   - the processor shows no red warning icon in the pipeline
   - **Extract node** is on
   - the matching conditions say `source == "dtaidemo"`, not `true` or a typo
   - the field names are typed exactly: `dtaidemo.device_id`, `dtaidemo.service_id`
   - in the edge: source = `SERVICE`, target = `CUSTOM_VENDORX_DEVICE` (not swapped)
   - the program is still sending (`sudo journalctl -u dtaidemo -f` shows `HTTP 202`)

### C6. Alerts and problems: move the Vendor X alert onto the Vendor X node
For root-cause analysis, the Vendor X problem has to be **on the Vendor X node**, not on the service. Otherwise it's just
another event on the service, and there's nothing downstream for Dynatrace to point to.

1. Open the alert from **B5** (**Anomaly Detection** app) and change the query to:
   ```
   timeseries v = avg(dtaidemo.queue_depth), by:{dtaidemo.device_id}
   | fieldsRename dt.smartscape_source.id = dtaidemo.device_id
   ```
2. Optional: change the **Event name** to `Vendor X queue depth too high on {dt.smartscape_source.id}`.
3. **Save.** Click **Preview** first if you like: the line should now be labelled with the Vendor X node's ID instead of `SERVICE-…`.

**What happens now:**

| Situation | Result |
|---|---|
| Only Vendor X spikes | A problem on the **Vendor X node**. The service is listed as affected only if it also shows issues. |
| Only the service has issues (e.g. errors) | A problem on the **service**, from Dynatrace's own detection. Vendor X isn't involved. |
| Both at the same time | Dynatrace sees an issue on the service *and* on something it depends on, so it can merge them into **one problem** and point to **Vendor X as the root cause**. |

To test the last row, see **Bonus** under [Don't have a service yet?](#dont-have-a-service-yet): run `sudo dtaidemo-spike` and
`bash scripts/trigger.sh storm 10` at the same time, then open the problem's **root cause** section.

> **Not guaranteed:** whether Dynatrace's root-cause analysis follows links created through OpenPipeline (rather than links
> OneAgent discovers itself) can depend on your tenant version. If the two events show up as separate problems, or are
> merged without Vendor X as the root cause, the setup above is still correct; the root-cause engine just doesn't use
> custom links on your tenant yet.

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
