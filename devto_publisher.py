#!/usr/bin/env python3
"""
Dev.to publisher — posts/updates articles via the Forem REST API.

API base: https://dev.to/api
Authentication: api-key header (not Bearer token)

Setup:
  1. Go to https://dev.to/settings/extensions → scroll to "DEV Community API Keys"
  2. Generate a key and set: export DEVTO_API_KEY=your_key
     (or add to your .env file as DEVTO_API_KEY=your_key)

Usage:
  from devto_publisher import publish_article, update_article, list_my_articles

  article_id = publish_article(
      title="My article title",
      body_markdown="# Hello\n\nContent here...",
      tags=["python", "ai", "beginners"],
      published=False,   # False = create as draft
      canonical_url=None,
      cover_image_url=None,
  )

CLI:
  python3 devto_publisher.py --list
  python3 devto_publisher.py --publish posts/my-article.md
  python3 devto_publisher.py --publish posts/my-article.md --live
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://dev.to/api"
_RATE_LIMIT_RETRY_WAIT = 60  # seconds to wait on 429


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def get_api_key() -> str:
    """
    Return the Dev.to API key.

    Lookup order:
      1. DEVTO_API_KEY environment variable
      2. .env file in the current working directory
      3. .env file in the same directory as this script

    Raises RuntimeError with a helpful message if the key is not found.
    """
    key = os.environ.get("DEVTO_API_KEY", "").strip()
    if key:
        return key

    # Search .env files
    for env_path in [Path.cwd() / ".env", Path(__file__).parent / ".env"]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == "DEVTO_API_KEY":
                    key = v.strip().strip('"').strip("'")
                    if key:
                        return key

    raise RuntimeError(
        "DEVTO_API_KEY not found.\n"
        "  1. Go to https://dev.to/settings/extensions\n"
        "  2. Scroll to 'DEV Community API Keys' and generate a key\n"
        "  3. Set it:  export DEVTO_API_KEY=your_key\n"
        "     or add  DEVTO_API_KEY=your_key  to your .env file"
    )


# ---------------------------------------------------------------------------
# Low-level HTTP helper
# ---------------------------------------------------------------------------

def _request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Make an authenticated JSON request to the Dev.to API.

    Handles 429 (rate-limit) by waiting and retrying once.
    Raises RuntimeError for 401, 422, and other HTTP errors.
    """
    key = api_key or get_api_key()
    url = f"{BASE_URL}{path}"

    body = json.dumps(payload).encode("utf-8") if payload is not None else None

    headers = {
        "api-key": key,
        "Content-Type": "application/json",
        "Accept": "application/vnd.forem.api-v1+json",
        "User-Agent": "devto-publisher/1.0 (+https://github.com/local)",
    }

    def _do_request() -> dict[str, Any]:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                err_body = exc.read().decode("utf-8")
                err_data = json.loads(err_body)
            except Exception:
                err_data = {"raw": exc.reason}

            if status == 401:
                raise RuntimeError(
                    f"401 Unauthorized — check your DEVTO_API_KEY.\n"
                    f"Details: {err_data}"
                ) from exc
            elif status == 422:
                raise RuntimeError(
                    f"422 Unprocessable Entity — validation failed.\n"
                    f"Details: {err_data}"
                ) from exc
            elif status == 429:
                # Caller handles retry
                raise exc
            else:
                raise RuntimeError(
                    f"HTTP {status} from Dev.to API ({method} {path}).\n"
                    f"Details: {err_data}"
                ) from exc

    try:
        return _do_request()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            print(
                f"Rate limited by Dev.to (429). Waiting {_RATE_LIMIT_RETRY_WAIT}s before retrying...",
                file=sys.stderr,
            )
            time.sleep(_RATE_LIMIT_RETRY_WAIT)
            return _do_request()  # second attempt — let any error propagate
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def publish_article(
    title: str,
    body_markdown: str,
    tags: list[str] | None = None,
    published: bool = False,
    canonical_url: str | None = None,
    cover_image_url: str | None = None,
    series: str | None = None,
    description: str | None = None,
) -> int:
    """
    Create a new article on Dev.to.

    Parameters
    ----------
    title:           Article headline (required).
    body_markdown:   Full article body in Markdown (required).
    tags:            Up to 4 tags (strings). Dev.to normalises to lowercase,
                     no spaces — e.g. ["python", "ai", "beginners"].
    published:       True to publish immediately; False (default) to save as draft.
    canonical_url:   Original URL if cross-posting from another site.
    cover_image_url: URL of the cover/hero image.
    series:          Series name — Dev.to groups articles with the same series string.
    description:     Short description / subtitle (shown in listing cards).

    Returns
    -------
    int  The article id assigned by Dev.to (use for update_article).
    """
    if not title:
        raise ValueError("title is required")
    if not body_markdown:
        raise ValueError("body_markdown is required")

    # Dev.to accepts max 4 tags; silently truncate with a warning
    clean_tags: list[str] = []
    if tags:
        clean_tags = [re.sub(r"[^a-z0-9]", "", t.lower().strip()) for t in tags if t.strip()]
        if len(clean_tags) > 4:
            print(
                f"Warning: Dev.to supports at most 4 tags; dropping: {clean_tags[4:]}",
                file=sys.stderr,
            )
            clean_tags = clean_tags[:4]

    article: dict[str, Any] = {
        "title": title,
        "body_markdown": body_markdown,
        "published": published,
        "tags": clean_tags,
    }
    if canonical_url:
        article["canonical_url"] = canonical_url
    if cover_image_url:
        article["cover_image"] = cover_image_url
    if series:
        article["series"] = series
    if description:
        article["description"] = description

    payload = {"article": article}

    result = _request("POST", "/articles", payload=payload)

    article_id: int = result["id"]
    status = "published" if result.get("published") else "draft"
    url = result.get("url") or result.get("path", "")
    print(f"Created article [{status}] id={article_id}  {url}")
    return article_id


def update_article(article_id: int, **kwargs: Any) -> dict[str, Any]:
    """
    Update an existing article.

    Pass any subset of the fields accepted by publish_article as keyword args:
      update_article(123, published=True)
      update_article(123, title="New title", tags=["python"])

    Returns the full updated article dict from the API.
    """
    if not article_id:
        raise ValueError("article_id is required")

    # Normalise tags if present
    if "tags" in kwargs and kwargs["tags"]:
        raw = kwargs["tags"]
        clean = [re.sub(r"[^a-z0-9]", "", t.lower().strip()) for t in raw if t.strip()]
        if len(clean) > 4:
            print(
                f"Warning: Dev.to supports at most 4 tags; dropping: {clean[4:]}",
                file=sys.stderr,
            )
            clean = clean[:4]
        kwargs["tags"] = clean

    # Map cover_image_url → cover_image for the API
    if "cover_image_url" in kwargs:
        kwargs["cover_image"] = kwargs.pop("cover_image_url")

    payload = {"article": kwargs}
    result = _request("PUT", f"/articles/{article_id}", payload=payload)

    status = "published" if result.get("published") else "draft"
    url = result.get("url") or result.get("path", "")
    print(f"Updated article [{status}] id={article_id}  {url}")
    return result


def list_my_articles(per_page: int = 30) -> list[dict[str, Any]]:
    """
    Return a list of the authenticated user's articles.

    Each entry is a dict with at minimum: id, title, published, url.

    Parameters
    ----------
    per_page: How many articles to fetch (max 1000, default 30).
    """
    per_page = min(max(1, per_page), 1000)
    result = _request("GET", f"/articles/me/all?per_page={per_page}")
    # API returns a list directly for this endpoint
    if isinstance(result, list):
        return result
    # Fallback if wrapped
    return result.get("articles", result)


# ---------------------------------------------------------------------------
# State file — tracks filename → Dev.to article_id / url / published
# ---------------------------------------------------------------------------

STATE_FILE = "devto_state.json"


def _state_path(directory: Path) -> Path:
    return directory / STATE_FILE


def load_state(directory: Path) -> dict[str, Any]:
    p = _state_path(directory)
    return json.loads(p.read_text()) if p.exists() else {}


def save_state(directory: Path, state: dict[str, Any]) -> None:
    _state_path(directory).write_text(json.dumps(state, indent=2))


def _patch_frontmatter_published(path: Path, published: bool) -> None:
    """Toggle the published field in frontmatter using a safe Python rewrite."""
    text = path.read_text(encoding="utf-8")
    new_val = "true" if published else "false"
    old_val = "false" if published else "true"
    patched = re.sub(
        rf"^(published:\s*){old_val}",
        rf"\g<1>{new_val}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if patched != text:
        path.write_text(patched, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _parse_markdown_file(path: Path) -> tuple[str, str, list[str]]:
    """
    Parse a markdown file produced by generate_blog.py.

    Title:   first line starting with '# '
    Tags:    line matching '**Tags:** tag1, tag2, tag3' (case-insensitive)
    Body:    full file content (title stays in the body so Dev.to renders it)

    Returns (title, body_markdown, tags).
    """
    text = path.read_text(encoding="utf-8")

    # Extract title: frontmatter first, then first H1 outside a code fence
    title = ""
    # Check frontmatter block
    fm_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).splitlines():
            if line.startswith("title:"):
                title = line[len("title:"):].strip().strip('"').strip("'")
                break
    if not title:
        in_fence = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                continue
            if not in_fence and stripped.startswith("# "):
                title = stripped[2:].strip()
                break
    if not title:
        title = path.stem.replace("-", " ").title()

    # Extract tags: frontmatter first, then **Tags:** footer
    tags: list[str] = []
    if fm_match:
        for line in fm_match.group(1).splitlines():
            if line.startswith("tags:"):
                raw = line[len("tags:"):].strip()
                tags = [t.strip() for t in raw.split(",") if t.strip()]
                break
    if not tags:
        tag_match = re.search(r"\*\*Tags:\*\*\s*(.+)", text, re.IGNORECASE)
        if tag_match:
            raw_tags = tag_match.group(1).strip()
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

    return title, text, tags


def pull_article(article_id: int, output_file: Path) -> None:
    """
    Fetch body_markdown for a draft or published article and write it to a local file.

    Uses /articles/me/unpublished for drafts (published articles 404 on that endpoint,
    so falls back to /articles/{id} for published ones).
    """
    # Try drafts first
    drafts = _request("GET", "/articles/me/unpublished?per_page=1000")
    if isinstance(drafts, list):
        match = next((a for a in drafts if a["id"] == article_id), None)
        if match:
            body = match["body_markdown"]
            output_file.write_text(body, encoding="utf-8")
            print(f"Pulled draft [{match['title']}] → {output_file}  ({len(body)} chars)")
            return

    # Fall back to published endpoint
    data = _request("GET", f"/articles/{article_id}")
    body = data["body_markdown"]  # type: ignore[index]
    output_file.write_text(body, encoding="utf-8")
    print(f"Pulled published [{data['title']}] → {output_file}  ({len(body)} chars)")  # type: ignore[index]


def _cmd_list() -> None:
    articles = list_my_articles(per_page=100)
    if not articles:
        print("No articles found.")
        return
    print(f"{'ID':>10}  {'ST':>2}  {'Title'}")
    print("-" * 70)
    for a in articles:
        status = "PB" if a.get("published") else "DR"
        print(f"{a['id']:>10}  {status}  {a.get('title', '(untitled)')}")
        if a.get("url"):
            print(f"{'':>14}{a['url']}")


def _cmd_publish(file: str, live: bool, canonical_url: str | None = None) -> None:
    path = Path(file).resolve()
    if not path.exists():
        print(f"File not found: {file}", file=sys.stderr)
        sys.exit(1)

    # Patch frontmatter published flag before reading body
    if live:
        _patch_frontmatter_published(path, published=True)

    title, body, tags = _parse_markdown_file(path)
    state = load_state(path.parent)
    existing = state.get(path.name)

    print(f"{'Updating' if existing else 'Creating'}: {title!r}")
    print(f"Tags:  {tags}")
    print(f"Mode:  {'LIVE' if live else 'draft'}")

    if existing:
        result = update_article(
            existing["article_id"],
            title=title,
            body_markdown=body,
            tags=tags[:4],
            published=live,
            **({"canonical_url": canonical_url} if canonical_url else {}),
        )
        url = result.get("url") or existing.get("url", "")
    else:
        article_id = publish_article(
            title=title,
            body_markdown=body,
            tags=tags[:4],
            published=live,
            canonical_url=canonical_url,
        )
        url = ""
        result = {"id": article_id, "published": live, "url": ""}

    state[path.name] = {
        "article_id": result.get("id") or (existing["article_id"] if existing else 0),
        "title": title,
        "published": live or bool(result.get("published")),
        "url": result.get("url") or url,
    }
    save_state(path.parent, state)


def _cmd_push_all(directory: str, live: bool, canonical_url: str | None = None) -> None:
    """Push all article-*.md files in directory, using state to create or update."""
    d = Path(directory)
    files = sorted(d.glob("article-*.md"))
    if not files:
        print(f"No article-*.md files found in {d}", file=sys.stderr)
        sys.exit(1)
    for f in files:
        print(f"\n── {f.name}")
        _cmd_publish(str(f), live=live, canonical_url=canonical_url)


def _cmd_pull_all(directory: str) -> None:
    """Pull all articles tracked in state back to local files."""
    d = Path(directory)
    state = load_state(d)
    if not state:
        print(f"No state file found in {d}. Push articles first.", file=sys.stderr)
        sys.exit(1)
    for filename, entry in state.items():
        out = d / filename
        pull_article(entry["article_id"], out)
        # Re-strip any drift in the series footer
        text = out.read_text(encoding="utf-8")
        out.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dev.to publisher — post markdown articles to Dev.to via the Forem API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--list", action="store_true", help="List your articles (drafts + published)")
    parser.add_argument("--publish", metavar="FILE", help="Push a single markdown file (create or update via state)")
    parser.add_argument("--push-all", metavar="DIR", help="Push all article-*.md files in DIR (create or update via state)")
    parser.add_argument("--pull", metavar="ID", type=int, help="Pull article by id to --output FILE")
    parser.add_argument("--pull-all", metavar="DIR", help="Pull all articles tracked in DIR state back to local files")
    parser.add_argument("--output", metavar="FILE", help="Output file path for --pull")
    parser.add_argument("--live", action="store_true", help="Publish immediately (public) instead of draft")
    parser.add_argument("--canonical-url", metavar="URL", help="Set canonical URL")
    parser.add_argument(
        "--update", metavar="ID", type=int,
        help="Override article id for --publish (normally resolved from state automatically)",
    )

    args = parser.parse_args()

    if args.pull:
        if not args.output:
            print("--pull requires --output FILE", file=sys.stderr)
            sys.exit(1)
        pull_article(args.pull, Path(args.output))
    elif args.pull_all:
        _cmd_pull_all(args.pull_all)
    elif args.list:
        _cmd_list()
    elif args.publish:
        # Manual --update override: inject into state before pushing
        if args.update:
            path = Path(args.publish).resolve()
            state = load_state(path.parent)
            if path.name not in state:
                state[path.name] = {"article_id": args.update, "title": "", "published": False, "url": ""}
                save_state(path.parent, state)
        _cmd_publish(args.publish, args.live, canonical_url=args.canonical_url)
    elif args.push_all:
        _cmd_push_all(args.push_all, args.live, canonical_url=args.canonical_url)
    elif args.update:
        if args.live:
            update_article(args.update, published=True)
        else:
            print("Specify --live to publish, or --publish FILE to update content.", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
