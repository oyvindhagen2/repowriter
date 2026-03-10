#!/usr/bin/env python3
"""
Medium publisher — posts/updates articles via the Medium Integration API.

API base: https://api.medium.com/v1
Authentication: Bearer token (Integration Token)

Setup:
  1. Go to https://medium.com/me/settings → "Integration tokens"
  2. Generate a token and set: export MEDIUM_INTEGRATION_TOKEN=your_token
     (or add to your .env file as MEDIUM_INTEGRATION_TOKEN=your_token)

Usage:
  from medium_publisher import publish_article, get_me

  article_id = publish_article(
      title="My article title",
      body_markdown="# Hello\n\nContent here...",
      tags=["python", "ai"],
      publish_status="draft",   # "draft" | "unlisted" | "public"
      canonical_url=None,
  )

CLI:
  python3 medium_publisher.py --me
  python3 medium_publisher.py --publish posts/my-article.md
  python3 medium_publisher.py --publish posts/my-article.md --live
  python3 medium_publisher.py --publish posts/my-article.md --unlisted
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

BASE_URL = "https://api.medium.com/v1"
_RATE_LIMIT_RETRY_WAIT = 60  # seconds to wait on 429


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def get_integration_token() -> str:
    """
    Return the Medium Integration Token.

    Lookup order:
      1. MEDIUM_INTEGRATION_TOKEN environment variable
      2. .env file in the current working directory
      3. .env file in the same directory as this script

    Raises RuntimeError with a helpful message if the token is not found.
    """
    token = os.environ.get("MEDIUM_INTEGRATION_TOKEN", "").strip()
    if token:
        return token

    for env_path in [Path.cwd() / ".env", Path(__file__).parent / ".env"]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == "MEDIUM_INTEGRATION_TOKEN":
                    token = v.strip().strip('"').strip("'")
                    if token:
                        return token

    raise RuntimeError(
        "MEDIUM_INTEGRATION_TOKEN not found.\n"
        "  1. Go to https://medium.com/me/settings\n"
        "  2. Scroll to 'Integration tokens' and generate a token\n"
        "  3. Set it:  export MEDIUM_INTEGRATION_TOKEN=your_token\n"
        "     or add  MEDIUM_INTEGRATION_TOKEN=your_token  to your .env file"
    )


# ---------------------------------------------------------------------------
# Low-level HTTP helper
# ---------------------------------------------------------------------------

def _request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any] | list[Any]:
    """
    Make an authenticated JSON request to the Medium API.

    Handles 429 (rate-limit) by waiting and retrying once.
    Raises RuntimeError for 401, 422, and other HTTP errors.
    """
    tok = token or get_integration_token()
    url = f"{BASE_URL}{path}"

    body = json.dumps(payload).encode("utf-8") if payload is not None else None

    headers = {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Charset": "utf-8",
        "User-Agent": "medium-publisher/1.0",
    }

    def _do_request() -> dict[str, Any] | list[Any]:
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
                    f"401 Unauthorized — check your MEDIUM_INTEGRATION_TOKEN.\n"
                    f"Details: {err_data}"
                ) from exc
            elif status == 403:
                raise RuntimeError(
                    f"403 Forbidden — your token may not have permission for this action.\n"
                    f"Details: {err_data}"
                ) from exc
            elif status == 429:
                raise exc
            else:
                raise RuntimeError(
                    f"HTTP {status} from Medium API ({method} {path}).\n"
                    f"Details: {err_data}"
                ) from exc

    try:
        return _do_request()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            print(
                f"Rate limited by Medium (429). Waiting {_RATE_LIMIT_RETRY_WAIT}s before retrying...",
                file=sys.stderr,
            )
            time.sleep(_RATE_LIMIT_RETRY_WAIT)
            return _do_request()
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_me() -> dict[str, Any]:
    """
    Return the authenticated user's profile.

    Includes: id, username, name, url, imageUrl.
    """
    result = _request("GET", "/me")
    return result.get("data", result)  # type: ignore[return-value]


def publish_article(
    title: str,
    body_markdown: str,
    tags: list[str] | None = None,
    publish_status: str = "draft",
    canonical_url: str | None = None,
    license: str = "all-rights-reserved",
    notify_followers: bool = False,
) -> str:
    """
    Create a new post on Medium.

    Parameters
    ----------
    title:            Post headline (required).
    body_markdown:    Full post body in Markdown (required).
    tags:             Up to 5 tags. Medium normalises them.
    publish_status:   "draft" (default) | "unlisted" | "public"
    canonical_url:    Original URL if cross-posting from another site.
    license:          "all-rights-reserved" (default) | "cc-40-by" | etc.
    notify_followers: Whether to notify followers (default False for drafts).

    Returns
    -------
    str  The post URL assigned by Medium.
    """
    if not title:
        raise ValueError("title is required")
    if not body_markdown:
        raise ValueError("body_markdown is required")

    if publish_status not in ("draft", "unlisted", "public"):
        raise ValueError(f"publish_status must be 'draft', 'unlisted', or 'public'; got {publish_status!r}")

    # Get user ID first
    me = get_me()
    user_id = me.get("id")
    if not user_id:
        raise RuntimeError(f"Could not determine user ID from /me response: {me}")

    clean_tags: list[str] = []
    if tags:
        clean_tags = [t.strip() for t in tags if t.strip()]
        if len(clean_tags) > 5:
            print(
                f"Warning: Medium supports at most 5 tags; dropping: {clean_tags[5:]}",
                file=sys.stderr,
            )
            clean_tags = clean_tags[:5]

    payload: dict[str, Any] = {
        "title": title,
        "contentFormat": "markdown",
        "content": body_markdown,
        "publishStatus": publish_status,
        "license": license,
        "notifyFollowers": notify_followers,
    }
    if clean_tags:
        payload["tags"] = clean_tags
    if canonical_url:
        payload["canonicalUrl"] = canonical_url

    result = _request("POST", f"/users/{user_id}/posts", payload=payload)
    data = result.get("data", result) if isinstance(result, dict) else result  # type: ignore[union-attr]

    url = data.get("url", "")  # type: ignore[union-attr]
    post_id = data.get("id", "")  # type: ignore[union-attr]
    print(f"Created post [{publish_status}] id={post_id}  {url}")
    return url


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _parse_markdown_file(path: Path) -> tuple[str, str, list[str]]:
    """
    Parse a markdown file produced by generate_blog.py.

    Title:   first line starting with '# '
    Tags:    line matching '**Tags:** tag1, tag2, tag3' (case-insensitive)
    Body:    full file content

    Returns (title, body_markdown, tags).
    """
    text = path.read_text(encoding="utf-8")

    title = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            break
    if not title:
        raise ValueError(f"No '# Title' line found in {path}")

    tags: list[str] = []
    tag_match = re.search(r"\*\*Tags:\*\*\s*(.+)", text, re.IGNORECASE)
    if tag_match:
        raw_tags = tag_match.group(1).strip()
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

    return title, text, tags


def _cmd_me() -> None:
    me = get_me()
    print(f"User:     {me.get('name')} (@{me.get('username')})")
    print(f"ID:       {me.get('id')}")
    print(f"URL:      {me.get('url')}")


def _cmd_publish(file: str, publish_status: str, canonical_url: str | None = None) -> None:
    path = Path(file)
    if not path.exists():
        print(f"File not found: {file}", file=sys.stderr)
        sys.exit(1)

    title, body, tags = _parse_markdown_file(path)
    print(f"Publishing: {title!r}")
    print(f"Tags:       {tags}")
    print(f"Status:     {publish_status}")
    if canonical_url:
        print(f"Canonical:  {canonical_url}")

    url = publish_article(
        title=title,
        body_markdown=body,
        tags=tags,
        publish_status=publish_status,
        canonical_url=canonical_url,
    )
    print(f"Done. url={url}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Medium publisher — post markdown articles to Medium via the Integration API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--me", action="store_true", help="Show authenticated user info")
    parser.add_argument("--publish", metavar="FILE", help="Publish a markdown file as a draft")
    parser.add_argument("--live", action="store_true", help="Publish immediately (public) instead of draft")
    parser.add_argument("--unlisted", action="store_true", help="Publish as unlisted instead of draft")
    parser.add_argument(
        "--canonical-url", metavar="URL",
        help="Set canonical URL (use when cross-posting — points back to the original)"
    )

    args = parser.parse_args()

    if args.me:
        _cmd_me()
    elif args.publish:
        if args.live:
            status = "public"
        elif args.unlisted:
            status = "unlisted"
        else:
            status = "draft"
        _cmd_publish(args.publish, status, canonical_url=args.canonical_url)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
