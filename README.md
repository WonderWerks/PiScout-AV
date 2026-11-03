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
- Screen changes use partial refresh, so there is no black/white flash. A full refresh happens on the first neighbor and then roughly every 15 minutes to clear ghosting.
- Listens only and never transmits LLDP/CDP: `lldpd` runs in receive-only mode.
- Starts at boot as a hardened systemd service.

**Known gaps:** these are on the roadmap below.
- The voice VLAN is still collected and still triggers a redraw when it changes, but it is no longer displayed. `MODEL` took its place.
- The gateway ping result is collected but not displayed.

---

## Hardware

| Part | Notes |
|---|---|
| Raspberry Pi Zero 2 W | With a 40-pin male GPIO header soldered on |
| Waveshare **2.13" e-Paper HAT+** (250×122, **V4**) | Uses the `epd2in13_V4` driver. Check the version sticker on the back of the board. |
| Waveshare **PoE-ETH-USB-HUB-BOX** | Case plus a PoE/Ethernet/USB hub for the Pi Zero. The stock lid doesn't fit over the display; a 3D-printed lid is on the roadmap. |
| microSD card | 8 GB or larger |

A USB power bank also works when the port has no PoE.

---

## Install (Raspberry Pi OS Lite)

The target is **Raspberry Pi OS Lite, 64-bit, Debian 13 "trixie"**.

> **Status:** being validated with a ground-up rebuild on a fresh card. This note will be removed once that rebuild passes.

### 1. Flash the card

In **Raspberry Pi Imager**, choose *Raspberry Pi Zero 2 W* → *Raspberry Pi OS Lite (64-bit)*. Then open the OS customisation settings and set:
- hostname: `piscout-av`
- a username and password
- **Enable SSH**
- **Wi-Fi, plus the Wi-Fi country.** Setup downloads packages and the code, so the Pi needs internet access. Wi-Fi is the easiest way to give it that, especially if the wired network you set up on has no internet. It's also handy later for managing the unit while `eth0` is plugged into the port under test.

> **Pi Zero 2 W is 2.4 GHz only.** If you use a phone hotspot, set it to 2.4 GHz. On an iPhone, turn on *Maximize Compatibility*.

Boot the Pi and SSH in, using `ssh <user>@piscout-av.local` or the Pi's IP address.

Forgot Wi-Fi in Imager? You can add it from the Pi instead of reimaging. Change `US` to your two-letter country code if needed. The connect command asks for the Wi-Fi password.

```bash
sudo raspi-config nonint do_wifi_country US
```

```bash
sudo rfkill unblock wifi; sudo nmcli radio wifi on
```

```bash
sudo nmcli --ask device wifi connect "<your-SSID>"
```

### 2. Update and install packages

First check the clock. The Pi has no clock battery, and if its time is behind, `apt` rejects Debian's package signatures as `Not live until ...`.

```bash
timedatectl | grep -E 'Local|synchronized'
```

If it shows `synchronized: no` or the wrong date, set the clock from a web server's response:

```bash
sudo date -s "$(curl -sI http://deb.debian.org | grep -i '^date:' | cut -d' ' -f2-)"
```

Then update and install:

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

### 5. Give the Pi read access to the repo (deploy key)

Skip this step if the repo is public.

Create a key on the Pi. It has no passphrase, so the Pi can pull on its own.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/piscout_deploy -N "" -C piscout-av-deploy
```

Print the **public** half:

```bash
cat ~/.ssh/piscout_deploy.pub
```

On GitHub, go to the repo → **Settings → Deploy keys → Add deploy key**. Paste the **whole line** printed above, from `ssh-ed25519` through `piscout-av-deploy`. GitHub rejects the key as "invalid" if the `ssh-ed25519` prefix is missing. Name the key after the unit, and leave **Allow write access unticked**. The Pi can then read this one repo and nothing else.

Trust GitHub's host key:

```bash
ssh-keyscan github.com >> ~/.ssh/known_hosts
```

### 6. Clone into `/opt/piscout-av`

The folder belongs to your user, so later updates don't need `sudo`.

```bash
sudo mkdir -p /opt/piscout-av && sudo chown $USER: /opt/piscout-av
```

Private repo (uses the deploy key, which git remembers for future pulls):

```bash
git clone -c core.sshCommand="ssh -i ~/.ssh/piscout_deploy" git@github.com:WonderWerks/PiScout-AV.git /opt/piscout-av
```

Public repo:

```bash
git clone https://github.com/WonderWerks/PiScout-AV.git /opt/piscout-av
```

### 7. Install and start the service

```bash
sudo cp /opt/piscout-av/piscout-av.service /etc/systemd/system/
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now piscout-av.service
```

### 8. Verify

```bash
systemctl status piscout-av.service
```

```bash
journalctl -u piscout-av.service -f
```

The log prints a `Data update: SW=... PORT=... VLAN=...` line once a neighbor is heard, and a `Diag: ...` line every 60 s.

---

## Updating

Make changes on your PC, commit and push to GitHub. Then pull on the Pi:

```bash
git -C /opt/piscout-av pull && sudo systemctl restart piscout-av.service
```

If `piscout-av.service` itself changed, reinstall it before restarting:

```bash
sudo cp /opt/piscout-av/piscout-av.service /etc/systemd/system/ && sudo systemctl daemon-reload
```

---

## Configuration

All settings are constants at the top of `piscout_av.py`:

| Constant | Default | Purpose |
|---|---|---|
| `IFACE` | `eth0` | Wired interface to listen on |
| `POLL_INTERVAL_SECONDS` | `1` | How often `lldpctl` is queried |
| `NO_NEIGHBOR_TIMEOUT_SECONDS` | `180` | Wait before showing `NO NEIGHBOR` |
| `SCREEN_ROTATION_INTERVAL_SECONDS` | `20` | Time on each screen |
| `DIAG_POLL_INTERVAL_SECONDS` | `60` | How often ping/DNS checks run |
| `MIN_DISPLAY_UPDATE_INTERVAL_SECONDS` | `10` | Minimum gap between redraws when the VLAN changes |
| `PARTIAL_REFRESH_LIMIT` | `45` | Partial refreshes before a full (flashing) refresh to clear ghosting |

After editing, restart the service:

```bash
sudo systemctl restart piscout-av.service
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| `apt update` fails with `Temporary failure resolving` | No internet or DNS on the active network. Connect Wi-Fi (see step 1). |
| `apt update` fails with `Not live until <date>` | The Pi's clock is behind, because it has no clock battery. Check `timedatectl`. If NTP can't reach the internet, set the clock from a web server's response: `sudo date -s "$(curl -sI http://deb.debian.org \| grep -i '^date:' \| cut -d' ' -f2-)"` |
| `nmcli` says `No network with SSID ... found` | Set the Wi-Fi country (step 1) and make sure the network is 2.4 GHz. |
| Stuck on `Loading...` / `NO NEIGHBOR` | Run `sudo lldpctl`. If it shows nothing, the switch isn't sending LLDP/CDP on that port, or `lldpd` isn't running (`systemctl status lldpd`). |
| `IP: N/A` on screen 1 | The switch isn't advertising a management address TLV. This is common and harmless. |
| Blank screen, service crashing | Run `journalctl -u piscout-av.service -n 50`. Check that SPI is enabled (`ls /dev/spidev0.0`) and that the packages in step 2 are installed. |
| `MY IP: NO DHCP` | The port has no DHCP for this VLAN, or the cable/port is bad. |
| `WAN: FAIL` but `DNS: PASS` | ICMP to 8.8.8.8 is blocked upstream. This is common on corporate networks. |

---

## Project layout

```text
piscout_av.py            main script (LLDP/CDP polling, diagnostics, display loop)
piscout-av.service   systemd unit
waveshare_epd/           Waveshare driver files needed for the 2.13" HAT+ (V4) panel
Images/                  build photos from the original project
CHANGELOG.md             what changed relative to upstream RaspberryFluke
```

---

## Roadmap

- [ ] Verify a clean install on Raspberry Pi OS Lite
- [ ] Show the voice VLAN and gateway ping again
- [ ] Web UI on Wi-Fi and Ethernet: full neighbor details, diagnostics, Pi health, Save-to-log and Reset buttons
- [ ] Wi-Fi hotspot fallback when no known Wi-Fi is in range (with an off switch)
- [ ] Passive listeners: IGMP querier, STP root bridge, PTP grandmaster, mDNS/Dante devices
- [ ] 3D-printed lid for the PoE-ETH-USB-HUB-BOX that clears the display

---

## Credits & licenses

- **RaspberryFluke**, © MKWB (𝕄ᶜᏦ𝘦ɴɴ𝒶), MIT License. This is the original project the fork is based on: <https://github.com/MKWB/RaspberryFluke>
- **PiScout** by the same author is its successor: <https://github.com/MKWB/PiScout>
- **Waveshare e-Paper drivers** (`waveshare_epd/`), © Waveshare, MIT-style license in each file header: <https://github.com/waveshare/e-Paper>
- PiScout-AV modifications © 2026 WonderWerks, released under the same MIT License. See [LICENSE](LICENSE).
