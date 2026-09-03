#!/usr/bin/env python3
"""
Burn full-screen "editorial-kinetic" sequential captions onto a video and
mux in a narration voiceover track. Visual language matches the
editorial-kinetic Hyperframes reference: right-aligned lines of varying
size building top-to-bottom over a darkened frame, a red rule down the
left edge, a page counter, a rotated side label, and a bottom micro
caption. Driven by real word timings instead of a fixed script, so any
AI-generated narration can drive it.

Usage:
    python3 burn_kinetic_subtitles.py \
        --video input.mp4 \
        --cues cues.json \
        --voiceover voiceover.mp3 \
        --out final.mp4 \
        [--original-volume 0.12] [--voiceover-volume 1.0] [--scrim 0.62]

cues.json shape:
{
  "pages": [
    {
      "lines": [
        {"text": "EVERY GREAT", "start": 0.30, "emphasis": false},
        {"text": "IDEA", "start": 0.85, "emphasis": true},
        {"text": "STARTS WITH", "start": 1.45, "emphasis": false}
      ],
      "clear_at": 3.6
    },
    ...
  ]
}
"start" is seconds from the start of the voiceover track when that line
begins appearing; "clear_at" is when the whole page fades out. "emphasis"
lines are rendered large and red; everything else is white, sized by a
short/medium heuristic.
"""
import argparse
import json
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont, ImageFilter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RED = (242, 13, 47)
WHITE = (247, 247, 247)
GREY = (150, 150, 150)

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

RIGHT_MARGIN = 150
RULE_X = 90
RULE_TOP = 120
RULE_BOTTOM = 1800
BLOCK_TOP = 640
LINE_GAP = 22
ENTER_DUR = 0.32
PAGE_FADE = 0.28
EMPHASIS_SIZE = 148
MEDIUM_SIZE = 76
SHORT_SIZE = 44


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def font(size):
    return ImageFont.truetype(FONT_PATH, max(8, int(size)))


def ffprobe_json(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path],
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
    return width, height, fps


def load_pages(path):
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    pages = payload["pages"]
    for page in pages:
        page["lines"].sort(key=lambda ln: ln["start"])
    pages.sort(key=lambda p: p["lines"][0]["start"])
    return pages


def active_page(pages, t):
    for i, page in enumerate(pages):
        start = page["lines"][0]["start"]
        if start <= t < page["clear_at"]:
            return i, page
    return None, None


def line_size(line):
    if line.get("emphasis"):
        return EMPHASIS_SIZE
    text = line["text"]
    if len(text) <= 10 and len(text.split()) <= 2:
        return SHORT_SIZE
    return MEDIUM_SIZE


def fit_font(draw, text, size, max_w):
    while size > 16:
        f = font(size)
        w = draw.textbbox((0, 0), text, font=f)[2]
        if w <= max_w:
            return f
        size -= 2
    return font(16)


def draw_page(base, page, t, width, height):
    page_start = page["lines"][0]["start"]
    clear_at = page["clear_at"]
    page_alpha = 1.0
    if t > clear_at - PAGE_FADE:
        page_alpha = clamp((clear_at - t) / PAGE_FADE)
    if page_alpha <= 0.01:
        return

    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    max_w = width - RIGHT_MARGIN - 120

    y = BLOCK_TOP
    for line in page["lines"]:
        if line["start"] > t:
            continue
        size = line_size(line)
        color = RED if line.get("emphasis") else WHITE
        f = fit_font(draw, line["text"], size, max_w)
        bbox = draw.textbbox((0, 0), line["text"], font=f)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        local = t - line["start"]
        progress = ease_out(local / ENTER_DUR)
        alpha = clamp(progress) * page_alpha
        y_shift = int((1 - progress) * 28)
        x = width - RIGHT_MARGIN - tw
        line_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ld = ImageDraw.Draw(line_layer)
        ld.text((x, y + y_shift), line["text"], font=f, fill=(*color, int(255 * alpha)))
        layer.alpha_composite(line_layer)
        y += th + LINE_GAP

    base.alpha_composite(layer)


def draw_chrome(base, page_index, total_pages, width, height, t):
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    d.line((RULE_X, RULE_TOP, RULE_X, RULE_BOTTOM), fill=(*RED, 255), width=8)

    label = "0{} / SEQUENTIAL CAPTIONS".format(min(page_index + 1, 9))
    d.text((RULE_X + 20, 78), label, font=font(26), fill=RED)

    micro = "TOP → BOTTOM  •  NEXT PAGE RESTARTS AT TOP"
    d.text((RULE_X + 20, height - 92), micro, font=font(20), fill=GREY)

    side = "HOOK • BODY • PAYOFF"
    sf = font(20)
    sb = d.textbbox((0, 0), side, font=sf)
    sw, sh = sb[2] - sb[0], sb[3] - sb[1]
    side_layer = Image.new("RGBA", (sw + 20, sh + 20), (0, 0, 0, 0))
    sld = ImageDraw.Draw(side_layer)
    sld.text((10, 6), side, font=sf, fill=(*GREY, 255))
    side_layer = side_layer.rotate(90, expand=True, resample=Image.Resampling.BICUBIC)
    base.alpha_composite(side_layer, (width - 46, height // 2 - sw // 2))

    base.alpha_composite(layer)


def render_overlay_video(video_path, pages, scrim, tmp_silent_path):
    width, height, fps = video_info(video_path)
    decode_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", video_path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-an", "-",
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

    scrim_layer = Image.new("RGBA", (width, height), (0, 0, 0, int(255 * scrim)))
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-360, -120, 640, 900), fill=(140, 0, 20, 130))
    glow = glow.filter(ImageFilter.GaussianBlur(160))

    frame_bytes = width * height * 3
    n = 0
    try:
        while True:
            raw = decoder.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            t = n / fps
            frame = Image.frombuffer("RGB", (width, height), raw, "raw", "RGB", 0, 1).convert("RGBA")
            frame.alpha_composite(scrim_layer)
            frame.alpha_composite(glow)
            idx, page = active_page(pages, t)
            if page:
                draw_page(frame, page, t, width, height)
                draw_chrome(frame, idx, len(pages), width, height, t)
            encoder.stdin.write(frame.convert("RGB").tobytes())
            n += 1
    finally:
        decoder.stdout.close()
        encoder.stdin.close()
        decoder.wait()
        code = encoder.wait()
        if code:
            raise SystemExit(f"ffmpeg encode failed with code {code}")


def mux_audio(video_only_path, video_path, voiceover_path, out_path, original_volume, voiceover_volume):
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
    ap.add_argument("--original-volume", type=float, default=0.12)
    ap.add_argument("--voiceover-volume", type=float, default=1.0)
    ap.add_argument("--scrim", type=float, default=0.62,
                     help="0-1 darkness overlay behind the captions so they read like the reference over any footage")
    args = ap.parse_args()

    pages = load_pages(args.cues)

    with tempfile.TemporaryDirectory() as tmp:
        silent_path = os.path.join(tmp, "overlay_silent.mp4")
        render_overlay_video(args.video, pages, args.scrim, silent_path)
        mux_audio(silent_path, args.video, args.voiceover, args.out, args.original_volume, args.voiceover_volume)

    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
