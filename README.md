# Family Wall Dashboard for Home Assistant

A drop-in **Mango Display replacement** for Home Assistant. It shows three
full-screen "screens" that rotate every **20 seconds** on a wall-mounted 32" TV
driven by a Raspberry Pi running Chromium in kiosk mode:

| Screen | Contents |
|--------|----------|
| **1** | Full-screen landscape family photo (slideshow) + large clock / day / date overlay (top-left) |
| **2** | Large full-month calendar (left) + portrait photo & clock (right) + 3 camera thumbnails |
| **3** | Portrait photo & clock (left) + next-6-days agenda list + weather forecast (right) + 3 camera thumbnails |

Plus: family photos pulled automatically from your **iCloud shared albums**,
five color-coded calendars, **Ring** camera thumbnails, a **camera pop-up** when
the doorbell rings or motion is detected, and optional **Wyze** cameras via
docker-wyze-bridge.

> **Yes — the 3 camera thumbnails are possible.** Ring cameras that are already
> in Home Assistant work directly. Wyze v4 cameras need the Wyze Bridge helper
> (Section 9) because Wyze v4 has no RTSP firmware and no live-video API. Good
> news: the bridge reaches your cameras over the internet via the Wyze cloud, so
> your **isolated camera network is not a blocker** — see Section 9.

---

## Get this package onto your Home Assistant

**Repo:** <https://github.com/michaelfiszlewicz/ha-family-calendar>

### About HACS (please read)
HACS installs *reusable components* only — **integrations, Lovelace cards, and
themes**. It does **not** install a personal dashboard, automations, or
`configuration.yaml` snippets, which is most of this package. So this repo is
installed by **cloning / downloading it into `/config`** (below), and HACS is
used only to install the **cards this dashboard depends on** (Section 5).

### Option A — Samba/SSH clone (recommended)
From a machine that can reach your HA files:
```bash
git clone https://github.com/michaelfiszlewicz/ha-family-calendar.git
```
Then copy the folders (`scripts/`, `automations/`, `lovelace/`, `docker/`) and
the two YAML files into `/config` as described in Section 1.

### Option B — Download ZIP
On the repo page: **Code → Download ZIP**, unzip, and copy the files into
`/config` per Section 1.

### Updating later
`git pull` in your clone (or re-download the ZIP) and re-copy changed files.

---

## Contents of this package

```
ha-family-calendar/
├── README.md                          <- you are here
├── configuration_additions.yaml       <- paste into configuration.yaml
├── lovelace/
│   └── family_dashboard.yaml          <- the 3-screen dashboard
├── automations/
│   ├── screen_rotation.yaml           <- 20-second rotation + photo cycling
│   ├── camera_overlay.yaml            <- doorbell / motion camera pop-up
│   └── photo_refresh.yaml             <- daily iCloud photo download
├── scripts/
│   └── icloud_photos.py               <- iCloud shared-album downloader
└── docker/
    ├── docker-compose-wyze.yml        <- Wyze bridge container
    └── wyze-bridge.env.example        <- Wyze credentials template
```

---

## 0. Prerequisites

1. **Home Assistant** (OS or Container/Supervised) up and running, and you can
   edit `configuration.yaml` (via the **File Editor** or **Studio Code Server**
   add-on).
2. **HACS** installed (Home Assistant Community Store) —
   <https://hacs.xyz/docs/setup/download>. Needed for the custom cards.
3. Your **Ring** integration already added (you confirmed these entities exist):
   - `camera.driveway_live_view`
   - `camera.front_door_live_view`
   - `camera.outside_deck_live_view`
   - `event.front_door_ding`
4. A **Raspberry Pi** (or any device) that will run Chromium in kiosk mode
   pointed at the dashboard URL.
5. Python 3 available inside Home Assistant (it is, on HA OS) to run the photo
   downloader.

---

## 1. Copy the files into your Home Assistant `/config`

Using the File Editor / Samba / SSH add-on, create this structure under
`/config`:

```
/config/
├── configuration.yaml            (you'll edit this)
├── scripts/
│   └── icloud_photos.py          (copy from scripts/)
├── automations/                  (only if you use directory-include, see §6)
│   ├── screen_rotation.yaml
│   ├── camera_overlay.yaml
│   └── photo_refresh.yaml
└── www/
    └── family_photos/            (auto-created by the script; put background.jpg here)
```

Copy `scripts/icloud_photos.py` to `/config/scripts/icloud_photos.py`.

---

## 2. Add the background image

Download the template background and save it as
`/config/www/family_photos/background.jpg`:

```bash
# run this from an SSH/terminal add-on inside Home Assistant
mkdir -p /config/www/family_photos
curl -L -o /config/www/family_photos/background.jpg \
  "https://displaytemplates.s3.amazonaws.com/media/TEMPLATES+BG+IMAGES/Template+11.jpg"
```

(You can swap in any image later — the dashboard references
`/local/family_photos/background.jpg`.)

Also drop a `placeholder.jpg` in `landscape/` and `portrait/` so the screens
show something before the first photo download:

```bash
mkdir -p /config/www/family_photos/landscape /config/www/family_photos/portrait
cp /config/www/family_photos/background.jpg /config/www/family_photos/landscape/placeholder.jpg
cp /config/www/family_photos/background.jpg /config/www/family_photos/portrait/placeholder.jpg
```

---

## 3. Add the configuration snippets

Open `configuration_additions.yaml` from this package and copy each block into
your `/config/configuration.yaml`. It adds:

- **5 calendars** (iCloud, Google-Mike, Google-Juno, US Holidays, Jewish
  Holidays) — color-coded on the dashboard.
- **Input helpers** — `input_number.dashboard_screen`, photo index helpers, and
  an `input_boolean.dashboard_rotate` pause switch.
- **shell_command** to run the photo downloader.
- **template + command_line sensors** that expose the "current" landscape /
  portrait photo to the dashboard.

> **Merge, don't duplicate:** if you already have a `calendar:` or `template:`
> key in your configuration.yaml, add these entries under the existing key.

### 3a. Install the ICS calendar integration

The calendar snippet uses `platform: ics`. Install **"ICS Calendar (ical)"**
from HACS (HACS → Integrations → search *ICS Calendar*), then restart.
Alternatively use the built-in **Remote Calendar** integration and add each URL
through the UI (Settings → Devices & Services → Add → *Remote Calendar*); if you
do that, update the `calendar.*` entity names in `family_dashboard.yaml`.

### 3b. Add Time & Date + Weather

- **Time & Date**: Settings → Devices & Services → Add Integration → *Time &
  Date* → enable **time** and **date** (creates `sensor.time`, `sensor.date`).
- **Weather**: Settings → Devices & Services → Add Integration → *Open-Meteo*
  → set location to **Liberty Township, OH (lat 39.3778, lon -84.3591)**. It
  creates a `weather.*` entity. If it isn't `weather.home`, edit the
  `entity: weather.home` line on Screen 3 to match.

---

## 4. Set up the iCloud photo downloader

The script `icloud_photos.py` pulls **full-resolution** photos from your two
public shared albums:

- **Landscape** (`B2d5n8hH47H6Qm`) → `/config/www/family_photos/landscape/`
- **Portrait** (`B2dG4TcsmGmq8Q7`) → `/config/www/family_photos/portrait/`

Test it once from a terminal add-on:

```bash
python3 /config/scripts/icloud_photos.py --output /config/www/family_photos
```

You should see it report a photo count and files appear in the folders, plus an
`index.json` in each. The `photo_refresh.yaml` automation re-runs it **daily at
4 AM** and once a minute after HA starts.

> **How it works:** the script talks to Apple's undocumented "shared streams"
> web API (no Apple ID needed for public albums), picks the largest derivative
> of each photo, and downloads it. Fully documented in the file's header.

> **If your HA blocks `shell_command` from running python** (rare on HA OS),
> you can instead run the script on the Pi via cron and write into a folder
> that HA serves. See Troubleshooting.

---

## 5. Install the custom cards (HACS → Frontend)

Open **HACS → Frontend → “＋ Explore & Download Repositories”** and install each
of these, then **reload the browser** (Ctrl-F5):

| Card | Why |
|------|-----|
| **Atomic Calendar Revamp** | Month grid (Screen 2) + agenda list (Screen 3) |
| **card-mod** | Custom CSS for layout / fonts / overlays |
| **state-switch** | Swaps between the 3 screens |
| **layout-card** | Grid layout for Screens 2 & 3 |
| **button-card** | Big clock / greeting panels |
| **browser_mod** | Camera pop-up on doorbell/motion |
| **kiosk-mode** | Hides HA header & sidebar on the wall |
| **album-slideshow-card** | *(already installed)* optional slideshow alt |

After installing, add each as a Lovelace **resource** if HACS didn't do it
automatically (Settings → Dashboards → ⋮ → Resources).

---

## 6. Install the automations

Pick **one** approach:

**A) Single automations.yaml (default HA):** open `/config/automations.yaml`
and paste the contents of all three files in `automations/` as list items
(each file is already a YAML list — just concatenate them).

**B) Directory include (cleaner):** add this line to `configuration.yaml`:

```yaml
automation manual: !include_dir_merge_list automations/
```

then copy the three files into `/config/automations/`. Keep any existing
`automation: !include automations.yaml` line as-is.

Restart Home Assistant (Developer Tools → YAML → **Check Configuration** first,
then **Restart**).

---

## 7. Create the dashboard

1. Settings → Dashboards → **＋ Add Dashboard** → *New dashboard from scratch* →
   title **Family Wall**, icon anything, → **Create**.
2. Open it → top-right **pencil (Edit)** → ⋮ menu → **Raw configuration editor**.
3. Delete the placeholder content and **paste the entire contents of
   `lovelace/family_dashboard.yaml`** → **Save**.
4. You should immediately see one of the three screens. Toggle
   `input_number.dashboard_screen` in Developer Tools → States (set 1, 2, 3) to
   preview each; the rotation automation will cycle it automatically.

---

## 8. Camera pop-up (doorbell / motion)

`automations/camera_overlay.yaml` shows a large live camera overlay:

- **Doorbell** → pops up `camera.front_door_live_view` when
  `event.front_door_ding` fires.
- **Motion** → pops up the matching camera when a Ring motion sensor turns on.
  Verify your motion entity names (Settings → Devices & Services → Ring) and
  update `binary_sensor.driveway_motion` etc. if they differ.

Both auto-dismiss after **30 seconds**.

**Target the right screen:** give your wall display a stable browser id:
open the dashboard on the Pi → HA sidebar shows *browser_mod* → set a
**Browser ID / register**; then uncomment and set `browser_id:` in the
automation so pop-ups only appear on the wall (not your phone).

---

## 9. Wyze v4 cameras (optional) — Wyze Bridge

**Key facts (important):** Wyze v4 cams have **no official RTSP firmware** and
**no live-video API** — the Wyze "Developer API" key is used for *login only*.
The only way to get a live stream is a bridge that logs into the Wyze cloud and
re-publishes each camera as RTSP/HLS/WebRTC.

**Your isolated-network setup works fine.** The bridge does **NOT** need a route
to your camera VLAN. It reaches each camera **over the internet** through the
Wyze cloud (P2P / relay / WebRTC). It only needs the bridge host to have
internet (your HA subnet does) and the cameras to have internet (your isolated
IoT VLAN allows that). We set **`NET_MODE=P2P`** so it skips LAN discovery and
connects straight over the net. **Run the bridge right on your HA subnet — it
never touches the isolated camera VLAN.**

> We use the **IDisposable fork** image (`idisposablegithub365/wyze-bridge`)
> because recent v4 firmware broke the old TUTK P2P, and this fork adds the
> WebRTC fallback that makes v4 work on current firmware.

**Steps:**

1. `cd docker/` → copy `wyze-bridge.env.example` to `wyze-bridge.env` and fill in
   your Wyze **email** + developer **API_ID / API_KEY**
   (generate at <https://developer-api-console.wyze.com/#/apikey/view>).
   With the API key set, the password is optional.
2. Run it on your HA host / HA subnet (needs internet, **not** camera-VLAN access):
   ```bash
   docker compose -f docker-compose-wyze.yml up -d
   ```
3. Open `http://<bridge-host>:5000` to confirm cameras appear and stream.
4. In Home Assistant, add each stream as a **Generic Camera**
   (Settings → Devices & Services → Add → *Generic Camera*):
   - Stream source: `rtsp://<bridge-host>:8554/<camera-nickname>`
   - (nickname = your Wyze camera name, lowercased, spaces→dashes)
5. Swap the Ring entities in `family_dashboard.yaml` for your new Wyze camera
   entities if you'd rather show those.

> **If cameras still time out (`IOTC_ER_TIMEOUT`):** current v4 firmware can be
> flaky over P2P. Confirm the stream loads in the bridge's own web UI (:5000)
> first — if it won't play there, it's a Wyze cloud/firmware issue, not HA. As a
> fallback you can bridge the two subnets with a VPN (Tailscale/WireGuard) and
> switch `NET_MODE` to `ANY`.

---

## 10. Kiosk mode on the Raspberry Pi

On the Pi, launch Chromium pointed at the dashboard in kiosk mode. Example
autostart command:

```bash
chromium-browser \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --incognito \
  --check-for-update-interval=31536000 \
  "http://<HOME_ASSISTANT_IP>:8123/family-wall/wall?kiosk"
```

- Replace `<HOME_ASSISTANT_IP>` with your HA address.
- The `?kiosk` query + the **kiosk-mode** plugin (Section 5) hide the header and
  sidebar.
- Create a **long-lived access token** and use a trusted-network / login so the
  Pi stays signed in. Consider the community "Fully Kiosk Browser" app as an
  alternative to Chromium — it also gives you screen on/off scheduling.

---

## 11. Troubleshooting

| Symptom | Fix |
|---------|-----|
| Screens don't rotate | Check `input_boolean.dashboard_rotate` is **on**; confirm `screen_rotation.yaml` automation is enabled (Settings → Automations). |
| "Custom element doesn't exist: state-switch / layout-card / …" | The HACS card isn't installed or its resource isn't loaded. Reinstall via HACS, hard-refresh (Ctrl-F5). |
| Photos don't appear | Run `python3 /config/scripts/icloud_photos.py` manually and read the output. Confirm files exist in `/config/www/family_photos/<landscape|portrait>/` and that `index.json` has a non-zero `count`. |
| Photo sensor blank | Developer Tools → States → check `sensor.landscape_index` has a `photos` attribute; check `input_number.photo_index_landscape`. |
| Calendar empty | Verify the `calendar.*` entities exist (Developer Tools → States) and the ICS integration is installed. iCloud URL must be the `https://` form (already converted for you). |
| Weather card error | Your weather entity isn't `weather.home` — edit Screen 3's `entity:` line. |
| Camera pop-up shows on phone too | Set `browser_id:` in `camera_overlay.yaml` to the wall display's id. |
| Clock is wrong | Set HA's timezone (Settings → System → General) to America/New_York. |

---

## Customization quick-reference

- **Rotation speed:** edit `seconds: "/20"` in `screen_rotation.yaml`.
- **Calendar colors:** edit the `color:` values in `family_dashboard.yaml`
  (iCloud=green, Mike=blue, Juno=cyan, US Holidays=orange, Jewish=purple).
- **Agenda length:** `maxDaysToShow: 6` on Screen 3.
- **Add more photos:** just add them to the iCloud shared albums — they sync on
  the next 4 AM refresh (or run the script manually).
- **Pause rotation:** turn off `input_boolean.dashboard_rotate`.

Enjoy your new family wall display! 🥭
