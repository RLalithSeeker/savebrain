"""
media.py -- turning a post's pixels and audio into text.

Two paths for each job, chosen in config.json:

  ocr:        "cloud" (provider vision model)  | "local" (easyocr)          | "off"
  transcribe: "cloud" (provider Whisper API)   | "local" (faster-whisper)   | "off"

"cloud" is the default on purpose. The local path needs torch, which is where
most first-time setups die. Nothing here imports torch unless you ask for it.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
import urllib.request

from . import llm

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# A 900px slide costs roughly 6k vision tokens and free tiers sit around 8k
# tokens/minute, so batches of 2 are what actually get through. Raise it if you
# are on a paid tier; lower it if you keep seeing rate limits.
BATCH_IMAGES = 2
MAX_AUDIO_MB = 24         # provider upload cap for audio
SLIDE_MAX_PX = 900        # vision cost scales with area; slides stay legible here

_easyocr_reader = None
_whisper = None


def _download(url: str, suffix: str, timeout: int = 30) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f)
    return path


def _shrink(path: str, max_px: int = SLIDE_MAX_PX) -> None:
    """Downscale in place. Vision cost scales with resolution; slides are legible at 1024."""
    try:
        from PIL import Image
    except ImportError:
        return
    try:
        im = Image.open(path).convert("RGB")
        im.thumbnail((max_px, max_px))
        im.save(path, "JPEG", quality=85)
    except Exception:
        pass


def image_to_data_url(url: str) -> str:
    path = _download(url, ".jpg", timeout=20)
    try:
        _shrink(path)
        with open(path, "rb") as f:
            return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    finally:
        _safe_rm(path)


def _safe_rm(path):
    try:
        os.remove(path)
    except Exception:
        pass


# ------------------------------------------------------------------ OCR
def _local_reader(lang: str):
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr  # noqa: F401  (heavy; only imported when ocr=local)
        try:
            import torch
            gpu = torch.cuda.is_available()
        except Exception:
            gpu = False
        print("   loading easyocr (gpu=%s), first run downloads ~100MB..." % gpu)
        _easyocr_reader = easyocr.Reader([lang or "en"], gpu=gpu)
    return _easyocr_reader


def _ocr_local(image_urls: list, lang: str) -> str:
    out = []
    for i, url in enumerate(image_urls, 1):
        path = None
        try:
            path = _download(url, ".jpg", timeout=20)
            _shrink(path, 1600)
            lines = _local_reader(lang).readtext(path, detail=0, paragraph=True)
            text = "\n".join(lines).strip()
            if text:
                out.append("[Slide %d]\n%s" % (i, text))
        except Exception as e:
            print("   slide %d: local OCR failed (%s)" % (i, str(e)[:80]))
        finally:
            if path:
                _safe_rm(path)
    return "\n\n".join(out)


def _ocr_cloud(image_urls: list, cfg: dict) -> str:
    chunks = []
    for start in range(0, len(image_urls), BATCH_IMAGES):
        batch = image_urls[start:start + BATCH_IMAGES]
        try:
            data_urls = [image_to_data_url(u) for u in batch]
        except Exception as e:
            print("   slide download failed (%s) -- media links expire a few hours "
                  "after a scrape; re-scrape and ingest the same day" % str(e)[:80])
            continue
        try:
            chunks.append(llm.vision_read(data_urls, cfg, start_idx=start + 1))
        except llm.LLMError as e:
            print("   vision OCR failed on slides %d-%d: %s"
                  % (start + 1, start + len(batch), str(e)[:120]))
    return "\n\n".join(c for c in chunks if c)


def read_slides(image_urls: list, cfg: dict) -> str:
    """Text of every slide, labelled [Slide N]. Empty string when OCR is off or fails."""
    mode = (cfg.get("ocr") or "cloud").lower()
    if mode == "off" or not image_urls:
        return ""
    if mode == "local":
        try:
            return _ocr_local(image_urls, cfg.get("language", "en"))
        except ImportError:
            print("   easyocr not installed -- falling back to cloud OCR "
                  "(pip install -r requirements-local.txt to use the local path)")
    return _ocr_cloud(image_urls, cfg)


# ------------------------------------------------------------ transcription
def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or ""


def _compress_audio(video_path: str) -> str:
    """Strip to a small mono mp3 so long reels fit the upload cap. Needs ffmpeg."""
    ff = _ffmpeg()
    if not ff:
        return ""
    out = video_path + ".mp3"
    cmd = [ff, "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", out]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    except Exception:
        return ""
    return out if os.path.exists(out) else ""


def _transcribe_local(path: str, cfg: dict) -> str:
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel  # heavy; only when transcribe=local
        try:
            import torch
            dev, ctype = ("cuda", "float16") if torch.cuda.is_available() else ("cpu", "int8")
        except Exception:
            dev, ctype = ("cpu", "int8")
        size = (cfg.get("llm") or {}).get("local_whisper_size") or "small.en"
        print("   loading faster-whisper %s on %s..." % (size, dev))
        _whisper = WhisperModel(size, device=dev, compute_type=ctype)
    segments, _info = _whisper.transcribe(path, language=cfg.get("language") or "en")
    return " ".join(s.text.strip() for s in segments).strip()


def transcribe(video_url: str, cfg: dict) -> str:
    """Spoken words of a video post. Empty string when off, unavailable, or it fails."""
    mode = (cfg.get("transcribe") or "cloud").lower()
    if mode == "off" or not video_url:
        return ""
    path = None
    extra = None
    try:
        path = _download(video_url, ".mp4", timeout=60)
        if mode == "local":
            try:
                return _transcribe_local(path, cfg)
            except ImportError:
                print("   faster-whisper not installed -- using cloud transcription")

        size_mb = os.path.getsize(path) / 1e6
        target = path
        if size_mb > MAX_AUDIO_MB:
            extra = _compress_audio(path)
            if not extra:
                print("   video is %.0fMB (cap %dMB) and ffmpeg is not installed -- "
                      "skipping transcript" % (size_mb, MAX_AUDIO_MB))
                return ""
            target = extra
        return llm.transcribe_file(target, cfg)
    except llm.LLMError as e:
        print("   transcription failed: %s" % str(e)[:140])
        return ""
    except Exception as e:
        print("   video download failed: %s" % str(e)[:140])
        return ""
    finally:
        if path:
            _safe_rm(path)
        if extra:
            _safe_rm(extra)
