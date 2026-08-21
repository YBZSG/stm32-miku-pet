# -*- coding: utf-8 -*-
"""
Desktop Pet Monitor for Google Antigravity & Web Control Center
- Pure Neumorphic Web UI (No Emojis, Clean Typography, Dual Soft Shadows)
- Direct Voice Control & Soundboard Playback (VS1053)
- Browser Microphone Voice Speech-to-Text (STT) Recognition
- Auto-tracks Antigravity transcript.jsonl
- Smart Chinese GBK UTF-8 boundary safe truncation
- 4-in-1 Dashboard (AI Monitor, Clock/Weather, Memo Board, Pomodoro)
"""

import os
import re
import sys
import json
import time
import socket
import struct
import zlib
import urllib.request
import threading
import sqlite3
from datetime import datetime
from typing import Optional, List
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

DEFAULT_UDP_PORT = 43210
DEFAULT_HTTP_PORT = 18900

STATE_MAP = {
    "idle": 0, "0": 0,
    "run_right": 1, "run": 1, "1": 1,
    "run_left": 2, "2": 2,
    "wave": 3, "3": 3,
    "jump": 4, "4": 4,
    "failed": 5, "5": 5,
    "waiting": 6, "6": 6,
    "working": 7, "7": 7,
    "review": 8, "8": 8,
    "look_right": 9, "9": 9,
    "look_left": 10, "10": 10
}

STATE_NAMES = {
    0: "待机复位 (IDLE)",
    1: "快步奔跑 (RUN_R)",
    2: "向左奔跑 (RUN_L)",
    3: "挥手问候 (WAVE)",
    4: "开心跳跃 (JUMP)",
    5: "抱头报错 (FAILED)",
    6: "等待输入 (WAITING)",
    7: "全力思考 (WORKING)",
    8: "审查状态 (REVIEW)",
    9: "右盼凝视 (LOOK_R)",
    10: "左顾凝视 (LOOK_L)"
}

VOICE_NAMES = {
    0: "工作中 / 頑張って考えるから、待っててね！",
    1: "等待中 / 次はどんなタスクかな？マスター！",
    2: "报错 / ダメです…エラーが発生したよ",
    3: "完成 / できたよ！完璧に完了しました",
    4: "问候 / こんにちは、私の名前は初音ミクです!"
}


class MQ135Telemetry:
    """Read local sensor measurements printed by the STM32 over CH340."""

    LINE_RE = re.compile(
        r"MQ135 raw=(\d+) mv=(\d+) quality=(\d+) level=([A-Z]+) warmup=([01])"
        r"(?: baseline=(\d+) delta=(-?\d+))?"
    )
    DHT_RE = re.compile(r"DHT valid=1 model=(DHT11) temp10=(-?\d+) hum10=(\d+)")
    DHT_ERROR_RE = re.compile(r"DHT valid=0 status=([A-Z_]+)")
    MPU_RE = re.compile(r"MPU6050 valid=1 ax=(-?\d+) ay=(-?\d+) az=(-?\d+) gx10=(-?\d+) gy10=(-?\d+) gz10=(-?\d+) pitch10=(-?\d+) roll10=(-?\d+) gesture=([A-Z_]+)")
    MODE_RE = re.compile(r"MODE ([1-7])")

    def __init__(self, mode_callback=None):
        self.raw = 0
        self.mv = 0
        self.quality = 0
        self.baseline = 0
        self.delta = 0
        self.level = "OFFLINE"
        self.warmup = True
        self.port = ""
        self.updated_at = 0.0
        self.status = "正在查找 CH340"
        self.last_error = ""
        self.mode_callback = mode_callback
        self.device_mode = 0
        self.mode_updated_at = 0.0
        self.dht_valid = False
        self.dht_model = "DHT11"
        self.dht_temperature10 = 0
        self.dht_humidity10 = 0
        self.dht_updated_at = 0.0
        self.dht_status = "等待 DHT11 数据"
        self.mpu_values = [0] * 8
        self.mpu_gesture = "OFFLINE"
        self.mpu_updated_at = 0.0
        self._lock = threading.Lock()

    def snapshot(self):
        with self._lock:
            online = self.updated_at > 0 and time.time() - self.updated_at < 5.0
            return {
                "raw": self.raw,
                "mv": self.mv,
                "quality": self.quality,
                "baseline": self.baseline,
                "delta": self.delta,
                "level": self.level if online else "OFFLINE",
                "warmup": self.warmup if online else False,
                "online": online,
                "port": self.port,
                "status": "数据正常" if online else self.status,
                "error": self.last_error,
                "device_mode": self.device_mode,
                "mode_age": (time.time() - self.mode_updated_at) if self.mode_updated_at else None,
            }

    def dht_snapshot(self):
        with self._lock:
            online = self.dht_valid and self.dht_updated_at > 0 and time.time() - self.dht_updated_at < 8.0
            return {
                "valid": online,
                "model": self.dht_model,
                "temperature": self.dht_temperature10 / 10.0 if online else None,
                "humidity": self.dht_humidity10 / 10.0 if online else None,
                "updated_at": self.dht_updated_at,
                "port": self.port,
                "status": "数据正常" if online else self.dht_status,
            }

    def mpu_snapshot(self):
        with self._lock:
            online = self.mpu_updated_at > 0 and time.time() - self.mpu_updated_at < 3.0
            v = self.mpu_values
            return {"online": online, "ax": v[0], "ay": v[1], "az": v[2],
                    "gx": v[3] / 10.0, "gy": v[4] / 10.0, "gz": v[5] / 10.0,
                    "pitch": v[6] / 10.0, "roll": v[7] / 10.0,
                    "gesture": self.mpu_gesture if online else "OFFLINE"}

    def _find_ch340(self):
        if not list_ports:
            return None
        for port in list_ports.comports():
            text = f"{port.description} {port.manufacturer or ''}".upper()
            if "CH340" in text or port.vid == 0x1A86:
                return port.device
        return None

    def _run(self):
        while True:
            port_name = self._find_ch340()
            if serial is None:
                with self._lock:
                    self.status = "缺少 pyserial"
                    self.last_error = "请安装 pyserial"
                time.sleep(2.0)
                continue
            if not port_name:
                with self._lock:
                    self.port = ""
                    self.status = "未找到 CH340"
                    self.last_error = ""
                time.sleep(2.0)
                continue
            port = None
            try:
                # Configure control lines before opening.  On some CH340 boards,
                # pyserial's default DTR/RTS transition is wired to MCU reset.
                port = serial.Serial()
                port.port = port_name
                port.baudrate = 115200
                port.timeout = 1.0
                port.dtr = False
                port.rts = False
                port.open()
                with self._lock:
                    self.port = port_name
                    self.status = f"{port_name} 已连接，等待数据"
                    self.last_error = ""
                while True:
                    line = port.readline().decode("ascii", errors="ignore").strip()
                    mode_match = self.MODE_RE.search(line)
                    if mode_match:
                        device_mode = int(mode_match.group(1))
                        with self._lock:
                            self.device_mode = device_mode
                            self.mode_updated_at = time.time()
                        if self.mode_callback:
                            self.mode_callback(device_mode)
                    dht_match = self.DHT_RE.search(line)
                    if dht_match:
                        with self._lock:
                            self.dht_valid = True
                            self.dht_model = dht_match.group(1)
                            self.dht_temperature10 = int(dht_match.group(2))
                            self.dht_humidity10 = int(dht_match.group(3))
                            self.dht_updated_at = time.time()
                            self.dht_status = "数据正常"
                    else:
                        dht_error = self.DHT_ERROR_RE.search(line)
                        if dht_error:
                            with self._lock:
                                self.dht_valid = False
                                self.dht_status = "读取失败，请检查 PB8 接线"
                    mpu_match = self.MPU_RE.search(line)
                    if mpu_match:
                        with self._lock:
                            self.mpu_values = [int(v) for v in mpu_match.groups()[:8]]
                            self.mpu_gesture = mpu_match.group(9)
                            self.mpu_updated_at = time.time()
                    match = self.LINE_RE.search(line)
                    if not match:
                        continue
                    with self._lock:
                        self.raw = int(match.group(1))
                        self.mv = int(match.group(2))
                        self.quality = int(match.group(3))
                        self.level = match.group(4)
                        self.warmup = match.group(5) == "1"
                        self.baseline = int(match.group(6) or 0)
                        self.delta = int(match.group(7) or 0)
                        self.updated_at = time.time()
                        self.status = "数据正常"
                        self.last_error = ""
            except Exception as exc:
                with self._lock:
                    self.port = port_name
                    self.status = f"{port_name} 串口不可用"
                    self.last_error = str(exc)
                time.sleep(2.0)
            finally:
                if port is not None and port.is_open:
                    port.close()

    def start(self):
        threading.Thread(target=self._run, name="mq135-telemetry", daemon=True).start()


def safe_gbk_truncate(text: str, max_bytes: int) -> bytes:
    encoded = b""
    for char in text:
        try:
            char_bytes = char.encode('gbk')
        except UnicodeEncodeError:
            char_bytes = b'?'
        if len(encoded) + len(char_bytes) > max_bytes:
            break
        encoded += char_bytes
    return encoded


def get_local_wlan_ips() -> List[str]:
    ips = []
    try:
        host_info = socket.gethostbyname_ex(socket.gethostname())
        for ip in host_info[2]:
            if ip.startswith("127.") or ip.startswith("169.254.") or ip.startswith("198.18."):
                continue
            ips.append(ip)
    except Exception:
        pass
    if not ips:
        ips = ["192.168.1.85"]
    return ips


class PetDashboardSender:
    def __init__(self, target_ip: Optional[str] = None, port: int = DEFAULT_UDP_PORT):
        self.local_ips = get_local_wlan_ips()
        self.explicit_target = target_ip if (target_ip and target_ip != "255.255.255.255") else None
        self.port = port
        self.session_id = int(time.time()) & 0xFFFFFFFF
        self.sequence_id = 0
        self.current_mode = 1
        self.current_state = 0
        self.total_tokens = 0
        self.remaining_percent = -1
        self.reset_minutes = 0
        self.session_title = "STM32 PET"
        
        self.weather_info = "Sunny +26C"
        self.weather_tip = "Daily Clock"
        
        self.memo_sender = "WEB"
        self.memo_text1 = "Drink water & rest!"
        self.memo_text2 = ""
        
        self.pomo_seconds = 1500
        self.geek_commits = 0
        self.geek_stars = 0
        
        self.manual_lock_until = 0.0
        self._lock = threading.Lock()
        self.mq135 = MQ135Telemetry(self._device_mode_changed)

    def _device_mode_changed(self, mode: int):
        with self._lock:
            self.current_mode = max(1, min(7, mode))
            self.manual_lock_until = 0.0

    def select_mode(self, mode: int):
        mode = max(1, min(7, int(mode)))
        with self._lock:
            self.current_mode = mode
            body = struct.pack("<B53x", mode)
            self._send_raw_payload(7, self.current_state, body, burst=2)

    def _send_raw_payload(self, mode: int, state: int, payload_54bytes: bytes,
                          burst: int = 1, select_display: bool = False):
        self.sequence_id = (self.sequence_id + 1) & 0xFFFFFFFF
        header = struct.pack("<BBBBII", 0xA5, 0x5A, mode, state, self.session_id, self.sequence_id)
        # A frame is 12-byte header + 46-byte body + CRC + CRLF = 64 bytes.
        body = bytearray(payload_54bytes.ljust(46, b'\x00')[:46])
        if select_display:
            body[45] = 0xD7
        payload = header + bytes(body)
        if len(payload) != 58:
            payload = payload.ljust(58, b'\x00')[:58]

        crc = zlib.crc32(payload) & 0xFFFFFFFF
        frame = payload + struct.pack("<I", crc) + b"\r\n"

        if self.explicit_target:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                for _ in range(burst):
                    s.sendto(frame, (self.explicit_target, self.port))
                s.close()
            except Exception:
                pass
            return

        subnets = ["192.168.0.255", "192.168.1.255", "255.255.255.255"]
        for local_ip in self.local_ips:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind((local_ip, 0))
                for _ in range(burst):
                    for target_bcast in subnets:
                        sock.sendto(frame, (target_bcast, self.port))
                sock.close()
            except Exception:
                pass

    def send_ai(self, state: Optional[int] = None, tokens: Optional[int] = None,
                remain_pct: Optional[int] = None, reset_min: Optional[int] = None,
                title: Optional[str] = None, lock_sec: float = 0.0,
                select_display: bool = False):
        with self._lock:
            if lock_sec > 0:
                self.manual_lock_until = time.time() + lock_sec
            if state is not None:
                if lock_sec > 0 or time.time() >= self.manual_lock_until:
                    self.current_state = state
            if tokens is not None: self.total_tokens = tokens
            if remain_pct is not None:
                self.remaining_percent = int(remain_pct) if 0 <= int(remain_pct) <= 100 else -1
            if reset_min is not None: self.reset_minutes = reset_min
            if title is not None and title.strip(): self.session_title = title.strip()

            # One physical LCD row: 32 ASCII pixels/bytes or 16 GBK glyphs.
            title_bytes = safe_gbk_truncate(self.session_title, 30)
            title_padded = title_bytes.ljust(36, b'\x00')
            quota_byte = self.remaining_percent if self.remaining_percent >= 0 else 255
            body = struct.pack("<IBIB36s", self.total_tokens, quota_byte, self.reset_minutes, len(title_bytes), title_padded)
            self._send_raw_payload(1, self.current_state, body,
                                   burst=3 if select_display else (2 if lock_sec > 0 else 1),
                                   select_display=select_display)

    def send_voice(self, voice_id: int, action: Optional[int] = None, lock_sec: float = 8.0):
        with self._lock:
            if lock_sec > 0:
                self.manual_lock_until = time.time() + lock_sec
            if action is None:
                action_map = {0: 7, 1: 6, 2: 5, 3: 0, 4: 3}
                action = action_map.get(voice_id, 3)
            self.current_state = action
            body = struct.pack("<B53x", voice_id)
            self._send_raw_payload(5, self.current_state, body, burst=1)

    def send_weather_clock(self, date_str: str, time_str: str, weather: str, tip: str,
                           state: Optional[int] = None, lock_sec: float = 0.0,
                           select_display: bool = False):
        with self._lock:
            if lock_sec > 0:
                self.manual_lock_until = time.time() + lock_sec
            if state is not None:
                self.current_state = state
            self.weather_info = weather
            self.weather_tip = tip
            d_bytes = date_str.encode('ascii')[:10].ljust(10, b'\x00')
            t_bytes = time_str.encode('ascii')[:8].ljust(8, b'\x00')
            w_bytes = safe_gbk_truncate(weather, 14).ljust(14, b'\x00')
            tip_bytes = safe_gbk_truncate(tip, 14).ljust(14, b'\x00')
            body = struct.pack("<10s8s14s14s4x", d_bytes, t_bytes, w_bytes, tip_bytes)
            self._send_raw_payload(2, self.current_state, body,
                                   burst=3 if select_display else 1,
                                   select_display=select_display)

    def send_memo(self, sender: str, text: str, state: int = 3,
                  lock_sec: float = 30.0, select_display: bool = False):
        with self._lock:
            if lock_sec > 0:
                self.manual_lock_until = time.time() + lock_sec
            self.current_state = state
            self.memo_sender = sender
            
            t1_bytes = safe_gbk_truncate(text, 20)
            consumed = len(t1_bytes.decode('gbk', errors='ignore'))
            rem = text[consumed:]
            t2_bytes = safe_gbk_truncate(rem, 18)
            
            self.memo_text1 = t1_bytes.decode('gbk', errors='ignore')
            self.memo_text2 = t2_bytes.decode('gbk', errors='ignore')
            
            s_bytes = safe_gbk_truncate(sender, 8).ljust(8, b'\x00')
            t1_padded = t1_bytes.ljust(20, b'\x00')
            t2_padded = t2_bytes.ljust(18, b'\x00')
            body = struct.pack("<8s20s18s6x", s_bytes, t1_padded, t2_padded)
            self._send_raw_payload(3, self.current_state, body,
                                   burst=3 if select_display else 2,
                                   select_display=select_display)

    def send_geek(self, pomo_sec: int, commits: int, stars: int, state: int = 7,
                  lock_sec: float = 30.0, select_display: bool = False):
        with self._lock:
            if lock_sec > 0:
                self.manual_lock_until = time.time() + lock_sec
            self.current_state = state
            self.pomo_seconds = pomo_sec
            self.geek_commits = commits
            self.geek_stars = stars
            body = struct.pack("<III34x", pomo_sec, commits, stars)
            self._send_raw_payload(4, self.current_state, body,
                                   burst=3 if select_display else 2,
                                   select_display=select_display)

    def send_air(self, lock_sec: float = 0.0, select_display: bool = False):
        with self._lock:
            if lock_sec > 0:
                self.manual_lock_until = time.time() + lock_sec
            self._send_raw_payload(6, self.current_state, bytes(54),
                                   burst=3 if select_display else 2,
                                   select_display=select_display)

    def send_dht(self, lock_sec: float = 0.0, select_display: bool = False):
        with self._lock:
            if lock_sec > 0:
                self.manual_lock_until = time.time() + lock_sec
            self._send_raw_payload(8, self.current_state, bytes(54),
                                   burst=3 if select_display else 2,
                                   select_display=select_display)

    def send_mpu(self, select_display: bool = False):
        with self._lock:
            self._send_raw_payload(9, self.current_state, bytes(54),
                                   burst=3 if select_display else 2,
                                   select_display=select_display)


class WeatherService:
    def __init__(self):
        self.last_fetch = 0
        self.cached_weather = "Sunny +26C"
        self.cached_tip = "Daily Clock"

    def update_weather(self):
        now = time.time()
        if now - self.last_fetch < 1800 and self.last_fetch != 0:
            return self.cached_weather, self.cached_tip
        try:
            req = urllib.request.Request("https://wttr.in/?format=%C+%t&m", headers={'User-Agent': 'curl/7.68.0'})
            with urllib.request.urlopen(req, timeout=4) as resp:
                raw = resp.read().decode('utf-8').strip()
                clean = re.sub(r'[^\x20-\x7E]', '', raw).strip()
                if clean and not clean.startswith("37.") and not clean.startswith("Unknown"):
                    self.cached_weather = clean[:14]
                    self.last_fetch = now
        except Exception:
            pass
        return self.cached_weather, self.cached_tip


class AntigravityWatcher:
    def __init__(self, sender: PetDashboardSender, weather_svc: WeatherService):
        self.sender = sender
        self.weather_svc = weather_svc
        self.base_dir = os.path.expanduser("~/.gemini/antigravity/brain")
        self.codex_db = os.path.expanduser("~/.codex/state_5.sqlite")
        self.last_active_time = time.time()

    def find_latest_codex_thread(self):
        if not os.path.isfile(self.codex_db):
            return None
        try:
            uri = "file:" + self.codex_db.replace("\\", "/") + "?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=0.2) as db:
                row = db.execute(
                    "SELECT updated_at, tokens_used FROM threads "
                    "WHERE archived=0 AND agent_role IS NULL "
                    "ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
            return row if row else None
        except Exception:
            return None

    def find_latest_transcript(self) -> Optional[str]:
        if not os.path.isdir(self.base_dir): return None
        candidates = []
        try:
            for entry in os.scandir(self.base_dir):
                if entry.is_dir():
                    log_file = os.path.join(entry.path, ".system_generated", "logs", "transcript.jsonl")
                    if os.path.isfile(log_file):
                        try:
                            candidates.append((os.path.getmtime(log_file), log_file))
                        except OSError: pass
        except Exception: return None
        if not candidates: return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def poll(self):
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        if self.sender.current_mode == 2:
            weather, tip = self.weather_svc.update_weather()
            state_val = self.sender.current_state if time.time() < self.sender.manual_lock_until else 0
            self.sender.send_weather_clock(date_str=date_str, time_str=time_str, weather=weather, tip=tip, state=state_val)
            return
        elif self.sender.current_mode in (3, 4, 5, 6, 7):
            return

        if time.time() < self.sender.manual_lock_until:
            return

        log_path = self.find_latest_transcript()
        time_since_mtime = 999.0
        size = 0
        state = 0
        title = "Local AI Task"

        if log_path and os.path.isfile(log_path):
            try:
                mtime = os.path.getmtime(log_path)
                time_since_mtime = time.time() - mtime
                size = os.path.getsize(log_path)
                # Privacy boundary: metadata only. Never open or parse private
                # conversation/transcript contents.
                if time_since_mtime < 8.0:
                    state = 7
                    self.last_active_time = time.time()
            except Exception: pass

        codex = self.find_latest_codex_thread()
        if codex and float(codex[0]) >= (os.path.getmtime(log_path) if log_path else 0):
            title = "Codex Task"
            size = int(codex[1] or 0) * 4
            time_since_mtime = max(0.0, time.time() - float(codex[0]))
            if time_since_mtime < 8.0:
                state = 7

        if state == 0:
            if time_since_mtime < 25.0:
                state = 6  # WAITING (等待指令)
            else:
                state = 0  # IDLE (待机复位)

        # Recheck at the exact send boundary. KEY2 may have changed mode while
        # this poll was reading a large Gemini/Codex transcript or SQLite DB.
        with self.sender._lock:
            still_ai = self.sender.current_mode == 1
            unlocked = time.time() >= self.sender.manual_lock_until
        if not still_ai or not unlocked:
            return
        # Antigravity's local transcript exposes activity but not the account's
        # real quota/reset counters. Use an explicit unavailable sentinel.
        self.sender.send_ai(state=state, tokens=0, remain_pct=-1, reset_min=0, title=title)


HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Miku 桌面宠物控制中心</title>
<style>
  :root {
    --bg: #e0e5ec;
    --card: #e0e5ec;
    --shadow-light: #ffffff;
    --shadow-dark: #b8bcc2;
    --primary: #18aeb5;
    --primary-light: #45cbd0;
    --text-main: #2d3748;
    --text-muted: #718096;
    --text-light: #a0aec0;
  }

  * {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    -webkit-tap-highlight-color: transparent;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }

  body {
    background-color: var(--bg);
    color: var(--text-main);
    padding: 24px 16px;
    max-width: 520px;
    margin: 0 auto;
    min-height: 100vh;
  }

  .header {
    text-align: center;
    margin-bottom: 24px;
    padding: 4px 0;
  }

  .header h1 {
    font-size: 20px;
    font-weight: 700;
    color: var(--primary);
    letter-spacing: 0.5px;
  }

  .header .subtitle {
    font-size: 12px;
    color: var(--text-muted);
    margin-top: 4px;
    font-weight: 500;
    letter-spacing: 0.3px;
  }

  .card {
    background: var(--card);
    border-radius: 20px;
    box-shadow: 8px 8px 16px var(--shadow-dark), -8px -8px 16px var(--shadow-light);
    padding: 20px;
    margin-bottom: 20px;
    border: 0;
  }

  .card-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--primary);
    margin-bottom: 14px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .well {
    background: var(--card);
    border-radius: 14px;
    box-shadow: inset 4px 4px 8px var(--shadow-dark), inset -4px -4px 8px var(--shadow-light);
    padding: 12px 16px;
    margin-bottom: 10px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 13px;
  }

  .well:last-child {
    margin-bottom: 0;
  }

  .well .label {
    color: var(--text-muted);
    font-weight: 500;
  }

  .well .val {
    color: var(--text-main);
    font-weight: 600;
    text-align: right;
    max-width: 65%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .val.highlight {
    color: var(--primary);
  }

  .val.mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }

  .btn-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
  }

  .btn-neu {
    background: var(--card);
    color: var(--text-main);
    border: none;
    border-radius: 14px;
    padding: 13px 8px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 5px 5px 10px var(--shadow-dark), -5px -5px 10px var(--shadow-light);
    transition: all 0.15s ease;
    text-align: center;
    outline: none;
    display: block;
    width: 100%;
  }

  .btn-neu:active {
    box-shadow: inset 3px 3px 6px var(--shadow-dark), inset -3px -3px 6px var(--shadow-light);
    transform: translateY(1px);
  }

  .btn-primary {
    color: var(--primary);
    font-weight: 700;
  }

  .btn-voice {
    text-align: left;
    padding: 12px 14px;
    margin-bottom: 10px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .btn-voice:last-child {
    margin-bottom: 0;
  }

  .btn-voice .v-title {
    font-size: 13px;
    font-weight: 700;
    color: var(--primary);
  }

  .btn-voice .v-sub {
    font-size: 11px;
    color: var(--text-muted);
    margin-top: 2px;
    font-weight: 500;
  }

  .btn-voice .v-tag {
    font-size: 11px;
    color: var(--text-light);
    font-family: monospace;
  }

  .input-neu {
    width: 100%;
    background: var(--card);
    border: none;
    border-radius: 14px;
    padding: 12px 16px;
    font-size: 13px;
    color: var(--text-main);
    box-shadow: inset 4px 4px 8px var(--shadow-dark), inset -4px -4px 8px var(--shadow-light);
    margin-bottom: 12px;
    outline: none;
    transition: all 0.2s ease;
  }

  .input-neu:focus {
    box-shadow: inset 5px 5px 10px var(--shadow-dark), inset -5px -5px 10px var(--shadow-light);
  }

  .mode-row {
    display: flex;
    gap: 12px;
  }

  .mode-row .btn-neu {
    flex: 1;
  }

  .mic-box {
    text-align: center;
    padding: 6px 0;
  }

  .mic-status {
    font-size: 12px;
    color: var(--text-muted);
    margin-top: 10px;
    min-height: 18px;
  }

  .toast {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    background: #2d3748;
    color: #ffffff;
    padding: 10px 22px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 500;
    box-shadow: 0 8px 16px rgba(0,0,0,0.15);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.25s ease;
    z-index: 999;
  }

  .dashboard { width: 100%; }
  .mobile-nav { display: none; }

  /* Same neumorphic language, arranged for a wide desktop. */
  @media (min-width: 800px) {
    body { max-width: 1240px; padding: 34px 30px 56px; }
    .header { text-align: left; padding-left: 4px; margin-bottom: 26px; }
    .header h1 { font-size: 24px; }
    .dashboard { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 22px; align-items: start; }
    .dashboard .card { margin-bottom: 0; min-width: 0; }
    .card-status { grid-column: 1 / span 4; grid-row: 1; }
    .card-air { grid-column: 5 / span 3; grid-row: 1; }
    .card-dht { grid-column: 8 / span 2; grid-row: 1; }
    .card-mpu { grid-column: 10 / span 3; grid-row: 1; }
    .card-voice { grid-column: 1 / span 7; grid-row: 2 / span 2; height: 100%; }
    .card-mic { grid-column: 8 / span 5; grid-row: 2; }
    .card-memo { grid-column: 8 / span 5; grid-row: 3; }
    .card-actions { grid-column: 1 / span 7; grid-row: 4; }
    .card-modes { grid-column: 8 / span 5; grid-row: 4; }
    .mode-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .mode-row .btn-neu:last-child { grid-column: 1 / -1; }
  }

  /* Mobile prioritizes readings and one-hand controls. */
  @media (max-width: 799px) {
    body { padding-bottom: 96px; }
    .dashboard { display: flex; flex-direction: column; }
    .card-status { order: 1; } .card-dht { order: 2; } .card-mpu { order: 3; } .card-air { order: 4; }
    .card-modes { order: 5; } .card-actions { order: 6; } .card-memo { order: 7; }
    .card-mic { order: 8; } .card-voice { order: 9; }
    .mode-row {
      display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px; overflow: visible; padding: 2px;
    }
    .mode-row .btn-neu { min-width: 0; width: 100%; }
    .mode-row .btn-neu:last-child { grid-column: 1 / -1; }
    .mobile-nav {
      display: grid; grid-template-columns: repeat(4, 1fr); position: fixed;
      left: 14px; right: 14px; bottom: max(12px, env(safe-area-inset-bottom));
      padding: 8px; border-radius: 18px; background: var(--card);
      box-shadow: 6px 6px 14px var(--shadow-dark), -4px -4px 12px var(--shadow-light);
      z-index: 80;
    }
    .mobile-nav a { color: var(--text-muted); text-decoration: none; text-align: center; font-size: 11px; font-weight: 600; padding: 6px 2px; }
    .mobile-nav a span { display: block; color: var(--primary); font-size: 16px; margin-bottom: 2px; }
    .toast { bottom: 92px; }
  }

  @media (max-width: 390px) { .btn-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
</head>
<body>

  <div class="header">
    <h1>MIKU PET CONSOLE</h1>
    <div class="subtitle">STM32 桌面宠物控制中心</div>
  </div>

  <main class="dashboard">

  <!-- 1. 状态监控 -->
  <div class="card card-status" id="status-card">
    <div class="card-title">系统状态</div>
    <div class="well">
      <span class="label">动作状态</span>
      <span class="val highlight" id="state-val">待机闲置</span>
    </div>
    <div class="well">
      <span class="label">当前面板</span>
      <span class="val" id="mode-val">AI 监控模式</span>
    </div>
    <div class="well">
      <span class="label">任务标题</span>
      <span class="val" id="title-val">STM32 PET</span>
    </div>
    <div class="well">
      <span class="label">消耗 Tokens</span>
      <span class="val mono" id="token-val">--</span>
    </div>
  </div>

  <!-- 2. MQ135 空气质量 -->
  <div class="card card-air" id="sensor-card">
    <div class="card-title">MQ135 空气质量</div>
    <div class="well">
      <span class="label">传感器状态</span>
      <span class="val highlight" id="air-level">等待串口数据</span>
    </div>
    <div class="well">
      <span class="label">相对空气质量</span>
      <span class="val mono" id="air-quality">--</span>
    </div>
    <div class="well">
      <span class="label">ADC 原始值</span>
      <span class="val mono" id="air-raw">--</span>
    </div>
    <div class="well">
      <span class="label">PA1 输入电压</span>
      <span class="val mono" id="air-voltage">--</span>
    </div>
    <div class="well">
      <span class="label">校准基线 / 偏差</span>
      <span class="val mono" id="air-baseline">--</span>
    </div>
  </div>

  <!-- DHT11 温湿度 -->
  <div class="card card-dht">
    <div class="card-title">DHT11 温湿度（PB8）</div>
    <div class="well">
      <span class="label">传感器状态</span>
      <span class="val highlight" id="dht-status">等待串口数据</span>
    </div>
    <div class="well">
      <span class="label">环境温度</span>
      <span class="val mono" id="dht-temperature">--.- °C</span>
    </div>
    <div class="well">
      <span class="label">相对湿度</span>
      <span class="val mono" id="dht-humidity">--.- %RH</span>
    </div>
  </div>

  <div class="card card-mpu">
    <div class="card-title">MPU6050 姿态与运动</div>
    <div class="well"><span class="label">连接 / 手势</span><span class="val highlight" id="mpu-gesture">等待数据</span></div>
    <div class="well"><span class="label">俯仰 / 横滚</span><span class="val mono" id="mpu-angle">-- / --</span></div>
    <div class="well"><span class="label">加速度 XYZ</span><span class="val mono" id="mpu-accel">--</span></div>
    <div class="well"><span class="label">角速度 XYZ</span><span class="val mono" id="mpu-gyro">--</span></div>
  </div>

  <!-- 专属语音点播控制台 -->
  <div class="card card-voice" id="voice-card">
    <div class="card-title">初音未来 专属语音点播</div>
    <button class="btn-neu btn-voice" onclick="postVoice(4)">
      <div>
        <div class="v-title">开机问候 (BOOT)</div>
        <div class="v-sub">こんにちは、私の名前は初音ミクです!</div>
      </div>
      <div class="v-tag">PLAY</div>
    </button>
    <button class="btn-neu btn-voice" onclick="postVoice(0)">
      <div>
        <div class="v-title">工作中 (WORKING)</div>
        <div class="v-sub">頑張って考えるから、待っててね！</div>
      </div>
      <div class="v-tag">PLAY</div>
    </button>
    <button class="btn-neu btn-voice" onclick="postVoice(1)">
      <div>
        <div class="v-title">待机中 (WAITING)</div>
        <div class="v-sub">次はどんなタスクかな？マスター！</div>
      </div>
      <div class="v-tag">PLAY</div>
    </button>
    <button class="btn-neu btn-voice" onclick="postVoice(3)">
      <div>
        <div class="v-title">任务完成 (COMPLETE)</div>
        <div class="v-sub">できたよ！完璧に完了しました</div>
      </div>
      <div class="v-tag">PLAY</div>
    </button>
    <button class="btn-neu btn-voice" onclick="postVoice(2)">
      <div>
        <div class="v-title">报错异常 (FAILED)</div>
        <div class="v-sub">ダメです…エラーが発生したよ</div>
      </div>
      <div class="v-tag">PLAY</div>
    </button>
  </div>

  <!-- 3. 麦克风语音指令识别 -->
  <div class="card card-mic">
    <div class="card-title">麦克风语音控制 (STT)</div>
    <div class="mic-box">
      <button id="mic-btn" class="btn-neu btn-primary" onclick="toggleVoiceRecognition()">
        开启麦克风语音监听
      </button>
      <div class="mic-status" id="mic-status">支持指令: 你好 / 思考 / 搞定 / 报错 / 挥手 / 跳跃 / 跑步 / 天气 / 留言 [内容]</div>
    </div>
  </div>

  <!-- 4. 动作交互 -->
  <div class="card card-actions" id="control-card">
    <div class="card-title">动作交互</div>
    <div class="btn-grid">
      <button class="btn-neu" onclick="postState('wave')">挥手问候</button>
      <button class="btn-neu" onclick="postState('jump')">开心跳跃</button>
      <button class="btn-neu" onclick="postState('run')">快步奔跑</button>
      <button class="btn-neu" onclick="postState('working')">全力思考</button>
      <button class="btn-neu" onclick="postState('waiting')">等待输入</button>
      <button class="btn-neu" onclick="postState('failed')">抱头报错</button>
      <button class="btn-neu" onclick="postState('look_left')">左顾凝视</button>
      <button class="btn-neu" onclick="postState('look_right')">右盼凝视</button>
      <button class="btn-neu" onclick="postState('idle')">待机复位</button>
    </div>
  </div>

  <!-- 5. 桌面留言板 -->
  <div class="card card-memo">
    <div class="card-title">桌面便签留言</div>
    <input type="text" id="memo-sender" class="input-neu" placeholder="留言署名 (如: MASTER)" value="MASTER" maxlength="8">
    <input type="text" id="memo-msg" class="input-neu" placeholder="留言内容 (支持汉字自动换行)" value="该休息喝水啦！" maxlength="20">
    <button class="btn-neu btn-primary" onclick="sendMemo()">发送留言到屏幕</button>
  </div>

  <!-- 6. 模式切换 -->
  <div class="card card-modes" id="mode-card">
    <div class="card-title">面板模式切换</div>
    <div class="mode-row">
      <button class="btn-neu" onclick="postMode('ai')">AI监控</button>
      <button class="btn-neu" onclick="postMode('clock')">时钟天气</button>
      <button class="btn-neu" onclick="postMode('geek', 1500)">番茄专注钟</button>
      <button class="btn-neu" onclick="postMode('air')">空气质量</button>
      <button class="btn-neu" onclick="postMode('dht')">温湿度</button>
      <button class="btn-neu" onclick="postMode('mpu')">姿态运动</button>
    </div>
  </div>

  </main>

  <nav class="mobile-nav" aria-label="手机快捷导航">
    <a href="#status-card"><span>●</span>状态</a>
    <a href="#sensor-card"><span>◇</span>环境</a>
    <a href="#control-card"><span>＋</span>控制</a>
    <a href="#mode-card"><span>▦</span>面板</a>
  </nav>

  <div id="toast" class="toast">指令已送达</div>

  <script>
    function showToast(msg) {
      var t = document.getElementById('toast');
      t.innerText = msg;
      t.style.opacity = '1';
      setTimeout(() => { t.style.opacity = '0'; }, 1500);
    }

    async function api(url, data) {
      try {
        await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        showToast('指令已送达');
        setTimeout(refresh, 100);
      } catch (e) {
        showToast('发送失败: ' + e);
      }
    }

    function postState(s) { api('/api/state', { state: s }); }
    function postMode(m, extra) { api('/api/mode', { mode: m, extra: extra }); }
    function postVoice(vid) { api('/api/voice', { voice_id: vid }); }
    
    function sendMemo(sender, text) {
      var s = sender || document.getElementById('memo-sender').value;
      var m = text || document.getElementById('memo-msg').value;
      api('/api/memo', { sender: s, text: m });
    }

    async function refresh() {
      try {
        var r = await fetch('/status');
        var d = await r.json();
        document.getElementById('state-val').innerText = d.state_name || d.state;
        document.getElementById('token-val').innerText = d.tokens ? Number(d.tokens).toLocaleString() : '--';
        document.getElementById('title-val').innerText = d.title || 'STM32 PET';
        var air = d.mq135 || {};
        var levelNames = { WARMUP: '预热中', GOOD: '良好', FAIR: '一般', POOR: '较差', BAD: '很差', OFFLINE: '未连接' };
        var airStatus = levelNames[air.level] || air.level || '未连接';
        if (!air.online && air.status) airStatus = air.status;
        if (!air.online && air.error) airStatus += '：' + air.error;
        document.getElementById('air-level').innerText = airStatus;
        document.getElementById('air-quality').innerText = air.online ? (air.quality + '%（相对值）') : '--';
        document.getElementById('air-raw').innerText = air.online ? air.raw : '--';
        document.getElementById('air-voltage').innerText = air.online ? (air.mv + ' mV') : '--';
        document.getElementById('air-baseline').innerText = air.online ? (air.baseline + ' / ' + (air.delta >= 0 ? '+' : '') + air.delta) : '--';
        var dht = d.dht11 || {};
        document.getElementById('dht-status').innerText = dht.status || '等待串口数据';
        document.getElementById('dht-temperature').innerText = dht.valid ? Number(dht.temperature).toFixed(1) + ' °C' : '--.- °C';
        document.getElementById('dht-humidity').innerText = dht.valid ? Number(dht.humidity).toFixed(1) + ' %RH' : '--.- %RH';
        var mpu = d.mpu6050 || {};
        var gestureNames = { STABLE:'稳定', SHAKE:'摇晃', TILT_LEFT:'左倾', TILT_RIGHT:'右倾', OFFLINE:'未连接' };
        document.getElementById('mpu-gesture').innerText = gestureNames[mpu.gesture] || mpu.gesture || '未连接';
        document.getElementById('mpu-angle').innerText = mpu.online ? (mpu.pitch.toFixed(1) + '° / ' + mpu.roll.toFixed(1) + '°') : '-- / --';
        document.getElementById('mpu-accel').innerText = mpu.online ? (mpu.ax + ' / ' + mpu.ay + ' / ' + mpu.az + ' mg') : '--';
        document.getElementById('mpu-gyro').innerText = mpu.online ? (mpu.gx.toFixed(1) + ' / ' + mpu.gy.toFixed(1) + ' / ' + mpu.gz.toFixed(1) + ' °/s') : '--';
        var modeNames = { 1: 'AI 监控模式', 2: '桌面时钟天气', 3: '桌面留言板', 4: '番茄专注钟', 5: '空气质量监测', 6: '温湿度监测', 7: '姿态运动监测' };
        document.getElementById('mode-val').innerText = modeNames[d.mode] || ('模式 ' + d.mode);
      } catch (e) {}
    }

    /* 浏览器语音识别 (Web Speech API) */
    var recognition = null;
    var isListening = false;

    function initSpeech() {
      var SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SpeechRec) {
        document.getElementById('mic-status').innerText = '当前浏览器暂不支持 Web Speech API，建议使用 Chrome/Edge/Safari。';
        return null;
      }
      var r = new SpeechRec();
      r.lang = 'zh-CN';
      r.continuous = true;
      r.interimResults = false;

      r.onstart = function() {
        isListening = true;
        document.getElementById('mic-btn').innerText = '正在监听您的语音指令... (点击停止)';
        document.getElementById('mic-status').innerText = '请说话: \"你好 / 思考 / 搞定 / 报错 / 跑步 / 天气 / 留言...\"';
      };

      r.onresult = function(event) {
        var transcript = event.results[event.results.length - 1][0].transcript.trim();
        document.getElementById('mic-status').innerText = '识别到语音: \"' + transcript + '\"';
        handleVoiceCommand(transcript);
      };

      r.onerror = function(event) {
        document.getElementById('mic-status').innerText = '语音识别提示: ' + event.error;
      };

      r.onend = function() {
        if (isListening) {
          try { r.start(); } catch(e) {}
        } else {
          document.getElementById('mic-btn').innerText = '开启麦克风语音监听';
        }
      };
      return r;
    }

    function toggleVoiceRecognition() {
      if (!recognition) recognition = initSpeech();
      if (!recognition) return;

      if (isListening) {
        isListening = false;
        recognition.stop();
        document.getElementById('mic-btn').innerText = '开启麦克风语音监听';
        document.getElementById('mic-status').innerText = '语音监听已关闭。';
      } else {
        try {
          recognition.start();
        } catch(e) {
          showToast('无法启动麦克风: ' + e);
        }
      }
    }

    function handleVoiceCommand(cmd) {
      cmd = cmd.toLowerCase();
      if (cmd.includes('你好') || cmd.includes('初音') || cmd.includes('问候') || cmd.includes('打招呼')) {
        postVoice(4);
      } else if (cmd.includes('思考') || cmd.includes('工作') || cmd.includes('写代码')) {
        postVoice(0);
      } else if (cmd.includes('等待') || cmd.includes('在吗') || cmd.includes('待机')) {
        postVoice(1);
      } else if (cmd.includes('搞定') || cmd.includes('完成') || cmd.includes('成功') || cmd.includes('夸我')) {
        postVoice(3);
      } else if (cmd.includes('报错') || cmd.includes('失败') || cmd.includes('错误')) {
        postVoice(2);
      } else if (cmd.includes('挥手')) {
        postState('wave');
      } else if (cmd.includes('跳跃') || cmd.includes('跳舞')) {
        postState('jump');
      } else if (cmd.includes('跑步') || cmd.includes('快跑')) {
        postState('run');
      } else if (cmd.includes('天气') || cmd.includes('时钟') || cmd.includes('几点')) {
        postMode('clock');
      } else if (cmd.includes('番茄') || cmd.includes('专注')) {
        postMode('geek', 1500);
      } else if (cmd.includes('留言') || cmd.includes('便签') || cmd.includes('提醒')) {
        var content = cmd.replace(/^(留言|便签|提醒)/, '').trim() || '收到语音提醒！';
        sendMemo('VOICE', content);
      } else {
        showToast('未识别的指令: ' + cmd);
      }
    }

    setInterval(refresh, 1500);
    refresh();
  </script>
</body>
</html>
"""


class WebhookHandler(BaseHTTPRequestHandler):
    sender_instance: Optional[PetDashboardSender] = None

    def do_POST(self):
        content_len = int(self.headers.get('Content-Length', 0))
        post_body = self.rfile.read(content_len)
        try:
            data = json.loads(post_body.decode('utf-8'))
            path = self.path
            if path == "/api/state":
                state = STATE_MAP.get(str(data.get("state", "0")).lower(), 0)
                if self.sender_instance.current_mode == 2:
                    now = datetime.now()
                    self.sender_instance.send_weather_clock(now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), self.sender_instance.weather_info, self.sender_instance.weather_tip, state=state, lock_sec=60.0)
                else:
                    self.sender_instance.send_ai(state=state, lock_sec=60.0)
            elif path == "/api/voice":
                vid = int(data.get("voice_id", 4))
                act = data.get("action")
                act_int = int(act) if act is not None else None
                self.sender_instance.send_voice(vid, act_int, lock_sec=20.0)
            elif path == "/api/memo":
                sender = str(data.get("sender", "WEB"))
                text = str(data.get("text", "Hello"))
                self.sender_instance.send_memo(sender=sender, text=text, lock_sec=60.0,
                                               select_display=True)
            elif path == "/api/mode":
                m = str(data.get("mode", "ai")).lower()
                if m == "clock":
                    now = datetime.now()
                    self.sender_instance.send_weather_clock(now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), "Sunny +26C", "Daily Clock", lock_sec=0.0, select_display=True)
                elif m == "geek":
                    self.sender_instance.send_geek(int(data.get("extra", 1500)), 12, 99,
                                                    state=self.sender_instance.current_state,
                                                    lock_sec=0.0, select_display=True)
                elif m == "air":
                    self.sender_instance.send_air(lock_sec=0.0, select_display=True)
                elif m == "dht":
                    self.sender_instance.send_dht(lock_sec=0.0, select_display=True)
                elif m == "mpu":
                    self.sender_instance.send_mpu(select_display=True)
                else:
                    self.sender_instance.send_ai(state=self.sender_instance.current_state,
                                                 lock_sec=0.0, select_display=True)
            else:
                state_str = str(data.get("state", "0")).lower()
                state = STATE_MAP.get(state_str, 0)
                self.sender_instance.send_ai(
                    state=state,
                    tokens=int(data.get("tokens", self.sender_instance.total_tokens)),
                    remain_pct=int(data.get("remain", self.sender_instance.remaining_percent)),
                    title=str(data.get("title", self.sender_instance.session_title)),
                    lock_sec=10.0
                )

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        except Exception as e:
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))

    def do_GET(self):
        if self.path == "/status":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            info = {
                "mode": self.sender_instance.current_mode,
                "state": self.sender_instance.current_state,
                "state_name": STATE_NAMES.get(self.sender_instance.current_state, "UNKNOWN"),
                "tokens": self.sender_instance.total_tokens,
                "remaining_percent": self.sender_instance.remaining_percent,
                "reset_minutes": self.sender_instance.reset_minutes,
                "title": self.sender_instance.session_title,
                "mq135": self.sender_instance.mq135.snapshot(),
                "dht11": self.sender_instance.mq135.dht_snapshot(),
                "mpu6050": self.sender_instance.mq135.mpu_snapshot()
            }
            self.wfile.write(json.dumps(info, ensure_ascii=False, indent=2).encode('utf-8'))
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))

    def log_message(self, format, *args): pass


def start_http_server(sender: PetDashboardSender, port: int = DEFAULT_HTTP_PORT):
    WebhookHandler.sender_instance = sender
    server = ThreadingHTTPServer(('0.0.0.0', port), WebhookHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    bcast_list = ", ".join(sender.local_ips)
    print("\n=======================================================")
    print("  Neumorphism Web Console (Voice Control Ready):")
    print(f"  * Local Access:  http://localhost:{port}")
    print(f"  * Mobile Access: http://192.168.1.85:{port}")
    print(f"  * Physical NICs: {bcast_list} -> Subnet Broadcast Port {sender.port}")
    print("=======================================================\n")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    sender = PetDashboardSender(target_ip=target)
    sender.mq135.start()
    weather_svc = WeatherService()
    watcher = AntigravityWatcher(sender, weather_svc)

    start_http_server(sender, DEFAULT_HTTP_PORT)

    print("[*] Miku Pet Monitor running... (Press Ctrl+C to stop)")
    while True:
        try:
            watcher.poll()
            time.sleep(1.0)
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            time.sleep(1.0)


if __name__ == "__main__":
    main()
