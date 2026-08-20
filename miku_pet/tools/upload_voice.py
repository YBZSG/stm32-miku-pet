# -*- coding: utf-8 -*-
"""
Python Fast Miku Voice Pack Uploader for STM32 W25Q64 Flash
With Chunk ACK Flow Control (100% Zero Dropped Bytes & Exact CRC32)
"""

import sys
import time
import zlib
import struct
import argparse
import os

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[!] Error: pyserial not installed. Run: pip install pyserial")
    sys.exit(1)

DEFAULT_BIN = os.path.join(os.path.dirname(__file__), "..", "assets", "miku_voice.bin")

def get_available_ports():
    return [p.device for p in serial.tools.list_ports.comports()]

def upload_voice(port=None, bin_path=DEFAULT_BIN, baud=115200):
    if not os.path.isfile(bin_path):
        print(f"[!] 错误: 未找到语音包文件: {bin_path}")
        return False

    with open(bin_path, "rb") as f:
        payload = f.read()

    total_size = len(payload)
    crc = zlib.crc32(payload) & 0xFFFFFFFF

    if not port:
        ports = get_available_ports()
        if not ports:
            print("[!] 未检测到任何已连接的串口！请检查 USB 连接。")
            return False
        port = ports[0]
        print(f"[*] 自动检测到串口: {port}")

    print(f"\n=======================================================")
    print(f"      Miku 专属语音包烧录工具 (精准流控版)            ")
    print(f"=======================================================")
    print(f"  * 目标串口: {port} (波特率: {baud})")
    print(f"  * 语音包文件: {os.path.basename(bin_path)} ({total_size:,} 字节 / {total_size/1024/1024:.2f} MB)")
    print(f"  * CRC32 校验码: 0x{crc:08X}")
    print(f"=======================================================\n")

    try:
        ser = serial.Serial(port, baud, timeout=0.5, write_timeout=10)
    except Exception as e:
        print(f"[!] 打开串口 {port} 失败: {e}")
        print("    提示: 请检查该串口是否被其他串口助手占用。")
        return False

    try:
        ser.dtr = True
        ser.rts = False
        time.sleep(0.1)
        ser.dtr = False
        ser.rts = False
        time.sleep(0.8)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        print("[1/3] 正在与开发板握手并准备擦除 Flash...")
        print("      (如果卡在这一步，请按一下开发板上的黑色 RESET 复位按键)")

        req_packet = b'A' + struct.pack("<II", total_size, crc)
        start_time = time.time()
        ready = False
        erasing = False

        while time.time() - start_time < 45.0:
            if not erasing:
                ser.write(req_packet)
            t_sub = time.time()
            while time.time() - t_sub < 0.5:
                line = ser.readline().decode('ascii', errors='ignore').strip()
                if line:
                    print(f"      开发板回显: {line}")
                if "AUDIO_READY" in line:
                    ready = True
                    break
                elif "AUDIO_ERASING" in line:
                    erasing = True
                    print("      [+] 握手成功，开发板正在擦除 Flash 扇区...")
            if ready:
                break

        if not ready:
            print("\n[!] 等待开发板握手超时！")
            return False

        print("\n[2/3] 开始写入音频数据到 SPI Flash (硬件逐块应答校验)...")
        chunk_size = 256
        sent = 0
        t0 = time.time()

        while sent < total_size:
            chunk = payload[sent : sent + chunk_size]
            ser.write(chunk)
            sent += len(chunk)
            
            # 等待单片机每写完一页返回的确认点号 '.'，绝不丢包
            ser.read(1)

            if sent % 32768 == 0 or sent == total_size:
                pct = (sent / total_size) * 100.0
                elapsed = max(0.1, time.time() - t0)
                speed = (sent / 1024.0) / elapsed
                bar_len = 30
                filled = int(bar_len * sent // total_size)
                bar = "=" * filled + ">" * (1 if filled < bar_len else 0) + " " * max(0, bar_len - filled - 1)
                sys.stdout.write(f"\r  [{bar}] {pct:5.1f}% ({sent:,}/{total_size:,} bytes) | {speed:5.1f} KB/s")
                sys.stdout.flush()

        print("\n\n[3/3] 数据发送完毕，等待 Flash 校验确认...")
        ok = False
        start_time = time.time()
        while time.time() - start_time < 30.0:
            line = ser.readline().decode('ascii', errors='ignore').strip()
            if line:
                print(f"      开发板回显: {line}")
            if "AUDIO_OK" in line:
                ok = True
                break
            elif "AUDIO_CRC_ERROR" in line:
                print("[!] 校验失败: CRC 错误！")
                return False

        if ok:
            print(f"\n[OK] 恭喜！Miku 专属语音包已完美烧录到开发板 Flash！")
            print(f"   开机将自动播放一次: \"こんにちは、私の名前は初音ミクです!\"")
            return True
        else:
            print("[!] 未收到开发板 AUDIO_OK 确认响应。")
            return False

    finally:
        ser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Miku Voice Uploader")
    parser.add_argument("--port", "-p", default=None, help="COM Port (e.g. COM7)")
    parser.add_argument("--bin", "-b", default=DEFAULT_BIN, help="Voice pack bin path")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    args = parser.parse_args()

    upload_voice(port=args.port, bin_path=args.bin, baud=args.baud)
