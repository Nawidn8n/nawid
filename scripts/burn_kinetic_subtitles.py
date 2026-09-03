#!/usr/bin/env python3
"""
Burn animated "editorial-kinetic" subtitles onto a real video and mux in a
narration voiceover track. Style is adapted from the editorial-kinetic
Hyperframes template (bold white/red uppercase captions, punch-in motion)
but reworked as a lower-third caption overlay so the underlying footage
stays visible, driven by real word timings instead of a fixed script.

Usage:
    python3 burn_kinetic_subtitles.py \
        --video input.mp4 \
        --cues cues.json \
        --voiceover voiceover.mp3 \
        --out final.mp4 \
        [--original-volume 0.15] [--voiceover-volume 1.0]

cues.json shape:
{
  "cues": [
    {"start": 0.10, "end": 1.05, "words": [{"t": "EVERY", "e": false}, {"t": "IDEA", "e": true}]},
    ...
  ]
}
start/end are seconds from the start of the voiceover track. "e" marks a
word as an emphasis/keyword (rendered larger, in red).
"""
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont, ImageFilter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RED = (242, 13, 47)
WHITE = (247, 247, 247)
GREY = (200, 200, 200)

FONT_CANDIDATES = [
    os.path.join(SCRIPT_DIR, "assets", "DejaVuSansMono-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
]


def resolve_font_path():
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "No usable bold font found. Expected scripts/assets/DejaVuSansMono-Bold.ttf "
        "next to this script."
    )


FONT_PATH = resolve_font_path()


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def font(size):
    return ImageFont.truetype(FONT_PATH, max(8, int(size)))


def ffprobe_json(path):
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", path,
        ],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def video_info(path):
    data = ffprobe_json(path)
    vstream = next(s for s in data["streams"] if s["codec_type"] == "video")
    width = int(vstream["width"])
    height = int(vstream["height"])
    num, den = vstream.get("r_frame_rate", "24/1").split("/")
    fps = float(num) / float(den) if float(den) else 24.0
    duration = float(data["format"].get("duration") or vstream.get("duration") or 0)
    return width, height, fps, duration


def audio_duration(path):
    data = ffprobe_json(path)
    return float(data["format"]["duration"])


def load_cues(path):
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload["cues"]


def active_cue(cues, t):
    for cue in cues:
        if cue["start"] <= t < cue["end"]:
            return cue
    return None


def measure_line(draw, words, base_size):
    """Return list of (text, font, color, width) for one caption line."""
    parts = []
    total_w = 0
    gap = int(base_size * 0.32)
    for w in words:
        size = int(base_size * (1.28 if w.get("e") else 1.0))
        color = RED if w.get("e") else WHITE
        f = font(size)
        bbox = draw.textbbox((0, 0), w["t"], font=f)
        tw = bbox[2] - bbox[0]
        parts.append((w["t"], f, color, tw))
        total_w += tw + gap
    if parts:
        total_w -= gap
    return parts, total_w


def fit_base_size(draw, words, max_w, start_size=64, min_size=26):
    size = start_size
    while size > min_size:
        _, total_w = measure_line(draw, words, size)
        if total_w <= max_w:
            break
        size -= 2
    return size


def draw_caption(base, cue, t, width, height):
    local = t - cue["start"]
    length = cue["end"] - cue["start"]
    enter = ease_out(local / 0.18)
    leave = clamp((length - local) / 0.16)
    progress = min(enter, leave)
    if progress <= 0.001:
        return

    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    max_w = int(width * 0.82)
    base_size = fit_base_size(draw, cue["words"], max_w, start_size=int(height * 0.052))
    parts, total_w = measure_line(draw, cue["words"], base_size)

    tallest = max((p[1].getbbox(p[0])[3] for p in parts), default=base_size)
    pad_x, pad_y = 34, 22
    card_w = total_w + pad_x * 2
    card_h = tallest + pad_y * 2
    cx = (width - card_w) // 2
    cy = int(height * 0.74) - card_h // 2

    y_shift = int((1 - progress) * 40)
    alpha = clamp(progress)

    card_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    card_draw = ImageDraw.Draw(card_layer)
    card_draw.rounded_rectangle(
        (cx, cy + y_shift, cx + card_w, cy + card_h + y_shift),
        radius=14,
        fill=(8, 8, 8, int(168 * alpha)),
    )
    card_draw.rectangle(
        (cx, cy + y_shift, cx + 8, cy + card_h + y_shift),
        fill=(*RED, int(255 * alpha)),
    )
    layer.alpha_composite(card_layer)

    x = cx + pad_x
    gap = int(base_size * 0.32)
    text_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_layer)
    for word_text, f, color, tw in parts:
        text_draw.text(
            (x, cy + pad_y - 4 + y_shift),
            word_text,
            font=f,
            fill=(*color, int(255 * alpha)),
        )
        x += tw + gap
    layer.alpha_composite(text_layer)

    base.alpha_composite(layer)


def render_overlay_video(video_path, cues, tmp_silent_path):
    width, height, fps, duration = video_info(video_path)
    decode_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", video_path,
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-an", "-",
    ]
    encode_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
        "-r", str(fps), "-i", "-",
        "-c:v", "libx264", "-preset", "medium", "-crf", "17",
        "-pix_fmt", "yuv420p", tmp_silent_path,
    ]

    decoder = subprocess.Popen(decode_cmd, stdout=subprocess.PIPE)
    encoder = subprocess.Popen(encode_cmd, stdin=subprocess.PIPE)

    frame_bytes = width * height * 3
    n = 0
    try:
        while True:
            raw = decoder.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            t = n / fps
            frame = Image.frombuffer("RGB", (width, height), raw, "raw", "RGB", 0, 1).convert("RGBA")
            cue = active_cue(cues, t)
            if cue:
                draw_caption(frame, cue, t, width, height)
            encoder.stdin.write(frame.convert("RGB").tobytes())
            n += 1
    finally:
        decoder.stdout.close()
        encoder.stdin.close()
        decoder.wait()
        code = encoder.wait()
        if code:
            raise SystemExit(f"ffmpeg encode failed with code {code}")

    return width, height, fps, duration


def mux_audio(video_only_path, video_path, voiceover_path, out_path,
               original_volume, voiceover_volume):
    filter_complex = (
        f"[1:a]volume={original_volume}[orig];"
        f"[2:a]volume={voiceover_volume}[vo];"
        f"[orig][vo]amix=inputs=2:duration=longest:dropout_transition=0[aout]"
    )
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", video_only_path,
        "-i", video_path,
        "-i", voiceover_path,
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", out_path,
    ]
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--cues", required=True)
    ap.add_argument("--voiceover", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--original-volume", type=float, default=0.15)
    ap.add_argument("--voiceover-volume", type=float, default=1.0)
    args = ap.parse_args()

    cues = load_cues(args.cues)
    cues.sort(key=lambda c: c["start"])

    with tempfile.TemporaryDirectory() as tmp:
        silent_path = os.path.join(tmp, "overlay_silent.mp4")
        render_overlay_video(args.video, cues, silent_path)
        mux_audio(
            silent_path, args.video, args.voiceover, args.out,
            args.original_volume, args.voiceover_volume,
        )

    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
