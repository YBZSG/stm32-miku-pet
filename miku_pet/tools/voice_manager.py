# -*- coding: utf-8 -*-
"""
Miku Custom Voice Pack Manager & Builder for STM32 VS1053 (5 Voice Slots)
"""

import os
import sys
import struct
import argparse

VOICE_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "voice")
OUTPUT_BIN = os.path.join(os.path.dirname(__file__), "..", "assets", "miku_voice.bin")

DEFAULT_VOICE_SLOTS = [
    {"name": "working.wav",  "desc": "工作中 / 思考生成中",  "text_ja": "頑張って考えるから、待っててね！"},
    {"name": "waiting.wav",  "desc": "等待指令 / 闲置待机",  "text_ja": "次はどんなタスクかな？マスター！"},
    {"name": "failed.wav",   "desc": "报错 / 异常提醒",      "text_ja": "ダメです…エラーが発生したよ"},
    {"name": "complete.wav", "desc": "任务完成 / 运行成功",  "text_ja": "できたよ！完璧に完了しました"},
    {"name": "boot.wav",     "desc": "开机欢迎问候语",        "text_ja": "こんにちは、私の名前は初音ミクです!"},
]

def build_voice_bin(voice_dir=VOICE_DIR, output_path=OUTPUT_BIN):
    os.makedirs(voice_dir, exist_ok=True)
    header_size = 8 + len(DEFAULT_VOICE_SLOTS) * 8  # 48 bytes for 5 slots
    header = bytearray(64)
    header[0:4] = b"VOIC"
    struct.pack_into("<I", header, 4, 1)  # Version = 1
    
    parts = []
    offset = 64  # Data starts after 64-byte aligned header
    
    for i, slot in enumerate(DEFAULT_VOICE_SLOTS):
        fn = os.path.join(voice_dir, slot["name"])
        if not os.path.isfile(fn):
            print(f"[!] 警告: 缺少音频文件 {slot['name']}，将填充空数据")
            data = b""
        else:
            with open(fn, "rb") as f:
                data = f.read()
        
        parts.append(data)
        struct.pack_into("<II", header, 8 + i * 8, offset, len(data))
        print(f"[*] 音频槽位 [{i}] {slot['name']:<14} ({slot['desc']}): {len(data):>7} 字节, 偏移量 0x{offset:X} -> {slot['text_ja']}")
        offset += len(data)
        
    with open(output_path, "wb") as f:
        f.write(header)
        for p in parts:
            f.write(p)
            
    print(f"\n[OK] 专属 5 音频语音包构建完成: {output_path} (总大小: {offset} 字节)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Miku Voice Pack Manager")
    parser.add_argument("--build", action="store_true", help="Build miku_voice.bin from assets/voice")
    args = parser.parse_args()
    build_voice_bin()
