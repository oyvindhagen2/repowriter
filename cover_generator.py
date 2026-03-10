#!/usr/bin/env python3
"""
Cover image generator — generates 1000x420 cover images for Dev.to articles,
uploads to Dev.to's image CDN, and updates frontmatter.

Setup:
  GOOGLE_AI_API_KEY  — Google AI Studio key (aistudio.google.com) [optional, falls back to Pollinations]
  DEVTO_API_KEY      — Dev.to API key

Usage:
  python3 cover_generator.py --dir posts/arctic_digital                # all articles
  python3 cover_generator.py --file posts/arctic_digital/article-01-*.md  # one article
  python3 cover_generator.py --dir posts/arctic_digital --dry-run       # preview prompts only
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

IMAGE_MODEL    = "gemini-2.5-flash-image"   # same model as Dev.to's built-in generator (paid)
IMAGEN_MODEL   = "imagen-4.0-generate-001"  # Imagen 4 (paid)
GEMINI_BASE    = "https://generativelanguage.googleapis.com/v1beta"
POLLINATIONS   = "https://image.pollinations.ai/prompt"  # free, no key, Flux model
DEVTO_API      = "https://dev.to/api"
CATBOX_API     = "https://catbox.moe/user/api.php"  # free anonymous file hosting


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------

def _load_env():
    for candidate in [Path(__file__).parent / ".env", Path.home() / ".env"]:
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k = k.strip(); v = v.strip().strip('"').strip("'")
                    if k not in os.environ:
                        os.environ[k] = v


def _require(key: str) -> str:
    v = os.environ.get(key, "").strip()
    if not v:
        print(f"Missing {key} — add it to .env", file=sys.stderr)
        sys.exit(1)
    return v


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

def _read_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    result: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _set_frontmatter_field(path: Path, field: str, value: str) -> None:
    """Set or add a field in the frontmatter block using a safe Python rewrite."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^(---\n)(.*?)(\n---\n)", text, re.DOTALL)
    if not m:
        # No frontmatter — prepend
        path.write_text(f"---\n{field}: {value}\n---\n{text}", encoding="utf-8")
        return

    fm_lines = m.group(2).splitlines()
    replaced = False
    new_lines = []
    for line in fm_lines:
        if line.startswith(f"{field}:"):
            new_lines.append(f"{field}: {value}")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f"{field}: {value}")

    new_fm = m.group(1) + "\n".join(new_lines) + m.group(3)
    path.write_text(new_fm + text[m.end():], encoding="utf-8")


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

STYLE_SUFFIX = (
    "retro-tech developer blog cover, dark background, geometric shapes, "
    "abstract data art, no text, no letters"
)


def build_prompt(article_num: int, title: str, description: str = "") -> str:
    """
    Build an image generation prompt from article metadata.
    Uses the description if available; falls back to the title.
    Override by adding an 'image_prompt' field to your frontmatter.
    """
    subject = description if description else title
    return f"abstract tech art inspired by: {subject}. {STYLE_SUFFIX}"


# ---------------------------------------------------------------------------
# Imagen 3 — image generation
# ---------------------------------------------------------------------------

def generate_image(prompt: str, api_key: str, engine: str = "auto", seed: int = 42) -> bytes:
    """
    Generate an image. Engine options:
      "pollinations"  — free, no billing, Flux model (default when no paid key)
      "imagen4"       — Imagen 4 via Google AI (requires billing enabled)
      "gemini"        — gemini-2.5-flash-image (requires billing enabled)
      "auto"          — try Imagen 4, fall back to Pollinations
    """
    if engine == "pollinations":
        return _generate_pollinations(prompt, seed=seed)
    if engine == "gemini":
        return _generate_gemini_image(prompt, api_key)
    if engine == "imagen4":
        return _generate_imagen4(prompt, api_key)
    # auto: try paid first, fall back gracefully
    if api_key:
        try:
            return _generate_imagen4(prompt, api_key)
        except Exception as e:
            print(f"  Imagen 4 unavailable ({type(e).__name__}), using Pollinations (free)...")
    return _generate_pollinations(prompt, seed=seed)


def _generate_pollinations(prompt: str, seed: int = 42) -> bytes:
    """
    Free image generation via Pollinations.ai (Flux model).
    No API key required. Returns PNG bytes. Exact 1000x420 output.
    Uses curl subprocess to avoid urllib bot detection.
    """
    import urllib.parse
    short_prompt = prompt[:200]
    encoded = urllib.parse.quote(short_prompt, safe="")
    url = f"{POLLINATIONS}/{encoded}?width=1000&height=420&model=flux&nologo=true&seed={seed}"

    for attempt in range(5):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                ["curl", "-s", "-L", "--max-time", "90", "-o", tmp_path, url],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"curl failed: {result.stderr}")
            data = Path(tmp_path).read_bytes()
            if len(data) < 1000:
                # Likely an error page, not an image
                err = data.decode(errors="replace")
                if attempt < 4:
                    wait = 20 + attempt * 20
                    print(f"  Pollinations bad response ({len(data)}b), retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"Pollinations returned non-image: {err[:200]}")
            return data
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    raise RuntimeError("Pollinations: max retries exceeded")


def _generate_gemini_image(prompt: str, api_key: str) -> bytes:
    """Use gemini-2.5-flash-image via generateContent with IMAGE response modality."""
    url = f"{GEMINI_BASE}/models/{IMAGE_MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        err = exc.read().decode()
        raise RuntimeError(f"Gemini image error {exc.code}: {err}") from exc

    # Extract first image part
    for part in data["candidates"][0]["content"]["parts"]:
        if "inlineData" in part:
            return base64.b64decode(part["inlineData"]["data"])
    raise RuntimeError("No image in Gemini response")


def _generate_imagen4(prompt: str, api_key: str) -> bytes:
    """Use Imagen 4 via predict endpoint."""
    url = f"{GEMINI_BASE}/models/{IMAGEN_MODEL}:predict?key={api_key}"
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "16:9",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        err = exc.read().decode()
        raise RuntimeError(f"Imagen 4 error {exc.code}: {err}") from exc

    b64 = data["predictions"][0]["bytesBase64Encoded"]
    return base64.b64decode(b64)


# ---------------------------------------------------------------------------
# Image hosting — catbox.moe (free, anonymous, permanent)
# ---------------------------------------------------------------------------

def upload_image(image_bytes: bytes, filename: str) -> str:
    """
    Upload image to catbox.moe (free anonymous hosting) and return the URL.
    No account or API key required.
    """
    boundary = "----FormBoundary" + base64.b64encode(os.urandom(12)).decode().replace("=", "")
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="reqtype"\r\n\r\n'
        f"fileupload\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="fileToUpload"; filename="{filename}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + image_bytes + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        CATBOX_API,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "cover-generator/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            url = resp.read().decode().strip()
    except urllib.error.HTTPError as exc:
        err = exc.read().decode()
        raise RuntimeError(f"catbox.moe upload error {exc.code}: {err}") from exc

    if not url.startswith("https://"):
        raise RuntimeError(f"Unexpected catbox response: {url}")
    return url


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def process_article(path: Path, api_key: str, dry_run: bool = False, engine: str = "auto", force: bool = False) -> str | None:
    """Generate cover image for one article. Returns the cover URL or None on dry-run."""
    fm = _read_frontmatter(path)
    title = fm.get("title", path.stem.replace("-", " ").title())
    description = fm.get("description", "")

    # Parse article number from filename (used as seed; 0 if not present)
    m = re.match(r"article-(\d+)-", path.name)
    article_num = int(m.group(1)) if m else 0

    # Allow per-article prompt override via frontmatter
    if fm.get("image_prompt"):
        prompt = f"{fm['image_prompt']}. {STYLE_SUFFIX}"
    else:
        prompt = build_prompt(article_num, title, description)
    print(f"\n[{path.name}]")
    print(f"  Title:  {title}")
    print(f"  Prompt: {prompt[:100]}...")

    if dry_run:
        return None

    # Skip if cover_image already set in frontmatter (unless forced)
    existing_url = fm.get("cover_image", "")
    local_path_check = path.parent / "covers" / f"article-{article_num:02d}.png"
    if not force and existing_url and existing_url.startswith("https://") and local_path_check.exists():
        print(f"  Skipping — cover already exists: {existing_url}")
        return existing_url

    print(f"  Generating image ({engine})...")
    image_bytes = generate_image(prompt, api_key, engine=engine, seed=article_num * 100)

    filename = f"article-{article_num:02d}.png"

    # Save locally
    local_dir = path.parent / "covers"
    local_dir.mkdir(exist_ok=True)
    local_path = local_dir / filename
    local_path.write_bytes(image_bytes)
    print(f"  Saved locally → {local_path}")

    # Upload to catbox.moe (free, anonymous, permanent)
    print(f"  Uploading {filename} to catbox.moe...")
    url = upload_image(image_bytes, filename)

    # Update frontmatter
    _set_frontmatter_field(path, "cover_image", url)
    print(f"  ✓ cover_image → {url}")
    return url


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    _load_env()
    parser = argparse.ArgumentParser(description="Generate Dev.to cover images via Imagen 3")
    parser.add_argument("--dir",  metavar="DIR",  help="Process all article-*.md in this directory")
    parser.add_argument("--file", metavar="FILE", help="Process a single article file")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts only, don't generate")
    parser.add_argument(
        "--engine", choices=["auto", "pollinations", "imagen4", "gemini"],
        default="auto",
        help="Image engine: auto (default), pollinations (free), imagen4/gemini (require billing)",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate even if cover already exists")
    args = parser.parse_args()

    if not args.dir and not args.file:
        parser.print_help()
        sys.exit(1)

    if args.dry_run:
        print("DRY RUN — prompts only, no images generated\n")

    files: list[Path] = []
    if args.file:
        files = [Path(args.file)]
    else:
        files = sorted(Path(args.dir).glob("article-*.md"))

    for i, f in enumerate(files):
        if i > 0:
            time.sleep(30)  # Pollinations rate limit
        process_article(
            f,
            api_key=os.environ.get("GOOGLE_AI_API_KEY", ""),
            dry_run=args.dry_run,
            engine=args.engine,
            force=args.force,
        )

    if not args.dry_run:
        print(f"\nDone — {len(files)} cover(s) generated and frontmatter updated.")
        print("Run push-all to sync to Dev.to.")


if __name__ == "__main__":
    main()
