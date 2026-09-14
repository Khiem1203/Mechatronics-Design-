# ============================================================
#  GP2Y0A02YK0F + ESP32  -  Realtime Voltage Plotter
# ------------------------------------------------------------
#  Doc du lieu tu ESP32 qua cong Serial (dinh dang CSV:
#     Time(ms),ADC,Voltage(V)
#  ) va ve bieu do line chart dien ap theo thoi gian thuc.
#
#  Chay:
#     pip install -r requirements.txt
#     python plot_voltage.py
# ============================================================

import time
import csv
import bisect
import threading
from collections import deque

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    raise SystemExit(
        "Thieu thu vien 'pyserial'. Cai bang:  pip install pyserial matplotlib"
    )

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.animation import FuncAnimation


# ----------------------------- Bang mau (dark theme) -----------------------------
BG      = "#1e1e2e"
PANEL   = "#282a3a"
FG      = "#e6e6e6"
MUTED   = "#9aa0b4"
ACCENT  = "#4fc3f7"   # mau duong bieu do
GREEN   = "#8bc34a"
GRID    = "#3a3b4f"
RED     = "#ef5350"

BUF_MAXLEN = 200_000   # so mau toi da giu trong bo dem ve


# ============================================================
#  Luong doc Serial (chay nen)
# ============================================================
class SerialReader(threading.Thread):
    def __init__(self, port, baud, on_sample, on_error):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.on_sample = on_sample      # callback(esp_ms, adc, volt) - chay o thread nay
        self.on_error = on_error        # callback(msg)
        self._stop = threading.Event()
        self.ser = None

    def run(self):
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=1)
        except Exception as e:
            self.on_error(f"Khong mo duoc {self.port}: {e}")
            return

        # ESP32 thuong reset khi mo cong -> cho on dinh roi xoa bo dem
        time.sleep(2.0)
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass

        while not self._stop.is_set():
            try:
                raw = self.ser.readline()
            except Exception as e:
                self.on_error(f"Loi doc serial: {e}")
                break

            if not raw:
                continue

            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            parts = line.split(",")
            if len(parts) != 3:
                continue    # bo qua dong banner / header

            try:
                esp_ms = int(parts[0])
                adc = int(parts[1])
                volt = float(parts[2])
            except ValueError:
                continue    # bo qua dong khong phai so

            self.on_sample(esp_ms, adc, volt)

        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass

    def stop(self):
        self._stop.set()


# ============================================================
#  Ung dung chinh
# ============================================================
class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=10)
        self.master = master
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # --- trang thai / bo dem ---
        self.lock = threading.Lock()
        self.reader = None
        self.t0 = None
        self.paused = False
        self.buf_t = deque(maxlen=BUF_MAXLEN)   # thoi gian (giay) tinh tu luc bat dau
        self.buf_v = deque(maxlen=BUF_MAXLEN)   # dien ap (V)
        self.records = []                        # (esp_ms, adc, volt, elapsed_s) - de xuat CSV
        self.latest = None                       # (esp_ms, adc, volt)

        # --- bien UI ---
        self.port_var   = tk.StringVar()
        self.baud_var   = tk.StringVar(value="115200")
        self.window_var = tk.IntVar(value=30)          # be rong cua so thoi gian (giay)
        self.auto_var   = tk.BooleanVar(value=True)    # tu dong scale truc Y
        self.ymin_var   = tk.DoubleVar(value=0.0)
        self.ymax_var   = tk.DoubleVar(value=3.3)

        self._build_style()
        self._build_controls()
        self._build_plot()
        self._build_statusbar()

        self.refresh_ports()

        self.ani = FuncAnimation(
            self.fig, self._update_plot, interval=80,
            blit=False, cache_frame_data=False,
        )
        master.protocol("WM_DELETE_WINDOW", self._on_close)

    # ----------------------------------------------------- style
    def _build_style(self):
        self.master.configure(bg=BG)
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=BG, foreground=FG,
                     fieldbackground=PANEL, font=("Segoe UI", 10))
        st.configure("TButton", padding=(10, 6), background=PANEL, foreground=FG)
        st.map("TButton",
               background=[("active", ACCENT), ("disabled", "#33344a")],
               foreground=[("active", "#0d0d0d")])
        st.configure("Accent.TButton", background=ACCENT, foreground="#0d0d0d")
        st.map("Accent.TButton", background=[("active", "#7fd6fb")])
        st.configure("Stop.TButton", background=RED, foreground="#0d0d0d")
        st.configure("TLabelframe", background=BG, bordercolor=GRID)
        st.configure("TLabelframe.Label", background=BG, foreground=ACCENT,
                     font=("Segoe UI", 10, "bold"))
        st.configure("TCheckbutton", background=BG, foreground=FG)
        st.map("TCheckbutton", background=[("active", BG)])
        st.configure("Value.TLabel", font=("Consolas", 30, "bold"),
                     foreground=GREEN, background=BG)
        st.configure("Unit.TLabel", font=("Segoe UI", 12),
                     foreground=MUTED, background=BG)
        st.configure("Stat.TLabel", font=("Consolas", 11),
                     foreground=FG, background=BG)
        st.configure("StatKey.TLabel", font=("Segoe UI", 10),
                     foreground=MUTED, background=BG)
        st.configure("Status.TLabel", background=PANEL, foreground=MUTED,
                     font=("Segoe UI", 9))

    # ----------------------------------------------------- thanh dieu khien
    def _build_controls(self):
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        # --- nhom Ket noi ---
        conn = ttk.Labelframe(bar, text="Ket noi", padding=8)
        conn.pack(side="left", fill="y")

        ttk.Label(conn, text="Cong").grid(row=0, column=0, padx=(0, 4))
        self.cbo_port = ttk.Combobox(conn, textvariable=self.port_var,
                                     width=14, state="readonly")
        self.cbo_port.grid(row=0, column=1, padx=(0, 4))

        ttk.Button(conn, text="↻", width=3,
                   command=self.refresh_ports).grid(row=0, column=2, padx=(0, 8))

        ttk.Label(conn, text="Baud").grid(row=0, column=3, padx=(0, 4))
        ttk.Combobox(conn, textvariable=self.baud_var, width=9,
                     values=("9600", "19200", "38400", "57600", "115200", "230400"),
                     ).grid(row=0, column=4, padx=(0, 8))

        self.btn_connect = ttk.Button(conn, text="Ket noi", style="Accent.TButton",
                                      command=self.toggle_connect)
        self.btn_connect.grid(row=0, column=5)

        # --- nhom Dieu khien ---
        ctrl = ttk.Labelframe(bar, text="Dieu khien", padding=8)
        ctrl.pack(side="left", fill="y", padx=(8, 0))

        self.btn_pause = ttk.Button(ctrl, text="Tam dung", command=self.toggle_pause)
        self.btn_pause.pack(side="left")
        ttk.Button(ctrl, text="Xoa", command=self.clear_data).pack(side="left", padx=(6, 0))

        # --- nhom Hien thi ---
        disp = ttk.Labelframe(bar, text="Hien thi", padding=8)
        disp.pack(side="left", fill="y", padx=(8, 0))

        ttk.Label(disp, text="Cua so (s)").grid(row=0, column=0, padx=(0, 4))
        ttk.Spinbox(disp, from_=5, to=600, increment=5, width=6,
                    textvariable=self.window_var).grid(row=0, column=1, padx=(0, 8))

        ttk.Checkbutton(disp, text="Tu scale Y", variable=self.auto_var,
                        command=self._sync_yfields).grid(row=0, column=2, padx=(0, 8))

        ttk.Label(disp, text="Ymin").grid(row=0, column=3, padx=(0, 3))
        self.ent_ymin = ttk.Entry(disp, textvariable=self.ymin_var, width=6)
        self.ent_ymin.grid(row=0, column=4, padx=(0, 6))
        ttk.Label(disp, text="Ymax").grid(row=0, column=5, padx=(0, 3))
        self.ent_ymax = ttk.Entry(disp, textvariable=self.ymax_var, width=6)
        self.ent_ymax.grid(row=0, column=6)

        # --- nhom Du lieu ---
        data = ttk.Labelframe(bar, text="Du lieu", padding=8)
        data.pack(side="left", fill="y", padx=(8, 0))
        ttk.Button(data, text="Xuat CSV", command=self.export_csv).pack(side="left")
        ttk.Button(data, text="Luu anh", command=self.save_png).pack(side="left", padx=(6, 0))

        self._sync_yfields()

    # ----------------------------------------------------- vung bieu do + sidebar
    def _build_plot(self):
        center = ttk.Frame(self)
        center.grid(row=1, column=0, sticky="nsew")
        center.columnconfigure(0, weight=1)
        center.rowconfigure(0, weight=1)

        self.fig = Figure(figsize=(9, 5), dpi=100, facecolor=BG)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor(PANEL)
        self.ax.set_title("Dien ap GP2Y0A02YK0F theo thoi gian thuc",
                          color=FG, fontsize=12, pad=12)
        self.ax.set_xlabel("Thoi gian (s)", color=MUTED)
        self.ax.set_ylabel("Dien ap (V)", color=MUTED)
        self.ax.tick_params(colors=MUTED)
        for spine in self.ax.spines.values():
            spine.set_color(GRID)
        self.ax.grid(True, color=GRID, linewidth=0.6, alpha=0.7)

        (self.line,) = self.ax.plot([], [], color=ACCENT, linewidth=1.8,
                                    antialiased=True)
        self.pt = self.ax.scatter([], [], s=36, color=GREEN, zorder=5)
        self.fig.tight_layout()

        self.canvas = FigureCanvasTkAgg(self.fig, master=center)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        tb_frame = ttk.Frame(center)
        tb_frame.grid(row=1, column=0, sticky="ew")
        tb = NavigationToolbar2Tk(self.canvas, tb_frame, pack_toolbar=False)
        tb.update()
        tb.pack(side="left")
        try:
            tb.configure(background=BG)
            for child in tb.winfo_children():
                child.configure(background=BG)
        except tk.TclError:
            pass

        # --- sidebar thong so ---
        side = ttk.Frame(self, padding=(12, 4))
        side.grid(row=1, column=1, sticky="ns")

        ttk.Label(side, text="DIEN AP HIEN TAI", style="StatKey.TLabel").pack(anchor="w")
        self.lbl_value = ttk.Label(side, text="--", style="Value.TLabel")
        self.lbl_value.pack(anchor="w")
        ttk.Label(side, text="volt", style="Unit.TLabel").pack(anchor="w", pady=(0, 12))

        self.stat_labels = {}
        for key in ("ADC", "Khoang cach uoc tinh", "Min", "Max", "Trung binh",
                    "Toc do mau", "So mau"):
            row = ttk.Frame(side)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=key, style="StatKey.TLabel", width=20,
                      anchor="w").pack(side="left")
            v = ttk.Label(row, text="--", style="Stat.TLabel", anchor="e")
            v.pack(side="right")
            self.stat_labels[key] = v

        self.columnconfigure(1, minsize=280)

    # ----------------------------------------------------- thanh trang thai
    def _build_statusbar(self):
        self.status = ttk.Label(self, text="Chua ket noi.", style="Status.TLabel",
                                anchor="w", padding=6)
        self.status.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    def set_status(self, msg):
        self.status.config(text=msg)

    # =========================================================
    #  Serial
    # =========================================================
    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.cbo_port["values"] = ports
        if ports and self.port_var.get() not in ports:
            self.port_var.set(ports[0])
        if not ports:
            self.set_status("Khong tim thay cong COM nao. Cam ESP32 roi bam ↻.")

    def toggle_connect(self):
        if self.reader is None:
            port = self.port_var.get().strip()
            if not port:
                messagebox.showwarning("Thieu cong", "Hay chon cong COM truoc.")
                return
            try:
                baud = int(self.baud_var.get())
            except ValueError:
                baud = 115200
                self.baud_var.set("115200")

            self.clear_data()
            self.reader = SerialReader(port, baud, self._on_sample, self._on_error)
            self.reader.start()
            self.btn_connect.config(text="Ngat ket noi", style="Stop.TButton")
            self.set_status(f"Dang ket noi {port} @ {baud} baud ... (ESP32 dang reset)")
        else:
            self.reader.stop()
            self.reader = None
            self.btn_connect.config(text="Ket noi", style="Accent.TButton")
            self.set_status("Da ngat ket noi.")

    def _on_sample(self, esp_ms, adc, volt):
        # chay trong thread doc serial
        now = time.monotonic()
        with self.lock:
            if self.t0 is None:
                self.t0 = now
            elapsed = now - self.t0
            self.latest = (esp_ms, adc, volt)
            if not self.paused:
                self.buf_t.append(elapsed)
                self.buf_v.append(volt)
                self.records.append((esp_ms, adc, volt, elapsed))

    def _on_error(self, msg):
        self.after(0, lambda: self._handle_error(msg))

    def _handle_error(self, msg):
        if self.reader is not None:
            self.reader.stop()
        self.reader = None
        self.btn_connect.config(text="Ket noi", style="Accent.TButton")
        self.set_status("Loi: " + msg)
        messagebox.showerror("Loi Serial", msg)

    # =========================================================
    #  Nut dieu khien
    # =========================================================
    def toggle_pause(self):
        self.paused = not self.paused
        self.btn_pause.config(text="Tiep tuc" if self.paused else "Tam dung")
        self.set_status("Da tam dung ghi du lieu." if self.paused
                        else "Dang ghi du lieu.")

    def clear_data(self):
        with self.lock:
            self.buf_t.clear()
            self.buf_v.clear()
            self.records.clear()
            self.t0 = None
            self.latest = None
        self.line.set_data([], [])
        self.set_status("Da xoa du lieu.")

    def _sync_yfields(self):
        state = "disabled" if self.auto_var.get() else "normal"
        self.ent_ymin.config(state=state)
        self.ent_ymax.config(state=state)

    def export_csv(self):
        with self.lock:
            rows = list(self.records)
        if not rows:
            messagebox.showinfo("Chua co du lieu", "Chua co mau nao de xuat.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=time.strftime("voltage_%Y%m%d_%H%M%S.csv"))
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["esp_ms", "adc", "voltage_V", "host_elapsed_s"])
                w.writerows(rows)
        except OSError as e:
            messagebox.showerror("Loi ghi file", str(e))
            return
        self.set_status(f"Da xuat {len(rows)} mau -> {path}")

    def save_png(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG", "*.png")],
            initialfile=time.strftime("voltage_%Y%m%d_%H%M%S.png"))
        if not path:
            return
        try:
            self.fig.savefig(path, dpi=150, facecolor=BG)
        except OSError as e:
            messagebox.showerror("Loi luu anh", str(e))
            return
        self.set_status(f"Da luu anh -> {path}")

    # =========================================================
    #  Ve lai bieu do (goi dinh ky boi FuncAnimation)
    # =========================================================
    @staticmethod
    def _estimate_distance_cm(v):
        # Cong thuc gan dung cho GP2Y0A02YK0F (tam do ~20-150 cm)
        if v <= 0.05:
            return None
        return 60.374 * (v ** -1.16)

    def _update_plot(self, _frame):
        with self.lock:
            ts = list(self.buf_t)
            vs = list(self.buf_v)
            latest = self.latest

        window = max(1, int(self.window_var.get()))

        if ts:
            tmax = ts[-1]
            tmin = tmax - window
            i = bisect.bisect_left(ts, tmin)
            xs = ts[i:]
            ys = vs[i:]
            self.line.set_data(xs, ys)
            self.ax.set_xlim(max(0.0, tmin), max(window, tmax))

            if xs:
                self.pt.set_offsets([[xs[-1], ys[-1]]])

            if self.auto_var.get():
                if ys:
                    lo, hi = min(ys), max(ys)
                    pad = max(0.05, (hi - lo) * 0.15)
                    self.ax.set_ylim(lo - pad, hi + pad)
            else:
                try:
                    lo = float(self.ymin_var.get())
                    hi = float(self.ymax_var.get())
                    if hi > lo:
                        self.ax.set_ylim(lo, hi)
                except (tk.TclError, ValueError):
                    pass

        self._update_stats(ts, vs, latest)
        return self.line, self.pt

    def _update_stats(self, ts, vs, latest):
        if latest is not None:
            esp_ms, adc, volt = latest
            self.lbl_value.config(text=f"{volt:5.3f}")
            self.stat_labels["ADC"].config(text=str(adc))
            d = self._estimate_distance_cm(volt)
            self.stat_labels["Khoang cach uoc tinh"].config(
                text=(f"{d:5.1f} cm" if d is not None else "--"))
        if vs:
            self.stat_labels["Min"].config(text=f"{min(vs):.3f} V")
            self.stat_labels["Max"].config(text=f"{max(vs):.3f} V")
            self.stat_labels["Trung binh"].config(text=f"{sum(vs) / len(vs):.3f} V")
            self.stat_labels["So mau"].config(text=str(len(self.records)))
        if len(ts) >= 2:
            span = ts[-1] - ts[0]
            rate = (len(ts) - 1) / span if span > 0 else 0.0
            self.stat_labels["Toc do mau"].config(text=f"{rate:4.1f} Hz")

    # =========================================================
    def _on_close(self):
        try:
            self.ani.event_source.stop()
        except Exception:
            pass
        if self.reader is not None:
            self.reader.stop()
        self.master.destroy()


def main():
    root = tk.Tk()
    root.title("ESP32 - GP2Y0A02YK0F  |  Realtime Voltage Plotter")
    root.geometry("1180x720")
    root.minsize(960, 600)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
