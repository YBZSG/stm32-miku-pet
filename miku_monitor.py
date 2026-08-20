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
from datetime import datetime
from typing import Optional, List
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

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
        self.remaining_percent = 85
        self.reset_minutes = 60
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

    def _send_raw_payload(self, mode: int, state: int, payload_54bytes: bytes, burst: int = 1):
        self.sequence_id = (self.sequence_id + 1) & 0xFFFFFFFF
        header = struct.pack("<BBBBII", 0xA5, 0x5A, mode, state, self.session_id, self.sequence_id)
        payload = header + payload_54bytes
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
                title: Optional[str] = None, lock_sec: float = 0.0):
        with self._lock:
            self.current_mode = 1
            if lock_sec > 0:
                self.manual_lock_until = time.time() + lock_sec
            if state is not None:
                if lock_sec > 0 or time.time() >= self.manual_lock_until:
                    self.current_state = state
            if tokens is not None: self.total_tokens = tokens
            if remain_pct is not None: self.remaining_percent = max(0, min(100, remain_pct))
            if reset_min is not None: self.reset_minutes = reset_min
            if title is not None and title.strip(): self.session_title = title.strip()

            title_bytes = safe_gbk_truncate(self.session_title, 36)
            title_padded = title_bytes.ljust(36, b'\x00')
            body = struct.pack("<IBIB36s", self.total_tokens, self.remaining_percent, self.reset_minutes, len(title_bytes), title_padded)
            self._send_raw_payload(1, self.current_state, body, burst=2 if lock_sec > 0 else 1)

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

    def send_weather_clock(self, date_str: str, time_str: str, weather: str, tip: str, state: Optional[int] = None, lock_sec: float = 0.0):
        with self._lock:
            self.current_mode = 2
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
            self._send_raw_payload(2, self.current_state, body, burst=1)

    def send_memo(self, sender: str, text: str, state: int = 3, lock_sec: float = 30.0):
        with self._lock:
            self.current_mode = 3
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
            self._send_raw_payload(3, self.current_state, body, burst=2)

    def send_geek(self, pomo_sec: int, commits: int, stars: int, state: int = 7, lock_sec: float = 30.0):
        with self._lock:
            self.current_mode = 4
            if lock_sec > 0:
                self.manual_lock_until = time.time() + lock_sec
            self.current_state = state
            self.pomo_seconds = pomo_sec
            self.geek_commits = commits
            self.geek_stars = stars
            body = struct.pack("<III34x", pomo_sec, commits, stars)
            self._send_raw_payload(4, self.current_state, body, burst=2)


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
        self.last_active_time = time.time()

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
        elif self.sender.current_mode == 3 or self.sender.current_mode == 4:
            return

        if time.time() < self.sender.manual_lock_until:
            return

        log_path = self.find_latest_transcript()
        time_since_mtime = 999.0
        size = 0
        state = 0
        title = "Antigravity"

        if log_path and os.path.isfile(log_path):
            try:
                mtime = os.path.getmtime(log_path)
                time_since_mtime = time.time() - mtime
                size = os.path.getsize(log_path)
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line: continue
                        try:
                            obj = json.loads(line)
                            if obj.get("type") == "USER_INPUT":
                                raw = obj.get("content", "")
                                if "<USER_REQUEST>" in raw:
                                    req = raw.split("<USER_REQUEST>")[1].split("</USER_REQUEST>")[0].strip()
                                    if req:
                                        title = req.split("\n")[0].strip()
                            elif obj.get("type") == "PLANNER_RESPONSE":
                                status = obj.get("status", "")
                                tool_calls = obj.get("tool_calls", [])
                                if status == "RUNNING" or (time_since_mtime < 5.0 and tool_calls):
                                    state = 7  # WORKING (全力思考)
                                    self.last_active_time = time.time()
                                elif status == "ERROR":
                                    state = 5  # FAILED (抱头报错)
                        except Exception: pass
            except Exception: pass

        if state == 0:
            if time_since_mtime < 25.0:
                state = 6  # WAITING (等待指令)
            else:
                state = 0  # IDLE (待机复位)

        self.sender.send_ai(state=state, tokens=int(size / 3.8), remain_pct=85, reset_min=60, title=title)


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
    --primary: #6d5dfc;
    --primary-light: #8b7efd;
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
    color: var(--text-main);
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
    color: var(--text-muted);
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
</style>
</head>
<body>

  <div class="header">
    <h1>MIKU PET CONSOLE</h1>
    <div class="subtitle">STM32 桌面宠物控制中心</div>
  </div>

  <!-- 1. 状态监控 -->
  <div class="card">
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

  <!-- 2. 专属语音点播控制台 -->
  <div class="card">
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
  <div class="card">
    <div class="card-title">麦克风语音控制 (STT)</div>
    <div class="mic-box">
      <button id="mic-btn" class="btn-neu btn-primary" onclick="toggleVoiceRecognition()">
        开启麦克风语音监听
      </button>
      <div class="mic-status" id="mic-status">支持指令: 你好 / 思考 / 搞定 / 报错 / 挥手 / 跳跃 / 跑步 / 天气 / 留言 [内容]</div>
    </div>
  </div>

  <!-- 4. 动作交互 -->
  <div class="card">
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
  <div class="card">
    <div class="card-title">桌面便签留言</div>
    <input type="text" id="memo-sender" class="input-neu" placeholder="留言署名 (如: MASTER)" value="MASTER" maxlength="8">
    <input type="text" id="memo-msg" class="input-neu" placeholder="留言内容 (支持汉字自动换行)" value="该休息喝水啦！" maxlength="20">
    <button class="btn-neu btn-primary" onclick="sendMemo()">发送留言到屏幕</button>
  </div>

  <!-- 6. 模式切换 -->
  <div class="card">
    <div class="card-title">面板模式切换</div>
    <div class="mode-row">
      <button class="btn-neu" onclick="postMode('ai')">AI监控</button>
      <button class="btn-neu" onclick="postMode('clock')">时钟天气</button>
      <button class="btn-neu" onclick="postMode('geek', 1500)">番茄专注钟</button>
    </div>
  </div>

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
        var modeNames = { 1: 'AI 监控模式', 2: '桌面时钟天气', 3: '桌面留言板', 4: '番茄专注钟' };
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
                self.sender_instance.send_memo(sender=sender, text=text, lock_sec=60.0)
            elif path == "/api/mode":
                m = str(data.get("mode", "ai")).lower()
                if m == "clock":
                    now = datetime.now()
                    self.sender_instance.send_weather_clock(now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), "Sunny +26C", "Daily Clock", lock_sec=60.0)
                elif m == "geek":
                    self.sender_instance.send_geek(int(data.get("extra", 1500)), 12, 99, lock_sec=60.0)
                else:
                    self.sender_instance.send_ai(state=0, lock_sec=60.0)
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
                "title": self.sender_instance.session_title
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
