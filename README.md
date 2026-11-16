# PiScout-AV

A pocket network port identifier for AV technicians. Plug it into a wall jack or switch port and the e-paper screen shows which switch and port you're on, the VLAN, and whether that network can reach the internet. That's the "is this drop live and on the right VLAN?" question you ask before blaming the DSP, codec or control processor.

It runs on a Raspberry Pi Zero 2 W with a Waveshare 2.13" e-paper display. It's powered by PoE or a USB power bank.

> **Fork notice:** PiScout-AV is a modified version of **[RaspberryFluke](https://github.com/MKWB/RaspberryFluke)** by MKWB, which is MIT-licensed. The same author's newer project is **[PiScout](https://github.com/MKWB/PiScout)**. The original commit history is kept in this repo. See [Credits & licenses](#credits--licenses).

---

## Features

**Screen 1 – Switch info**, learned from LLDP or CDP:

| Line | Shows |
|---|---|
| `SW:` | Switch name. Shows `N/A` if the switch has no system name set. |
| `IP:` | Switch management IP |
| `PORT:` | Switch port, shortened (`GigabitEthernet1/0/24` → `Gi1/0/24`) |
| `VLAN:` / `VOICE:` | Access (native) VLAN and voice VLAN (`N/A` if the switch doesn't advertise one) |
| `MODEL:` | Switch model, taken from the switch's system description |

**Screen 2 – Diagnostics**, refreshed every 60 s and immediately when the switch info changes:

| Line | Shows |
|---|---|
| `SW MAC:` | Switch chassis MAC |
| `MY IP:` | The unit's DHCP address on the wired port, or `NO DHCP` |
| `GW:` | The wired network's gateway, with `OK`/`FAIL` for a ping to it |
| `WAN:` | `PASS`/`FAIL`: ping to 8.8.8.8 |
| `DNS:` | `PASS`/`FAIL`: resolves google.com using the wired network's own DNS server |

**Everything on the screen describes the wired port.** Even when the unit is also on Wi-Fi, the checks are forced out of `eth0`, so Wi-Fi can never make a dead port look healthy.

**Behavior:**
- Boot splash, **HAVE YOU TRIED TURNING IT OFF AND ON AGAIN?**, for 5 s. Then an animated `Loading...` screen while it waits for the switch. It shows `NO NEIGHBOR` if nothing is heard within 3 minutes.
- Switches between the two screens every 20 s. Screen changes don't flash; a full refresh happens about every 15 minutes to clear ghosting.
- **Listen-only:** it never sends LLDP/CDP. The only traffic it creates is normal DHCP, ping and DNS.
- Starts at boot as a hardened systemd service.

---

## Materials

| Qty | Part | Source / SKU | Notes |
|---|---|---|---|
| 1 | Raspberry Pi Zero 2 W **with 40-pin header** | Any Raspberry Pi reseller | The display plugs into the GPIO header. Buy a version with the header already soldered on, or solder a 2×20 male header yourself. |
| 1 | Waveshare **2.13" e-Paper HAT+** (250×122) | [Waveshare SKU 27467](https://www.waveshare.com/2.13inch-e-paper-hat-plus.htm) | Uses the V4 driver; the version sticker is on the back. |
| 1 | Waveshare **PoE Ethernet / USB HUB BOX** | [Waveshare SKU 20895](https://www.waveshare.com/product/raspberry-pi/boards-kits/raspberry-pi-zero-2-w-cat/poe-eth-usb-hub-box.htm) | ABS case plus a hub board that connects to the Pi by pogo pins. Adds 802.3af PoE, Ethernet and 3× USB. Pi not included. The stock lid doesn't fit over the display. |
| 1 | microSD card, 8 GB or larger | Any | |

**You'll also need:**
- A PC with [Raspberry Pi Imager](https://www.raspberrypi.com/software/) and a microSD card reader.
- An **802.3af PoE** switch port or PoE injector. For bench use, a USB power supply into the Pi works instead.
- A 2.4 GHz Wi-Fi network or phone hotspot with internet access during setup.



---

## Install

You need **Raspberry Pi OS Lite (64-bit)**, based on Debian 13 "trixie", and internet access on the Pi during setup.

### 1. Flash the card

In **Raspberry Pi Imager**, choose *Raspberry Pi Zero 2 W* → *Raspberry Pi OS Lite (64-bit)*, then open the customisation settings and set:
- **Hostname:** `piscout-av`
- **Username and password**
- **Enable SSH**
- **Wi-Fi and Wi-Fi country.** The Pi downloads packages and code during setup. Wi-Fi is the easiest way to get it online, and it's handy later for managing the unit while the wired port is in use.

> The Pi Zero 2 W is **2.4 GHz only**. If you use a phone hotspot, set it to 2.4 GHz. On an iPhone, turn on *Maximize Compatibility*.

Boot the Pi and connect:

```bash
ssh <user>@piscout-av.local
```

If `.local` doesn't resolve, use the Pi's IP address. Forgot Wi-Fi? See [Troubleshooting](#troubleshooting).

### 2. Install packages

```bash
sudo apt update && sudo apt full-upgrade -y
```

```bash
sudo apt install -y git lldpd python3 python3-pil python3-spidev python3-gpiozero python3-lgpio fonts-dejavu-core
```

If `apt` complains `Not live until ...`, the Pi's clock is wrong. See [Troubleshooting](#troubleshooting).

### 3. Configure the Pi

Enable SPI, which the display needs:

```bash
sudo raspi-config nonint do_spi 0
```

Make lldpd listen-only (`-r`) and accept CDP (`-c`):

```bash
echo 'DAEMON_ARGS="-r -c"' | sudo tee /etc/default/lldpd
```

Let the Pi's own internet traffic (updates) prefer Wi-Fi over the wired port. The on-screen checks still test the wired port.

```bash
sudo nmcli connection modify "$(nmcli -g GENERAL.CONNECTION device show eth0)" ipv4.route-metric 700 ipv6.route-metric 700
```

```bash
sudo reboot
```

### 4. Install PiScout-AV

```bash
sudo mkdir -p /opt/piscout-av && sudo chown $USER: /opt/piscout-av
```

```bash
git clone https://github.com/WonderWerks/PiScout-AV.git /opt/piscout-av
```

```bash
sudo cp /opt/piscout-av/piscout-av.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now piscout-av.service
```

### 5. Check it's running

Plug the wired port into a switch, then watch the log:

```bash
journalctl -u piscout-av.service -f
```

Within about 30 s you should see a `Data update: SW=... PORT=... VLAN=...` line, and the screen switches to the switch info. Press `Ctrl+C` to stop watching; the service keeps running.

---

## Updating

```bash
git -C /opt/piscout-av pull && sudo systemctl restart piscout-av.service
```

If `piscout-av.service` changed in the update, reinstall it first:

```bash
sudo cp /opt/piscout-av/piscout-av.service /etc/systemd/system/ && sudo systemctl daemon-reload
```

---

## Configuration

The settings are at the top of `piscout_av.py`. Restart the service after changing them.

| Setting | Default | Purpose |
|---|---|---|
| `IFACE` | `eth0` | Wired port to test |
| `NO_NEIGHBOR_TIMEOUT_SECONDS` | `180` | Wait before showing `NO NEIGHBOR` |
| `SCREEN_ROTATION_INTERVAL_SECONDS` | `20` | Time on each screen |
| `SPLASH_TEXT`, `SPLASH_SECONDS` | see file, `5` | Boot splash message and how long it shows |
| `DIAG_POLL_INTERVAL_SECONDS` | `60` | How often the diagnostics re-run |
| `PARTIAL_REFRESH_LIMIT` | `45` | Screen changes between full (flashing) refreshes |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Stuck on `Loading...` / `NO NEIGHBOR` | Run `sudo lldpctl`. If it shows nothing, the switch isn't sending LLDP/CDP on that port. If it shows a neighbor, check that `/etc/default/lldpd` contains `DAEMON_ARGS="-r -c"` (step 3). |
| `SW: N/A` but other lines are filled | The switch has no system name set. Name it in the switch's settings. |
| `IP: N/A` on screen 1 | The switch doesn't advertise a management address. This is harmless. |
| `MY IP: NO DHCP` | No DHCP on this port or VLAN, or a bad cable or port. |
| `WAN: FAIL` but `DNS: PASS` | Ping is blocked upstream. This is common on corporate networks. |
| Blank screen | Run `journalctl -u piscout-av.service -n 50`. Check that SPI is on (`ls /dev/spidev0.0`). |
| `apt` / `git pull` fail with Wi-Fi connected | Run the route-metric command in step 3, then reboot. |
| Wi-Fi didn't reconnect after a reboot | Phone hotspots often sleep. Wake the hotspot, then run `sudo nmcli connection up "<your-SSID>"`. |

**Add Wi-Fi after flashing.** Change `US` to your country code. The last command asks for the Wi-Fi password.

```bash
sudo raspi-config nonint do_wifi_country US
```

```bash
sudo rfkill unblock wifi; sudo nmcli radio wifi on
```

```bash
sudo nmcli --ask device wifi connect "<your-SSID>"
```

**Fix the clock** (`apt` says `Not live until ...`). The Pi has no clock battery. If it can't reach a time server, set the time from a web server instead:

```bash
sudo date -s "$(curl -sI http://deb.debian.org | grep -i '^date:' | cut -d' ' -f2-)"
```

---

## Project layout

```text
piscout_av.py         main script: LLDP/CDP polling, diagnostics, display
piscout-av.service    systemd unit
waveshare_epd/        Waveshare driver files for the 2.13" HAT+ (V4)
Images/               build photos from the original RaspberryFluke project
CHANGELOG.md          changes relative to upstream RaspberryFluke
```

---

## Future ideas

Not planned on a schedule:
- 3D-printed lid for the PoE-ETH-USB-HUB-BOX that clears the display
- Web UI over Wi-Fi and Ethernet: full neighbor details, Pi health, Save-to-log and Reset buttons
- Wi-Fi hotspot fallback when no known Wi-Fi is in range, with an off switch
- Passive listeners: IGMP querier, STP root bridge, PTP grandmaster, mDNS/Dante devices

---

## Credits & licenses

- **RaspberryFluke**, © MKWB (𝕄ᶜᏦ𝘦ɴɴ𝒶), MIT License. This is the original project the fork is based on: <https://github.com/MKWB/RaspberryFluke>
- **PiScout** by the same author is its successor: <https://github.com/MKWB/PiScout>
- **Waveshare e-Paper drivers** (`waveshare_epd/`), © Waveshare, MIT-style license in each file header: <https://github.com/waveshare/e-Paper>
- PiScout-AV modifications © 2026 WonderWerks, released under the same MIT License. See [LICENSE](LICENSE).
