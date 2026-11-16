# Changelog

Changes in PiScout-AV relative to upstream [RaspberryFluke](https://github.com/MKWB/RaspberryFluke) at commit `d5c78db`.

## 2026-11-16 – Share-ready README

### Changed
- `GW:` shows `OK`/`FAIL` for the gateway ping, not `PASS`/`FAIL`.
- README: materials list with Waveshare SKUs and links, plus what else you need. The roadmap is now "Future ideas".
- README install reordered to match the first real build. A new step 2, **Get online**, sets the route metric, then checks internet and the clock *before* `apt`. That's the order the first build actually needed. Step 4 now checks that the lldpd file reads back correctly.

## 2026-11-03 – Boot splash, voice VLAN and gateway ping on screen

### Added
- Boot splash: **HAVE YOU TRIED TURNING IT OFF AND ON AGAIN?** It's word-wrapped in the largest bold font that fits and shown for 5 s (`SPLASH_TEXT`, `SPLASH_SECONDS`). Discovery runs in the background meanwhile.

### Changed
- Screen 1: the VLAN line now also shows the voice VLAN (`VLAN: 1  VOICE: N/A`).
- Screen 2: the `GW:` line now shows `PASS`/`FAIL` for the gateway ping.

## 2026-11-03 – Diagnostics test the LAN only

### Fixed
- Diagnostics now test the wired LAN (`eth0`) only, so Wi-Fi can't answer for it:
  - `GW:` comes from the DHCP lease on `eth0`, not the system's default route.
  - The WAN and gateway pings use `ping -I eth0`.
  - The DNS check sends one query for google.com to the LAN's own DHCP-assigned DNS server, out of `eth0`. Before, it used the system resolver, which could answer over Wi-Fi.
- README step 4b: Ethernet's route metric is set to 700, so the Pi's own `apt` and `git` traffic prefers Wi-Fi.

## 2026-11-03 – Neighbor detection without a switch name

### Fixed
- A neighbor now counts as found once a **port** is learned. Before, it also needed a switch name and a VLAN, so a switch that doesn't send a System Name TLV (seen on a Netgear M4250) showed `NO NEIGHBOR` even though its port, VLAN, IP and model were all received.
- `SW:` shows `N/A` when no system name is advertised. The MAC stays on the diagnostics screen's `SW MAC:` line.
- `SW MAC` on the diagnostics screen showed `N/A` for up to a minute after boot, because the first diagnostics run happened before the first LLDP packet arrived. Diagnostics now re-run as soon as the neighbor info changes. This also refreshes them right away when you move to another port.
- An M4250 with no system name set was seen briefly advertising its serial number as the name.

## 2026-11-03 – Rename, V4 display driver, no-flash screen changes

### Changed
- Renamed `raspberryfluke.py` → `piscout_av.py`, `raspberryfluke.service` → `piscout-av.service`, and the install path `/opt/raspberryfluke` → `/opt/piscout-av`. "Fluke" now appears only in the credits, which name the upstream project.
- Display driver is now `epd2in13_V4`, matching the 2.13" e-Paper HAT+ (V4) on the unit. The upstream code used `epd2in13_V3`.
- The panel stays awake between updates, and screen changes use partial refresh. Before this, every screen change put the panel to sleep, woke it and did a full refresh, which caused the black/white flash.
- A full refresh now happens on the first neighbor, after 45 partials (`PARTIAL_REFRESH_LIMIT`, about every 15 min), or if a partial refresh fails.
- The loading animation stops once `NO NEIGHBOR` is shown. Before, it kept redrawing over that screen.
- README: install steps for Lite, deploy-key access for a private repo, and an update workflow (push from PC, `git pull` on the Pi).

## 2026-11-03 – Recovered from device and published

The code was recovered from the reference unit's `/opt/raspberryfluke`. The edits were made on the device around April 2026 and had never been committed. The `raspberryfluke.py.bak` file found on the device was byte-identical to the upstream script, so it was not kept.

### Added
- **Switch model** on screen 1 (`MODEL:`), taken from the first word of the LLDP system description.
- **Diagnostics screen** (screen 2): switch MAC, the Pi's IP (or `NO DHCP`), default gateway, WAN ping (8.8.8.8) and DNS (google.com), each shown as PASS/FAIL.
- A background diagnostics thread that refreshes every 60 s (`DIAG_POLL_INTERVAL_SECONDS`).
- **Screen rotation** between switch info and diagnostics every 20 s (`SCREEN_ROTATION_INTERVAL_SECONDS`).
- An **animated loading screen** (`Loading` → `Loading...`) using partial refresh.
- `waveshare_epd/` driver files (`__init__.py`, `epdconfig.py`, `epd2in13_V3.py`) are now included in the repo. Upstream had you clone Waveshare's repo and copy them in.

### Changed
- `raspberryfluke.service`: `RestrictAddressFamilies` now allows `AF_INET AF_INET6`, which the diagnostics pings and DNS lookups need. This edit was made only to the installed copy at `/etc/systemd/system/` and was recovered from there.
- Screen 1 shows `MODEL:` instead of `VOICE:`. The voice VLAN is still collected and still triggers a redraw when it changes.
- The switch-info tuple grew from 5 to 6 fields to hold the model.
- Removed several long explanatory docstrings and comments from the parsing functions.

### Known issues
- Every screen change does a full `init()` and full refresh, which makes the panel flash black/white.
- The gateway ping result is collected but not displayed.
