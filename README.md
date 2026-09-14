# ESP32 + Sharp GP2Y0A02YK0F — Realtime Distance / Voltage Dashboard

Firmware ESP32 (PlatformIO) đọc cảm biến hồng ngoại Sharp GP2Y0A02YK0F và
đẩy dữ liệu ra Serial dạng CSV. Một web dashboard chạy local (Python, chỉ cần
`pyserial`) đọc cổng COM và stream log **real-time** lên trình duyệt qua
Server-Sent Events.

```
ESP32 ──USB/Serial(115200)──> plot_web.py ──SSE──> http://127.0.0.1:8000
        "Time(ms),ADC,Voltage(V)"
```

## Nội dung repo

| Đường dẫn | Mô tả |
|---|---|
| `src/main.cpp` | Firmware ESP32: đọc ADC GPIO34, in `Time(ms), ADC, Voltage(V)` mỗi 50 ms |
| `platformio.ini` | Cấu hình PlatformIO (board `esp32dev`, monitor 115200, upload 921600) |
| `plot_web.py` | Web server + serial reader, dashboard real-time (khuyên dùng) |
| `web/index.html` | Giao diện dashboard (uPlot) |
| `web/vendor/` | uPlot đã kèm sẵn — chạy được offline, không cần internet |
| `plot_voltage.py` | Bản vẽ real-time bằng matplotlib (cửa sổ desktop, không cần web) |
| `calibration_plot.py` | Script hiệu chuẩn: vẽ V theo 1/L để lấy công thức khoảng cách |

## Đấu nối phần cứng

| GP2Y0A02YK0F | ESP32 |
|---|---|
| VCC | VIN (5V) |
| GND | GND |
| VO  | GPIO34 (ADC1_CH6) |

> GPIO34 là chân input-only, ADC 12-bit (0–4095), attenuation 11 dB (~0–3.3 V).

## Cài đặt

### 1. Clone
```bash
git clone https://github.com/Khiem1203/Mechatronics-Design-.git
cd Mechatronics-Design-
```

### 2. Nạp firmware cho ESP32

Cần [PlatformIO](https://platformio.org/) (extension trong VS Code, hoặc CLI).

```bash
pio run --target upload      # build + nạp
pio device list              # xem ESP32 đang ở cổng COM nào
```

Trong VS Code: mở thư mục này → PlatformIO tự nhận project → bấm **Upload** (mũi tên →).

> Nếu `pio` chưa có: `pip install platformio`.
> Lần build đầu PlatformIO sẽ tải toolchain ESP32 (~vài trăm MB), hơi lâu.

### 3. Chạy web dashboard

```bash
pip install -r requirements.txt
python plot_web.py
```

Trình duyệt tự mở `http://127.0.0.1:8000`. Trên trang web:

1. Chọn cổng COM của ESP32 trong dropdown (bấm **Refresh** nếu chưa thấy).
2. Baud để **115200**.
3. Bấm **Connect** → đồ thị và log chạy real-time.

Tuỳ chọn:
```bash
python plot_web.py --port 8080          # đổi port web
python plot_web.py --host 0.0.0.0       # cho máy khác trong cùng LAN xem
python plot_web.py --no-browser         # không tự mở trình duyệt
```

> `--host 0.0.0.0` sẽ mở dashboard ra toàn mạng LAN. Chỉ dùng khi ở mạng
> tin cậy; bạn bè truy cập bằng `http://<IP-máy-bạn>:8080`.

### 4. (Tuỳ chọn) Bản matplotlib

```bash
python plot_voltage.py
```

## Lỗi thường gặp

| Triệu chứng | Cách xử lý |
|---|---|
| Không thấy cổng COM | Cài driver USB-UART (CP210x hoặc CH340) rồi cắm lại cáp |
| `Cannot open COMx` / Access denied | Đóng Serial Monitor của PlatformIO / Arduino IDE (chỉ 1 chương trình được giữ cổng) |
| Connect được nhưng không có dữ liệu | Kiểm tra baud = 115200, bấm nút **EN/RST** trên ESP32 |
| Điện áp luôn ~0 hoặc bão hoà | Kiểm tra dây VO vào đúng GPIO34, và sensor cấp nguồn 5V (VIN) |
| Đồ thị nhiễu | Bình thường — thêm tụ 10 µF giữa VCC và GND sát sensor |

## Workflow khi làm chung

```bash
git pull                     # lấy thay đổi mới nhất
# ...sửa code...
git add -A
git commit -m "mô tả thay đổi"
git push
```

`.pio/` (thư mục build) và `__pycache__/` đã được gitignore — mỗi máy tự build.
