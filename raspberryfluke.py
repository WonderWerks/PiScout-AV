import subprocess
import time
import threading
import signal
import logging
import re
from PIL import Image, ImageDraw, ImageFont
from waveshare_epd import epd2in13_V3

# ============================================================
# -------------------- CONFIGURATION -------------------------
# ============================================================

# Physical resolution of the Waveshare 2.13" V3 e-paper panel.
DISPLAY_WIDTH = 250
DISPLAY_HEIGHT = 122

# Layout margins for text placement.
LEFT_MARGIN = 10
TOP_MARGIN = 4

# Font sizing rules.
# Five lines must fit vertically, so the base size is intentionally smaller.
BASE_FONT_SIZE = 16
MIN_FONT_SIZE = 10
LINE_SPACING = 2  # Extra pixels between lines.

# Path to system font used for rendering text.
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# The only wired interface on the RaspberryFluke.
IFACE = "eth0"

# -------------------- Polling / Timing ----------------------

# Background polling frequency for LLDP/CDP updates.
POLL_INTERVAL_SECONDS = 1

# Timeout for subprocess calls to prevent hanging indefinitely.
SUBPROCESS_TIMEOUT_SECONDS = 3

# Maximum time to remain on "Loading" before displaying a "NO NEIGHBOR" screen.
# This accounts for slow CDP environments (e.g., 45–90 seconds observed).
NO_NEIGHBOR_TIMEOUT_SECONDS = 180

# Minimum time between display refreshes once monitoring VLAN changes.
# This protects the e-paper panel if VLAN rapidly flaps.
MIN_DISPLAY_UPDATE_INTERVAL_SECONDS = 10

# How long each screen is shown during rotation (seconds).
SCREEN_ROTATION_INTERVAL_SECONDS = 20

# How often the diagnostics thread re-runs pings/DNS (seconds).
DIAG_POLL_INTERVAL_SECONDS = 60

# -------------------- E-Paper Hygiene -----------------------

# After this many partial refreshes, force a full refresh to prevent ghosting.
PARTIAL_REFRESH_LIMIT = 8

# ============================================================
# -------------------- LOGGING -------------------------------
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("raspberryfluke")

# ============================================================
# -------------------- FONT PRELOAD / CACHE ------------------
# ============================================================

# Preload all font sizes once at startup to avoid disk I/O on each render.
FONT_CACHE = {
    s: ImageFont.truetype(FONT_PATH, s)
    for s in range(MIN_FONT_SIZE, BASE_FONT_SIZE + 1)
}

# ============================================================
# -------------------- SHARED STATE --------------------------
# ============================================================

# Shared tuple containing the most recently collected data.
# Format: (switch_name, switch_ip, port_name, vlan_id, voice_vlan_id)
current_data = ("Loading", "...", "...", "...", "...", "...")

# Lock protects access to current_data between threads.
data_lock = threading.Lock()

# Event used to notify the display loop when new data is available.
data_event = threading.Event()

# Event used to signal clean shutdown.
shutdown_event = threading.Event()

# -------------------- Diagnostics State ---------------------

# Shared tuple for diagnostics screen.
# Format: (switch_mac, pi_ip, gw_ip, gw_ping_ok, net_ok, dns_ok)
# None values mean "not yet collected".
current_diag = None

# Lock protects access to current_diag between threads.
diag_lock = threading.Lock()

# ============================================================
# -------------------- UTILITY FUNCTIONS ---------------------
# ============================================================

def run(cmd):
    """
    Execute a subprocess command safely with a timeout.

    Any failure returns an empty string, and errors are logged for diagnostics.
    """
    try:
        return subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        ).decode("utf-8", errors="ignore").strip()
    except subprocess.TimeoutExpired:
        log.warning("Command timeout: %s", cmd)
        return ""
    except FileNotFoundError:
        log.error("Command not found: %s", cmd)
        return ""
    except subprocess.CalledProcessError:
        log.warning("Command failed: %s", cmd)
        return ""
    except Exception:
        log.exception("Unexpected subprocess error: %s", cmd)
        return ""

def clean_hostname(name):
    """
    Remove domain suffix from a hostname.
    Example: switch.domain.local -> switch
    """
    return name.split(".")[0] if "." in name else name

def shorten_interface(intf):
    """
    Shorten long Cisco-style interface names so they fit cleanly on the display.
    """
    replacements = {
        "GigabitEthernet": "Gi",
        "TenGigabitEthernet": "Te",
        "FastEthernet": "Fa",
    }
    for long, short in replacements.items():
        if intf.startswith(long):
            return intf.replace(long, short)
    return intf

def fit_font(draw, text, max_width):
    """
    Select the largest preloaded font size that fits within max_width.
    """
    for size in range(BASE_FONT_SIZE, MIN_FONT_SIZE - 1, -1):
        font = FONT_CACHE[size]
        if draw.textlength(text, font=font) <= max_width:
            return font
    return FONT_CACHE[MIN_FONT_SIZE]

def _first_value_for_keys(kv, keys):
    """
    Return the first non-empty value found in kv for a list of possible keys.
    """
    for k in keys:
        v = kv.get(k, "")
        if v:
            return v
    return ""

def _find_first_match_value(kv, pattern):
    """
    Return the first value whose key matches the given regex pattern.
    """
    rx = re.compile(pattern)
    for k, v in kv.items():
        if rx.search(k) and v:
            return v
    return ""

def _normalize_vlan(v):
    """
    Normalize VLAN values to a simple numeric string when possible.
    """
    v = (v or "").strip()
    if not v:
        return "N/A"

    # Some outputs may include extra words; pull the first integer.
    m = re.search(r"\b(\d{1,4})\b", v)
    if m:
        return m.group(1)

    return v

# ============================================================
# -------------------- DISCOVERY PARSING ---------------------
# ============================================================

def parse_lldp_keyvalue():
    """
    Query lldpctl in keyvalue format and return a dictionary of key/value pairs.
    """
    kv = {}
    out = run(["lldpctl", "-f", "keyvalue"])
    if not out:
        return kv

    for line in out.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        kv[k.strip()] = v.strip()

    return kv

def extract_switch_hostname(kv):
    sw = kv.get(f"lldp.{IFACE}.chassis.name", "")
    sw = clean_hostname(sw) if sw else "N/A"
    return sw

def extract_switch_ip(kv):
    candidates = [
        f"lldp.{IFACE}.chassis.mgmt-ip",
        f"lldp.{IFACE}.chassis.mgmt-ip.0",
        f"lldp.{IFACE}.chassis.mgmt-ip.1",
    ]
    ip = _first_value_for_keys(kv, candidates)

    if not ip:
        ip = _find_first_match_value(kv, rf"^lldp\.{re.escape(IFACE)}\.chassis\.mgmt-ip(\.|$)")

    ip = (ip or "").strip()
    if not ip:
        return "N/A"
    return ip

def extract_switch_mac(kv):
    """
    Extract the switch chassis MAC address from LLDP ChassisID.
    """
    mac = kv.get(f"lldp.{IFACE}.chassis.mac", "")
    return mac.strip() if mac else "N/A"

def extract_switch_model(kv):
    """
    Extract the switch model from SysDescr.
    Takes the first word/token before a space or comma.
    Example: "M4250-26G4F-PoE+ 26x1G ..." -> "M4250-26G4F-PoE+"
    """
    descr = kv.get(f"lldp.{IFACE}.chassis.descr", "").strip()
    if not descr:
        return "¯\\_(ツ)_/¯"
    # Split on space or comma, take first token.
    model = re.split(r"[ ,]", descr)[0]
    return model if model else "¯\\_(ツ)_/¯"

def extract_port(kv):
    port = kv.get(f"lldp.{IFACE}.port.ifname", "") or kv.get(f"lldp.{IFACE}.port.descr", "")
    port = shorten_interface(port) if port else "N/A"
    return port

def extract_native_vlan(kv):
    vlan = kv.get(f"lldp.{IFACE}.vlan.vlan-id", "") or ""
    return _normalize_vlan(vlan)

def extract_voice_vlan(kv):
    v = _find_first_match_value(
        kv,
        rf"^lldp\.{re.escape(IFACE)}\..*med\.policy.*voice.*vlan"
    )
    if not v:
        v = _find_first_match_value(
            kv,
            rf"^lldp\.{re.escape(IFACE)}\..*med\.policy.*application.*voice.*vlan"
        )
    if v:
        return _normalize_vlan(v)

    v = _find_first_match_value(
        kv,
        rf"^lldp\.{re.escape(IFACE)}\..*(cdp).*(voice|aux).*(vlan)"
    )
    if not v:
        v = _find_first_match_value(
            kv,
            rf"^lldp\.{re.escape(IFACE)}\..*(voice|aux).*(vlan)"
        )
    if v:
        return _normalize_vlan(v)

    out = run(["lldpctl"])
    if out:
        patterns = [
            r"Voice\s+VLAN\s*:\s*(\d{1,4})",
            r"Auxiliary\s+VLAN\s*:\s*(\d{1,4})",
            r"\bvoice\b.*\bVLAN\b.*?(\d{1,4})",
        ]
        for p in patterns:
            m = re.search(p, out, flags=re.IGNORECASE)
            if m:
                return _normalize_vlan(m.group(1))

    return "N/A"

def get_switch_info():
    """
    Collect switch hostname, switch management IP, port, VLAN, and voice VLAN.
    Returns: (SW, SW_IP, PORT, VLAN, VOICE_VLAN)
    """
    kv = parse_lldp_keyvalue()

    sw = extract_switch_hostname(kv)
    sw_ip = extract_switch_ip(kv)
    port = extract_port(kv)
    vlan = extract_native_vlan(kv)
    voice = extract_voice_vlan(kv)
    model = extract_switch_model(kv)

    return (sw, sw_ip, port, vlan, voice, model)

def is_data_ready(data):
    """
    Determine whether the essential neighbor information is populated.
    """
    sw, _sw_ip, port, vlan, _voice, _model = data
    if sw in ("Loading", "N/A", ""):
        return False
    if port in ("...", "N/A", ""):
        return False
    if vlan in ("...", "N/A", ""):
        return False
    return True

# ============================================================
# -------------------- DIAGNOSTICS ---------------------------
# ============================================================

def get_pi_ip():
    """
    Get the Pi's own IP address on eth0.
    Returns IP string or "NO DHCP".
    """
    out = run(["ip", "-4", "addr", "show", IFACE])
    if out:
        m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", out)
        if m:
            return m.group(1)
    return "NO DHCP"

def get_default_gateway():
    """
    Extract the default gateway IP from the routing table.
    Returns IP string or None.
    """
    out = run(["ip", "route", "show", "default"])
    if out:
        m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", out)
        if m:
            return m.group(1)
    return None

def ping_host(host):
    """
    Ping a host once with a 2-second timeout.
    Returns True if reachable, False otherwise.
    """
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False

def check_dns():
    """
    Attempt to resolve google.com.
    Returns True if DNS resolves, False otherwise.
    """
    try:
        result = subprocess.run(
            ["getent", "hosts", "google.com"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False

def collect_diagnostics(switch_mac):
    """
    Run all diagnostic checks and return a diag tuple.
    Format: (switch_mac, pi_ip, gw_ip, gw_ping_ok, net_ok, dns_ok)
    switch_mac is passed in from LLDP data already collected.
    """
    pi_ip = get_pi_ip()
    gw_ip = get_default_gateway()

    gw_ping_ok = ping_host(gw_ip) if gw_ip else False
    net_ok = ping_host("8.8.8.8")
    dns_ok = check_dns()

    log.info(
        "Diag: MAC=%s IP=%s GW=%s GW_PING=%s NET=%s DNS=%s",
        switch_mac, pi_ip, gw_ip, gw_ping_ok, net_ok, dns_ok
    )

    return (switch_mac, pi_ip, gw_ip or "N/A", gw_ping_ok, net_ok, dns_ok)

# ============================================================
# -------------------- BACKGROUND THREADS --------------------
# ============================================================

def data_collector():
    """
    Continuously poll for updated LLDP/CDP information.
    When data changes, update shared state and signal the display loop.
    """
    global current_data
    last = None

    while not shutdown_event.is_set():
        new_data = get_switch_info()

        with data_lock:
            if new_data != current_data:
                current_data = new_data
                data_event.set()

        if last != new_data:
            log.info("Data update: SW=%s SWIP=%s PORT=%s VLAN=%s VOICE=%s MODEL=%s", *new_data)
            last = new_data

        time.sleep(POLL_INTERVAL_SECONDS)

def diagnostics_collector():
    """
    Periodically collect diagnostic data (pings, DNS, IP).
    Runs independently of the LLDP collector.
    Only starts collecting after a neighbor is seen (to get switch MAC).
    """
    global current_diag

    while not shutdown_event.is_set():
        # Wait until we have a valid neighbor to get the switch MAC.
        with data_lock:
            snap = current_data

        kv = parse_lldp_keyvalue()
        switch_mac = extract_switch_mac(kv)

        diag = collect_diagnostics(switch_mac)

        with diag_lock:
            current_diag = diag

        # Signal display loop that diag data changed.
        data_event.set()

        # Wait for next poll cycle.
        for _ in range(DIAG_POLL_INTERVAL_SECONDS):
            if shutdown_event.is_set():
                break
            time.sleep(1)

# ============================================================
# -------------------- DISPLAY RENDERING ---------------------
# ============================================================

def render_image(data):
    """
    Render screen 1: LLDP switch info.
    """
    image = Image.new("1", (DISPLAY_WIDTH, DISPLAY_HEIGHT), 255)
    draw = ImageDraw.Draw(image)

    lines = [
        f"SW: {data[0]}",
        f"IP: {data[1]}",
        f"PORT: {data[2]}",
        f"VLAN: {data[3]}",
        f"MODEL: {data[5]}",
    ]

    y = TOP_MARGIN
    max_width = DISPLAY_WIDTH - (LEFT_MARGIN * 2)

    for line in lines:
        font = fit_font(draw, line, max_width)
        draw.text((LEFT_MARGIN, y), line, font=font, fill=0)
        y += font.size + LINE_SPACING

    return image.rotate(180)

def render_loading(dot_count):
    """
    Render the loading screen with animated dots (0-3).
    dot_count cycles 0,1,2,3 -> "Loading", "Loading.", "Loading..", "Loading..."
    """
    dots = "." * dot_count
    loading_data = (f"Loading{dots}", "...", "...", "...", "...", "...")
    return render_image(loading_data)

def render_diag(diag):
    """
    Render screen 2: diagnostics.
    Format: (switch_mac, pi_ip, gw_ip, gw_ping_ok, net_ok, dns_ok)
    """
    image = Image.new("1", (DISPLAY_WIDTH, DISPLAY_HEIGHT), 255)
    draw = ImageDraw.Draw(image)

    switch_mac, pi_ip, gw_ip, gw_ping_ok, net_ok, dns_ok = diag

    gw_label = f"GW: {gw_ip}"

    lines = [
        f"SW MAC: {switch_mac}",
        f"MY IP: {pi_ip}",
        gw_label,
        f"WAN: {'PASS' if net_ok else 'FAIL'}",
        f"DNS: {'PASS' if dns_ok else 'FAIL'}",
    ]

    y = TOP_MARGIN
    max_width = DISPLAY_WIDTH - (LEFT_MARGIN * 2)

    for line in lines:
        font = fit_font(draw, line, max_width)
        draw.text((LEFT_MARGIN, y), line, font=font, fill=0)
        y += font.size + LINE_SPACING

    return image.rotate(180)

def render_diag_pending():
    """
    Render screen 2 placeholder while diagnostics haven't run yet.
    """
    image = Image.new("1", (DISPLAY_WIDTH, DISPLAY_HEIGHT), 255)
    draw = ImageDraw.Draw(image)

    lines = [
        "SW MAC: ...",
        "MY IP: ...",
        "GW: checking...",
        "WAN: ...",
        "DNS: ...",
    ]

    y = TOP_MARGIN
    max_width = DISPLAY_WIDTH - (LEFT_MARGIN * 2)

    for line in lines:
        font = fit_font(draw, line, max_width)
        draw.text((LEFT_MARGIN, y), line, font=font, fill=0)
        y += font.size + LINE_SPACING

    return image.rotate(180)

def render_no_neighbor():
    return render_image(("NO NEIGHBOR", "N/A", "N/A", "N/A", "N/A", "N/A"))

# ============================================================
# -------------------- SIGNAL HANDLING -----------------------
# ============================================================

def handle_shutdown(signum, frame):
    log.info("Shutdown requested (signal %s)", signum)
    shutdown_event.set()
    data_event.set()

# ============================================================
# -------------------- MAIN SERVICE LOOP ---------------------
# ============================================================

def main():
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    epd = epd2in13_V3.EPD()

    partial_refresh_count = 0
    last_display_update_mono = 0.0

    first_ready_displayed = False
    no_neighbor_displayed = False
    boot_start_mono = time.monotonic()
    last_displayed_vlan = None
    last_displayed_voice_vlan = None

    # Screen rotation state (only active after first neighbor is displayed).
    current_screen = 0          # 0 = switch info, 1 = diagnostics
    last_rotation_mono = 0.0

    # Loading animation state.
    loading_dot_count = 0
    last_dot_update_mono = time.monotonic()
    DOT_INTERVAL_SECONDS = 0.75

    try:
        # Initial boot screen (full refresh).
        epd.init()
        epd.Clear(0xFF)
        boot_img = render_loading(0)
        epd.display(epd.getbuffer(boot_img))
        log.info("Displayed boot screen (Loading)")

        threading.Thread(target=data_collector, daemon=True).start()
        threading.Thread(target=diagnostics_collector, daemon=True).start()

        while not shutdown_event.is_set():
            data_event.wait(timeout=0.5)
            data_event.clear()

            with data_lock:
                snap = current_data

            with diag_lock:
                diag_snap = current_diag

            now_mono = time.monotonic()

            # ---- LOADING PHASE ----
            if not first_ready_displayed:

                # Animate loading dots.
                if (now_mono - last_dot_update_mono) >= DOT_INTERVAL_SECONDS:
                    loading_dot_count = (loading_dot_count + 1) % 4
                    last_dot_update_mono = now_mono
                    dot_img = render_loading(loading_dot_count)
                    epd.displayPartial(epd.getbuffer(dot_img))

                if is_data_ready(snap):
                    epd.init()
                    epd.Clear(0xFF)
                    img = render_image(snap)
                    epd.display(epd.getbuffer(img))
                    epd.sleep()

                    first_ready_displayed = True
                    no_neighbor_displayed = False
                    last_displayed_vlan = snap[3]
                    last_displayed_voice_vlan = snap[4]
                    partial_refresh_count = 0
                    last_display_update_mono = now_mono
                    last_rotation_mono = now_mono
                    current_screen = 0

                    log.info("First neighbor displayed. Starting rotation.")
                    continue

                if (not no_neighbor_displayed) and ((now_mono - boot_start_mono) >= NO_NEIGHBOR_TIMEOUT_SECONDS):
                    epd.init()
                    epd.Clear(0xFF)
                    img = render_no_neighbor()
                    epd.display(epd.getbuffer(img))
                    epd.sleep()

                    no_neighbor_displayed = True
                    partial_refresh_count = 0
                    last_display_update_mono = now_mono

                    log.warning("No neighbor after %ss; displayed NO NEIGHBOR screen.", NO_NEIGHBOR_TIMEOUT_SECONDS)

                continue

            # ---- ROTATION PHASE (post first-neighbor) ----

            # Check if it's time to rotate screens.
            time_to_rotate = (now_mono - last_rotation_mono) >= SCREEN_ROTATION_INTERVAL_SECONDS

            # Also check if VLAN/VOICE changed (existing behaviour — only on screen 0).
            current_vlan = snap[3]
            current_voice = snap[4]
            vlan_changed = (last_displayed_vlan is not None and current_vlan != last_displayed_vlan)
            voice_changed = (last_displayed_voice_vlan is not None and current_voice != last_displayed_voice_vlan)
            vlan_or_voice_changed = (vlan_changed or voice_changed) and is_data_ready(snap)

            if vlan_or_voice_changed:
                # VLAN/VOICE change: update immediately on screen 0, respecting min interval.
                if (now_mono - last_display_update_mono) >= MIN_DISPLAY_UPDATE_INTERVAL_SECONDS:
                    epd.init()
                    img = render_image(snap)

                    if partial_refresh_count >= PARTIAL_REFRESH_LIMIT:
                        epd.Clear(0xFF)
                        epd.display(epd.getbuffer(img))
                        partial_refresh_count = 0
                        log.info("VLAN/VOICE change: full refresh.")
                    else:
                        try:
                            epd.displayPartial(epd.getbuffer(img))
                            partial_refresh_count += 1
                            log.info("VLAN/VOICE change: partial refresh.")
                        except Exception:
                            epd.Clear(0xFF)
                            epd.display(epd.getbuffer(img))
                            partial_refresh_count = 0
                            log.warning("Partial refresh failed; full refresh used.", exc_info=True)

                    epd.sleep()
                    last_displayed_vlan = current_vlan
                    last_displayed_voice_vlan = current_voice
                    last_display_update_mono = now_mono
                    current_screen = 0
                    last_rotation_mono = now_mono

            elif time_to_rotate:
                # Rotate to next screen.
                current_screen = 1 - current_screen
                last_rotation_mono = now_mono

                epd.init()

                if current_screen == 0:
                    img = render_image(snap)
                    log.info("Rotation: showing switch info screen.")
                else:
                    if diag_snap is not None:
                        img = render_diag(diag_snap)
                        log.info("Rotation: showing diagnostics screen.")
                    else:
                        img = render_diag_pending()
                        log.info("Rotation: showing diagnostics pending screen.")

                epd.display(epd.getbuffer(img))
                epd.sleep()
                partial_refresh_count = 0
                last_display_update_mono = now_mono

        # Clean shutdown.
        try:
            epd.sleep()
        except Exception:
            pass
        log.info("Exited cleanly.")

    except Exception:
        try:
            epd.sleep()
        except Exception:
            pass
        raise

if __name__ == "__main__":
    main()
