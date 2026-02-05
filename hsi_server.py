from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup
import threading
import time
from datetime import datetime
import socket

# ────────────────────────────────────────────────
# mDNS / Zeroconf advertisement (for auto-discovery)
# ────────────────────────────────────────────────
try:
    from zeroconf import ServiceInfo, Zeroconf
except ImportError:
    print("zeroconf not installed → run: pip install zeroconf")
    Zeroconf = ServiceInfo = None

def get_lan_ip():
    """Get the local network IP (not 127.0.0.1)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def advertise_mdns():
    if not Zeroconf:
        print("mDNS disabled (zeroconf library missing)")
        return
    zeroconf = Zeroconf()
    my_ip = get_lan_ip()
    info = ServiceInfo(
        "_hsi._tcp.local.",
        "HSI Futures Server._hsi._tcp.local.",
        addresses=[socket.inet_aton(my_ip)],
        port=8080,
        properties={'path': '/hsi'},
        server="hsi-server.local."
    )
    print(f"mDNS advertising: hsi-server.local :8080 (IP: {my_ip})")
    zeroconf.register_service(info)
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("Unregistering mDNS service...")
        zeroconf.unregister_service(info)
        zeroconf.close()

# Start mDNS in background thread
if Zeroconf:
    threading.Thread(target=advertise_mdns, daemon=True).start()

# ────────────────────────────────────────────────
# Flask + scraping logic
# ────────────────────────────────────────────────
app = Flask(__name__)

latest_data = {}
last_update_str = "Not yet fetched"

# Cache last successful parsed data
last_valid_hsi = None
last_valid_hhi = None

def safe_float(value, fallback=None):
    """Safely convert string to float, return fallback on failure or N/A"""
    if not value:
        return fallback
    cleaned = value.replace(',', '').strip()
    if cleaned in ('N/A', '-', '--', ''):
        return fallback
    try:
        return float(cleaned)
    except ValueError:
        print(f"  → safe_float failed on: '{value}'")
        return fallback

def fetch_hsi_futures():
    global last_update_str, last_valid_hsi
    url = "https://www.aastocks.com/en/stocks/market/bmpfutures.aspx"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Request error for HSI: {e}")
        return

    soup = BeautifulSoup(response.text, "html.parser")

    table = None
    header_keywords = ["Futures", "Last", "Chg", "Chg%", "Open", "Day Range"]
    for tbl in soup.find_all("table"):
        table_text = tbl.get_text(separator=" ", strip=True)
        if all(kw in table_text for kw in header_keywords):
            table = tbl
            print("Detected futures table for HSI")
            break

    if not table:
        print("No futures table found for HSI")
        return

    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 8:
            continue
        texts = [c.get_text(strip=True) for c in cells]
        if texts and "HANG SENG INDEX Futures" in texts[0]:
            try:
                current     = safe_float(texts[1])
                change      = safe_float(texts[2])
                change_pct  = safe_float(texts[3].rstrip("%"))
                open_val    = safe_float(texts[6])
                low, high   = None, None
                if "-" in texts[7]:
                    parts = [p.strip().replace(",", "") for p in texts[7].split("-")]
                    if len(parts) == 2:
                        low  = safe_float(parts[0])
                        high = safe_float(parts[1])

                if current is None:
                    print("HSI current price is N/A → skipping update")
                    return

                last_close_approx = round(current - (change or 0), 2)

                update_elem = soup.find(string=lambda s: s and "Last Update" in s)
                update_time = update_elem.strip() if update_elem else datetime.now().strftime("%Y/%m/%d %H:%M")

                data = {
                    "last_close": last_close_approx,
                    "open":       open_val or current,
                    "high":       high or current,
                    "low":        low or current,
                    "current":    current,
                    "change":     change or 0.0,
                    "change_pct": change_pct or 0.0,
                    "timestamp":  int(time.time())
                }

                latest_data["HSI"] = data
                last_valid_hsi = data
                last_update_str = update_time

                print(f"HSI Updated → {current} Chg: {change:+.2f} ({change_pct:.3f}%) {update_time}")

            except Exception as e:
                print(f"Parse error for HSI: {e}")
            break

def fetch_hhi_futures():
    global last_update_str, last_valid_hhi
    url = "https://www.aastocks.com/en/stocks/market/bmpfutures.aspx?future=200200"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Request error for HHI: {e}")
        return

    soup = BeautifulSoup(response.text, "html.parser")

    table = None
    header_keywords = ["Futures", "Last", "Chg", "Chg%", "Open", "Day Range"]
    for tbl in soup.find_all("table"):
        table_text = tbl.get_text(separator=" ", strip=True)
        if all(kw in table_text for kw in header_keywords):
            table = tbl
            print("Detected futures table for HHI")
            break

    if not table:
        print("No futures table found for HHI")
        return

    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 8:
            continue
        texts = [c.get_text(strip=True) for c in cells]
        if texts and "H-SHARES INDEX Futures" in texts[0]:
            try:
                current     = safe_float(texts[1])
                change      = safe_float(texts[2])
                change_pct  = safe_float(texts[3].rstrip("%"))
                open_val    = safe_float(texts[6])
                low, high   = None, None
                if "-" in texts[7]:
                    parts = [p.strip().replace(",", "") for p in texts[7].split("-")]
                    if len(parts) == 2:
                        low  = safe_float(parts[0])
                        high = safe_float(parts[1])

                if current is None:
                    print("HHI current price is N/A → skipping update")
                    return

                last_close_approx = round(current - (change or 0), 2)

                update_elem = soup.find(string=lambda s: s and "Last Update" in s)
                update_time = update_elem.strip() if update_elem else datetime.now().strftime("%Y/%m/%d %H:%M")

                data = {
                    "last_close": last_close_approx,
                    "open":       open_val or current,
                    "high":       high or current,
                    "low":        low or current,
                    "current":    current,
                    "change":     change or 0.0,
                    "change_pct": change_pct or 0.0,
                    "timestamp":  int(time.time())
                }

                latest_data["HHI"] = data
                last_valid_hhi = data
                last_update_str = update_time

                print(f"HHI Updated → {current} Chg: {change:+.2f} ({change_pct:.3f}%) {update_time}")

            except Exception as e:
                print(f"Parse error for HHI: {e}")
            break

@app.route('/hsi')
def get_hsi():
    # Return combined HSI + HHI if available
    response = {}
    if "HSI" in latest_data:
        response["HSI"] = latest_data["HSI"]
    if "HHI" in latest_data:
        response["HHI"] = latest_data["HHI"]
    if not response:
        return jsonify({"error": "No data available yet"}), 503
    return jsonify(response)

def background_updater():
    while True:
        fetch_hsi_futures()
        fetch_hhi_futures()
        time.sleep(10)  # adjust to 30–60 if rate-limited

if __name__ == '__main__':
    print("HSI & HHI Futures Server starting...")
    print("Local: http://127.0.0.1:8080/hsi")
    print("Network: http://<your-ip>:8080/hsi")
    print("mDNS: http://hsi-server.local:8080/hsi (if client supports zeroconf)")
    print("Data updates every 10 seconds")

    threading.Thread(target=background_updater, daemon=True).start()

    # Run on all interfaces

    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)
