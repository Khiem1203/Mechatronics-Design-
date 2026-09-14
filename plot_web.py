# ============================================================
#  GP2Y0A02YK0F + ESP32  -  Realtime Voltage Plotter (Web UI)
# ------------------------------------------------------------
#  Reads CSV lines from the ESP32 serial port:
#        Time(ms),ADC,Voltage(V)
#  and streams them to a browser dashboard (Server-Sent Events).
#
#  Run:
#        pip install pyserial          (matplotlib NOT needed)
#        python plot_web.py
#  then open   http://127.0.0.1:8000   (opens automatically)
#
#  Only the Python standard library + pyserial are required.
# ============================================================

import os
import sys
import json
import time
import queue
import argparse
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    raise SystemExit(
        "Missing 'pyserial'.  Install with:\n"
        "    " + os.path.basename(sys.executable) + " -m pip install pyserial"
    )

HOST = "127.0.0.1"
PORT = 8000
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


# ============================================================
#  Serial manager  -  one connection, many SSE subscribers
# ============================================================
class SerialManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._ser = None
        self._reader = None
        self._stop = threading.Event()
        self._subs = set()            # set[queue.Queue]
        self.port = None
        self.baud = None
        self.last_error = ""
        self.lines_seen = 0           # raw non-empty lines
        self.samples = 0             # successfully parsed samples

    # ---- subscribers -------------------------------------------------
    def subscribe(self):
        q = queue.Queue(maxsize=2000)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)

    def _broadcast(self, obj):
        dead = []
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(obj)
            except queue.Full:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    # ---- connection ------------------------------------------------
    def status(self):
        return {
            "connected": self._ser is not None and self._ser.is_open,
            "port": self.port,
            "baud": self.baud,
            "last_error": self.last_error,
            "lines_seen": self.lines_seen,
            "samples": self.samples,
        }

    def connect(self, port, baud):
        self.disconnect()
        self.last_error = ""
        self.lines_seen = 0
        self.samples = 0
        try:
            ser = serial.Serial()
            ser.port = port
            ser.baudrate = int(baud)
            ser.timeout = 1
            # Do NOT drive the auto-reset lines: some ESP32 boards otherwise
            # sit held in reset (RTS->EN) and emit nothing. Behave like a
            # plain terminal.
            ser.dtr = False
            ser.rts = False
            ser.open()
        except Exception as e:
            self.last_error = f"Cannot open {port}: {e}"
            raise
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
        self._ser = ser
        self.port = port
        self.baud = int(baud)
        self._stop.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._broadcast({"type": "status", **self.status()})

    def disconnect(self):
        self._stop.set()
        r = self._reader
        if r and r.is_alive():
            r.join(timeout=2)
        self._reader = None
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None
        self._broadcast({"type": "status", **self.status()})

    # ---- reader loop --------------------------------------------
    def _read_loop(self):
        ser = self._ser
        try:
            ser.reset_input_buffer()
        except Exception:
            pass
        self._broadcast({"type": "info", "msg": f"Port {self.port} open @ {self.baud} baud - waiting for data..."})

        opened_at = time.monotonic()
        warned_no_data = False

        while not self._stop.is_set():
            try:
                raw = ser.readline()
            except Exception as e:
                self.last_error = f"Serial read error: {e}"
                self._broadcast({"type": "error", "msg": self.last_error})
                break

            if not raw:
                # readline() timed out (1 s) with no bytes
                if (not warned_no_data and self.lines_seen == 0
                        and time.monotonic() - opened_at > 4):
                    warned_no_data = True
                    self._broadcast({"type": "error", "msg": (
                        "Port is open but NO bytes are arriving. Check: (1) correct "
                        "COM port, (2) baud = 115200, (3) close Arduino IDE / PlatformIO "
                        "Serial Monitor, (4) press the ESP32 EN/RST button.")})
                continue

            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            self.lines_seen += 1
            # Stream the first lines verbatim so the UI can show what the board sends
            if self.lines_seen <= 60:
                self._broadcast({"type": "raw", "line": line})

            parts = line.split(",")
            if len(parts) != 3:
                continue
            try:
                esp_ms = int(parts[0])
                adc = int(parts[1])
                volt = float(parts[2])
            except ValueError:
                continue

            self.samples += 1
            if self.samples == 1:
                self._broadcast({"type": "info", "msg": "Receiving samples."})
            self._broadcast({
                "type": "sample",
                "t": esp_ms,
                "adc": adc,
                "v": volt,
                "ts": time.time(),
            })


MGR = SerialManager()


# ============================================================
#  HTTP handler
# ============================================================
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass                                    # silence default logging

    # ---- helpers -----------------------------------------------
    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        if not os.path.isfile(path):
            self.send_error(404, "Not found")
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript",
            ".css": "text/css",
        }.get(os.path.splitext(path)[1], "application/octet-stream")
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # ---- routing --------------------------------------------------
    def do_GET(self):
        route = self.path.split("?", 1)[0]

        if route == "/":
            return self._send_file(os.path.join(WEB_DIR, "index.html"))

        if route.startswith("/web/"):
            rel = route[len("/web/"):].replace("..", "")
            return self._send_file(os.path.join(WEB_DIR, *rel.split("/")))

        if route == "/api/ports":
            ports = []
            for p in serial.tools.list_ports.comports():
                ports.append({"device": p.device, "desc": p.description})
            return self._send_json({"ports": ports})

        if route == "/api/status":
            return self._send_json(MGR.status())

        if route == "/api/stream":
            return self._stream()

        self.send_error(404, "Not found")

    def do_POST(self):
        route = self.path.split("?", 1)[0]

        if route == "/api/connect":
            body = self._read_body()
            port = (body.get("port") or "").strip()
            baud = body.get("baud") or 115200
            if not port:
                return self._send_json({"ok": False, "error": "No port given"}, 400)
            try:
                MGR.connect(port, baud)
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 500)
            return self._send_json({"ok": True, **MGR.status()})

        if route == "/api/disconnect":
            MGR.disconnect()
            return self._send_json({"ok": True, **MGR.status()})

        self.send_error(404, "Not found")

    # ---- SSE stream ---------------------------------------------
    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        q = MGR.subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            # push current status right away
            self._sse_write({"type": "status", **MGR.status()})
            last_ping = time.time()
            while True:
                try:
                    obj = q.get(timeout=1.0)
                    self._sse_write(obj)
                except queue.Empty:
                    if time.time() - last_ping > 15:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last_ping = time.time()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            MGR.unsubscribe(q)

    def _sse_write(self, obj):
        payload = "data: " + json.dumps(obj) + "\n\n"
        self.wfile.write(payload.encode("utf-8"))
        self.wfile.flush()


def _bind(host, want_port):
    """Try want_port, then a few fallbacks; return a running server."""
    last = None
    for p in [want_port, 8001, 8080, 8123, 8765, 0]:
        try:
            srv = ThreadingHTTPServer((host, p), Handler)
            srv.daemon_threads = True
            return srv
        except OSError as e:
            last = e
            print(f"  port {p} unavailable ({e.strerror or e})")
    raise SystemExit(f"  Could not bind any port: {last}")


def main():
    ap = argparse.ArgumentParser(description="ESP32 realtime voltage plotter (web UI)")
    ap.add_argument("--host", default=HOST, help="bind address (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=PORT, help="port (default 8000)")
    ap.add_argument("--no-browser", action="store_true", help="do not auto-open the browser")
    args = ap.parse_args()

    if not os.path.isdir(WEB_DIR):
        raise SystemExit(f"Missing 'web' folder next to this script: {WEB_DIR}")
    if not os.path.isfile(os.path.join(WEB_DIR, "vendor", "uPlot.iife.min.js")):
        raise SystemExit("Missing web/vendor/uPlot.iife.min.js  (re-download the project files).")

    srv = _bind(args.host, args.port)
    real_port = srv.server_address[1]

    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        if os.environ.get(var):
            print("  NOTE: a system proxy is set (" + var + ").")
            print("        If the page will not load, add 127.0.0.1,localhost to your")
            print("        browser's proxy bypass list, or use a different browser.")
            break

    urls = [f"http://127.0.0.1:{real_port}", f"http://localhost:{real_port}"]
    print("  ------------------------------------------------------------")
    print("   Realtime Voltage Plotter is running.")
    print("   Open ONE of these in your browser (keep this window open):")
    for u in urls:
        print("       " + u)
    print("   Press Ctrl+C here to stop.")
    print("  ------------------------------------------------------------")

    if not args.no_browser:
        try:
            webbrowser.open(urls[0])
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopping ...")
    finally:
        MGR.disconnect()
        srv.shutdown()


if __name__ == "__main__":
    main()
