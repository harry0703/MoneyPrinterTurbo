"""Converte a subtitle.srt de uma task do MoneyPrinterTurbo em timing.json.

Uso: python3 srt_to_timing.py <subtitle.srt> <timing.json>
"""

import json
import re
import sys

TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def _seconds(stamp: str) -> float:
    h, m, s, ms = TIME.match(stamp.strip()).groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        blocks = re.split(r"\n\s*\n", f.read().strip())
    items = []
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start, end = lines[1].split("-->")
        items.append(
            {
                "n": len(items) + 1,
                "start": round(_seconds(start), 3),
                "end": round(_seconds(end), 3),
                "text": " ".join(lines[2:]),
            }
        )
    return items


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    timing = parse(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(timing, f, ensure_ascii=False, indent=1)
    for item in timing:
        print(f"{item['n']:>3} {item['start']:7.2f} {item['end']:7.2f}  {item['text']}")
