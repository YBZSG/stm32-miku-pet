#!/usr/bin/env python3
"""Convert a Codex v2 pet atlas to an STM32-friendly RGB565 RLE package."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from PIL import Image


CELL_SIZE = (192, 208)
FRAME_COUNTS = (7, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8)
STATE_NAMES = (
    "idle", "run_right", "run_left", "wave", "jump", "failed",
    "waiting", "working", "review", "look_0_157", "look_180_337",
)
MAGIC = b"MPET"
VERSION = 1
HEADER = struct.Struct("<4sHHHHII")
ENTRY = struct.Struct("<BBHIII")


def rgb565(pixel: tuple[int, int, int]) -> int:
    r, g, b = pixel
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def encode_rle(image: Image.Image) -> bytes:
    values = [rgb565(pixel) for pixel in image.get_flattened_data()]
    output = bytearray()
    index = 0
    while index < len(values):
        color = values[index]
        count = 1
        while index + count < len(values) and values[index + count] == color and count < 255:
            count += 1
        output += struct.pack("<BH", count, color)
        index += count
    return bytes(output)


def normalize_look_scale(cell: Image.Image) -> Image.Image:
    """Match look-direction sprite height to idle without changing aspect ratio."""
    alpha = cell.getchannel("A")
    bbox = alpha.point(lambda value: 255 if value > 16 else 0).getbbox()
    if not bbox:
        return cell
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    target_height = 198
    if height >= target_height:
        return cell
    scale = target_height / height
    new_width = max(1, round(width * scale))
    sprite = cell.crop(bbox).resize((new_width, target_height), Image.Resampling.LANCZOS)
    normalized = Image.new("RGBA", cell.size, (0, 0, 0, 0))
    x = (cell.width - new_width) // 2
    y = 203 - target_height
    normalized.alpha_composite(sprite, (x, y))
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("atlas", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--width", type=int, default=96)
    parser.add_argument("--height", type=int, default=104)
    # Match firmware RGB565 background 0xF7BE exactly after quantization.
    parser.add_argument("--background", default="F7F7F7")
    args = parser.parse_args()

    atlas = Image.open(args.atlas).convert("RGBA")
    expected = (CELL_SIZE[0] * 8, CELL_SIZE[1] * 11)
    if atlas.size != expected:
        raise SystemExit(f"expected atlas {expected}, got {atlas.size}")

    background_rgb = tuple(bytes.fromhex(args.background))
    entries: list[dict[str, int | str]] = []
    payloads: list[bytes] = []

    for state, frame_count in enumerate(FRAME_COUNTS):
        for frame in range(frame_count):
            x0, y0 = frame * CELL_SIZE[0], state * CELL_SIZE[1]
            cell = atlas.crop((x0, y0, x0 + CELL_SIZE[0], y0 + CELL_SIZE[1]))
            if state in (9, 10):
                cell = normalize_look_scale(cell)
            cell = cell.resize((args.width, args.height), Image.Resampling.LANCZOS)
            background = Image.new("RGBA", cell.size, (*background_rgb, 255))
            background.alpha_composite(cell)
            encoded = encode_rle(background.convert("RGB"))
            payloads.append(encoded)
            entries.append({
                "state": state,
                "state_name": STATE_NAMES[state],
                "frame": frame,
                "duration_ms": 140 if state in (1, 2) else 180,
                "length": len(encoded),
            })

    table_size = ENTRY.size * len(entries)
    data_offset = HEADER.size + table_size
    cursor = data_offset
    table = bytearray()
    for entry, payload in zip(entries, payloads):
        entry["offset"] = cursor
        table += ENTRY.pack(
            int(entry["state"]), int(entry["frame"]), int(entry["duration_ms"]),
            cursor, len(payload), args.width * args.height,
        )
        cursor += len(payload)

    package = bytearray(HEADER.pack(
        MAGIC, VERSION, args.width, args.height, len(entries), HEADER.size, data_offset,
    ))
    package += table
    for payload in payloads:
        package += payload

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(package)
    manifest = {
        "format": "MPET-RGB565-RLE",
        "version": VERSION,
        "width": args.width,
        "height": args.height,
        "background": f"#{args.background.upper()}",
        "frame_count": len(entries),
        "states": list(STATE_NAMES),
        "frames": entries,
        "package_bytes": len(package),
    }
    args.output.with_suffix(".json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output), "bytes": len(package), "frames": len(entries)}))


if __name__ == "__main__":
    main()
