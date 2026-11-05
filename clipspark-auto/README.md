# CLIPSPARK Auto — one-click video-to-Shorts MVP

This is a real local/server-side automated clipping app, not just a mockup. It uploads videos or accepts YouTube URLs, transcribes with faster-whisper, scores speech-heavy moments, automatically selects non-overlapping clips, crops them to 1080×1920, burns in animated phrase captions, and exports MP4 files and a ZIP.

## Start

1. Install **Python 3.10+** and **FFmpeg** (including ffprobe and the `ass` subtitle filter / libass). Verify `ffmpeg -filters` contains `ass`.
2. In this folder run:

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
   pip install -r requirements.txt
   uvicorn app:app --host 127.0.0.1 --port 8000
   ```
3. Open http://127.0.0.1:8000 in a browser.
4. Upload a video or paste a YouTube URL, then click **Generate my Shorts**. No manual clipping required.

First run may download a Whisper model. Processing time depends on video length and CPU speed. YouTube downloads may be unavailable due to platform restrictions or rights; only use content you have permission to process.

## Configuration

`WHISPER_MODEL=base` (default) or `small` for improved transcription at higher CPU cost; `MAX_UPLOAD_MB=1500` (default).

## Limitations before public launch

- Highlight ranking is a **heuristic** based on spoken density and reaction words, not a trained virality predictor; no actual comparison to a database of viral videos.
- Vertical cropping is center-based, not AI face/speaker tracking. Captions are grouped and subtly animated rather than fully word-by-word highlighted.
- No accounts, persistent job database, rate limits, cleanup policy, quotas, GPU workers, malware scanning, distributed queue, or cloud deployment. Do **not** expose this development server publicly without those controls.
- Long videos may take a while; exports use FFmpeg CPU encoding. URLs are restricted to YouTube domains, but production use needs additional network egress controls.
- YouTube importing is best-effort and subject to availability, terms, and rights.

This is a usable automated MVP, not a production SaaS or a guarantee of viral performance.

## Render deployment (experimental)

1. Create a GitHub repository and upload `app.py`, `requirements.txt`, `Dockerfile`, `render.yaml`, and the `static` directory to its root.
2. In Render, select **New > Blueprint**, connect that GitHub repository, and apply the `render.yaml` Blueprint.
3. Open the Render service URL after the build finishes.

**Warning:** This is an experimental, single-user prototype, not a safe public multi-user production service. It lacks authentication, quotas, job cleanup, and persistent storage. Render's free instance may run out of memory or time out when transcribing or rendering videos, and its disk is ephemeral. Do not upload private videos to a publicly accessible deployment. For reliable production use, add access controls, durable storage, background workers, and a sufficiently sized paid instance.
