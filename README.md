# PiScout-AV

A pocket network port identifier for AV technicians. Plug it into a wall jack or switch port and the e-paper screen shows which switch and port you're on, the VLAN, and whether the network can actually reach the internet. That's the "is this drop live and on the right VLAN?" question you ask before blaming the DSP, codec or control processor.

It runs on a Raspberry Pi Zero 2 W with a Waveshare 2.13" e-paper display. It's powered by PoE or a USB power bank.

> **Fork notice:** PiScout-AV is a modified version of **[RaspberryFluke](https://github.com/MKWB/RaspberryFluke)** by MKWB, which is MIT-licensed. The same author's newer project is **[PiScout](https://github.com/MKWB/PiScout)**. The original commit history is kept in this repo. See [Credits & licenses](#credits--licenses).

---

## Features

**Screen 1 – Switch info**, learned from LLDP or CDP:

| Line | Shows |
|---|---|
| `SW:` | Switch hostname, with the domain suffix removed |
| `IP:` | Switch management IP |
| `PORT:` | Switch port, shortened (`GigabitEthernet1/0/24` → `Gi1/0/24`) |
| `VLAN:` | Access (native) VLAN |
| `MODEL:` | Switch model, taken from the first word of the switch's system description |

**Screen 2 – Diagnostics**, refreshed every 60 s:

| Line | Shows |
|---|---|
| `SW MAC:` | Switch chassis MAC |
| `MY IP:` | The Pi's own DHCP address on `eth0`, or `NO DHCP` |
| `GW:` | Default gateway |
| `WAN:` | `PASS`/`FAIL` for a ping to 8.8.8.8 |
| `DNS:` | `PASS`/`FAIL` for resolving google.com |

**Behavior:**
- Animated `Loading...` screen while it waits for the first LLDP/CDP packet.
- Switches between the two screens every 20 s once a neighbor is found.
- Shows `NO NEIGHBOR` if nothing is heard within 180 s. Some CDP environments take 45–90 s.
- Redraws immediately if the VLAN or voice VLAN changes, at most once every 10 s, to protect the panel.
- Forces a full refresh after 8 partial refreshes to prevent ghosting.
- Listens only and never transmits LLDP/CDP: `lldpd` runs in receive-only mode.
- Starts at boot as a hardened systemd service.

**Known gaps:** these are on the roadmap below.
- The voice VLAN is still collected and still triggers a redraw when it changes, but it is no longer displayed. `MODEL` took its place.
- The gateway ping result is collected but not displayed.
- Changing screens does a full refresh, so the display flashes black/white each time.

---

## Hardware

| Part | Notes |
|---|---|
| Raspberry Pi Zero 2 W | With a 40-pin male GPIO header soldered on |
| Waveshare 2.13" e-Paper HAT, **V3** (250×122) | The code uses the `epd2in13_V3` driver. The original project lists the HAT+ (SKU 27467). |
| Power | A PoE splitter/HAT, or a USB power bank. The original project uses the Waveshare PoE Ethernet / USB HUB BOX (SKU 20895). |
| microSD card | 8 GB or larger |

---

## Install (Raspberry Pi OS Lite)

The target is **Raspberry Pi OS Lite, 64-bit, Debian 13 "trixie"**.

> **Status:** the reference unit currently runs the *desktop* edition of trixie. These Lite steps have not yet been tested end to end on a fresh card. The package list adds `python3-spidev`, `python3-gpiozero` and `fonts-dejavu-core`, which the driver and the script need and which the desktop edition may already include.

### 1. Flash the card

In **Raspberry Pi Imager**, choose *Raspberry Pi Zero 2 W* → *Raspberry Pi OS Lite (64-bit)*. Then open the OS customisation settings and set:
- a hostname
- a username and password
- **Enable SSH**
- Wi-Fi, which is optional but handy for managing the unit while `eth0` is plugged into the port under test

Boot the Pi and SSH in.

### 2. Update and install packages

```bash
sudo apt update && sudo apt full-upgrade -y
```

```bash
sudo apt install -y git lldpd python3 python3-pil python3-spidev python3-gpiozero python3-lgpio fonts-dejavu-core
```

### 3. Enable SPI, needed for the display

```bash
sudo raspi-config nonint do_spi 0
```

```bash
sudo reboot
```

### 4. Configure lldpd: receive-only, with CDP enabled

```bash
echo 'DAEMON_ARGS="-r -c"' | sudo tee /etc/default/lldpd
```

```bash
sudo systemctl restart lldpd
```

`-r` means receive only (never transmit). `-c` enables CDP for Cisco switches.

### 5. Get the code into `/opt/raspberryfluke`

The install path and service name are still `raspberryfluke`, inherited from the original project.

**If the repo is public**, clone it on the Pi:

```bash
sudo git clone https://github.com/WonderWerks/PiScout-AV.git /opt/raspberryfluke
```

**If the repo is private**, copy it from a PC that already has it cloned. Run this on the PC:

```bash
scp -r PiScout-AV <user>@<pi-address>:~/
```

Then on the Pi:

```bash
sudo mv ~/PiScout-AV /opt/raspberryfluke && sudo chown -R root:root /opt/raspberryfluke
```

### 6. Install and start the service

```bash
sudo cp /opt/raspberryfluke/raspberryfluke.service /etc/systemd/system/
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now raspberryfluke.service
```

### 7. Verify

```bash
systemctl status raspberryfluke.service
```

```bash
journalctl -u raspberryfluke.service -f
```

The log prints a `Data update: SW=... PORT=... VLAN=...` line once a neighbor is heard, and a `Diag: ...` line every 60 s.

---

## Configuration

All settings are constants at the top of `raspberryfluke.py`:

| Constant | Default | Purpose |
|---|---|---|
| `IFACE` | `eth0` | Wired interface to listen on |
| `POLL_INTERVAL_SECONDS` | `1` | How often `lldpctl` is queried |
| `NO_NEIGHBOR_TIMEOUT_SECONDS` | `180` | Wait before showing `NO NEIGHBOR` |
| `SCREEN_ROTATION_INTERVAL_SECONDS` | `20` | Time on each screen |
| `DIAG_POLL_INTERVAL_SECONDS` | `60` | How often ping/DNS checks run |
| `MIN_DISPLAY_UPDATE_INTERVAL_SECONDS` | `10` | Minimum gap between redraws when the VLAN changes |
| `PARTIAL_REFRESH_LIMIT` | `8` | Partial refreshes before a forced full refresh |

After editing, restart the service:

```bash
sudo systemctl restart raspberryfluke.service
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Stuck on `Loading...` / `NO NEIGHBOR` | Run `sudo lldpctl`. If it shows nothing, the switch isn't sending LLDP/CDP on that port, or `lldpd` isn't running (`systemctl status lldpd`). |
| `IP: N/A` on screen 1 | The switch isn't advertising a management address TLV. This is common and harmless. |
| Blank screen, service crashing | Run `journalctl -u raspberryfluke.service -n 50`. Check that SPI is enabled (`ls /dev/spidev0.0`) and that the packages in step 2 are installed. |
| `MY IP: NO DHCP` | The port has no DHCP for this VLAN, or the cable/port is bad. |
| `WAN: FAIL` but `DNS: PASS` | ICMP to 8.8.8.8 is blocked upstream. This is common on corporate networks. |

---

## Project layout

```text
raspberryfluke.py        main script (LLDP/CDP polling, diagnostics, display loop)
raspberryfluke.service   systemd unit
waveshare_epd/           Waveshare driver files needed for the 2.13" V3 panel
Images/                  build photos from the original project
CHANGELOG.md             what changed relative to upstream RaspberryFluke
```

---

## Roadmap

- [ ] Fix the black/white flash when switching screens (use partial refresh for screen changes)
- [ ] Verify a clean install on Raspberry Pi OS Lite
- [ ] Show the voice VLAN and gateway ping again
- [ ] Small web UI with more detail (full LLDP/CDP neighbor dump, history)
- [ ] Rename the install path and service from `raspberryfluke` to `piscout-av`

---

## Credits & licenses

- **RaspberryFluke**, © MKWB (𝕄ᶜᏦ𝘦ɴɴ𝒶), MIT License. This is the original project the fork is based on: <https://github.com/MKWB/RaspberryFluke>
- **PiScout** by the same author is its successor: <https://github.com/MKWB/PiScout>
- **Waveshare e-Paper drivers** (`waveshare_epd/`), © Waveshare, MIT-style license in each file header: <https://github.com/waveshare/e-Paper>
- PiScout-AV modifications © 2026 WonderWerks, released under the same MIT License. See [LICENSE](LICENSE).
