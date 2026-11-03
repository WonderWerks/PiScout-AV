# Changelog

Changes in PiScout-AV relative to upstream [RaspberryFluke](https://github.com/MKWB/RaspberryFluke) at commit `d5c78db`.

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
