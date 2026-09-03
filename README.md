# AI Vlog Kinetic-Subtitle Workflow

Automates turning a raw vlog clip into a narrated video with animated,
on-brand kinetic subtitles — inspired by the "editorial-kinetic"
Hyperframes template that was reviewed for this project (bold white/red
uppercase captions, punch-in motion, red accent bar).

**Live workflow:** https://n8n.farhadflow.com/workflow/YFlSyUO3Q8G02DtG
(created via the n8n Workflow SDK, currently inactive until the render
host is set up — see Setup below).

## Pipeline

1. **Vlog Upload Webhook** — `POST /webhook/vlog-kinetic-subtitles`, a
   multipart request carrying the raw video file (field `video`) plus a
   `topic` string and optional `voiceId`.
2. **Normalize Input** — defaults `topic`/`voiceId` and carries the
   `scriptPath` (the render script's location on the render host — edit
   this node if you deploy it somewhere other than
   `/data/scripts/burn_kinetic_subtitles.py`).
3. **Generate Script** (OpenAI, `gpt-5.4`) — writes a ~60-90 word narration
   script and wraps 3-5 "power words" in `**bold**` for kinetic emphasis.
4. **Clean Script Text** (Code) — strips the `**bold**` markers to get the
   plain narration text, remembering the character ranges that were
   emphasized.
5. **ElevenLabs Voiceover** (HTTP Request →
   `/v1/text-to-speech/{voice_id}/with-timestamps`) — turns the clean
   narration into speech, returning audio plus character-level timestamps.
6. **Build Kinetic Cues** (Code) — turns the character alignment into
   word-level timings, groups words into short 2-4 word caption bursts,
   carries the emphasis flag per word, and base64-decodes the voiceover
   audio. Produces the `cues.json` the renderer expects.
7. **Prepare Paths** (Code) — computes a per-execution work directory and
   file paths on the render host.
8. **Make Work Dir** (SSH) — `mkdir -p` the work directory on the render
   host.
9. **Attach Files Binary** (Code) — reassembles one item carrying the
   uploaded video, the voiceover audio, and `cues.json` as binary data.
10. **Upload Video / Upload Voiceover / Upload Cues** (SSH, SFTP upload,
    run in parallel) — copies the three files into the work directory on
    the render host.
11. **Render Kinetic Subtitles** (SSH command) — runs
    `scripts/burn_kinetic_subtitles.py` on the render host, which burns
    the animated captions onto the video and mixes in the voiceover
    (ducking the original audio) via ffmpeg.
12. **Download Final Video** (SSH, SFTP download) → **Respond With Video**
    — pulls the rendered MP4 back and returns it as the webhook response.

## Why SSH instead of Execute Command

n8n has no built-in node that can composite animated text onto video
frames, so the actual rendering is done by `scripts/burn_kinetic_subtitles.py`
(Pillow + ffmpeg) on a separate machine. This n8n instance's **Execute
Command** node isn't available in its node registry, so the workflow uses
the **SSH** node instead — for both running the render command and moving
files (SFTP upload/download) — against the credential named
**"SSH Password account"**. In practice this means: point that credential
at a host that has `ffmpeg`, `python3`, and `pip install -r
scripts/requirements.txt` done, with `scripts/burn_kinetic_subtitles.py`
and `scripts/assets/` deployed there.

If you're running n8n self-hosted somewhere that *does* have the Execute
Command node available, you can simplify this by swapping the SSH nodes
for Execute Command + Write/Read Binary File nodes operating on local
disk instead — the render script itself doesn't change.

## Setup checklist

1. Pick (or provision) a render host with `ffmpeg`, `ffprobe`, and Python 3.
2. Copy `scripts/burn_kinetic_subtitles.py`, `scripts/requirements.txt`,
   and `scripts/assets/` to that host (e.g. `/data/scripts/`), then
   `pip install -r requirements.txt` there.
3. Point the **"SSH Password account"** n8n credential at that host.
4. In the **Normalize Input** node, confirm `scriptPath` matches wherever
   you deployed `burn_kinetic_subtitles.py`.
5. Set a real ElevenLabs `voiceId` default in **Normalize Input** (or pass
   `voiceId` in each request) — it currently defaults to a placeholder
   voice.
6. Activate the workflow, then test with:
   ```bash
   curl -X POST https://n8n.farhadflow.com/webhook/vlog-kinetic-subtitles \
     -F "video=@my-clip.mp4" \
     -F "topic=A weekend trip to the mountains" \
     -o final.mp4
   ```

## Files

- `n8n-workflow/vlog-kinetic-subtitles.workflow.ts` — the n8n Workflow SDK
  source that generated the live workflow (source of truth; re-run through
  `validate_workflow` / `update_workflow` if you edit it).
- `scripts/burn_kinetic_subtitles.py` — the ffmpeg/Pillow renderer.
- `scripts/assets/` — the DejaVu Sans Mono Bold font used for captions
  (carried over from the reviewed template so the look matches).

## Customizing the look

`scripts/burn_kinetic_subtitles.py` draws one caption "card" per cue:
white bold uppercase text on a semi-transparent dark rounded rectangle,
a red accent bar on the left edge, emphasis words larger and in red
(`#f20d2f`), positioned in the lower third. Tweak `RED`, `WHITE`, the
`0.74` vertical anchor, card padding, or animation easing at the top of
that file to restyle it.
