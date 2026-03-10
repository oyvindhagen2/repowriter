"""
renderer.py — Convert Dev.to article markdown to HTML.

Exposes a single public function:

    render(markdown_text: str) -> tuple[dict, str]

Returns (frontmatter_dict, html_body).
No external dependencies — pure stdlib only.
"""

from __future__ import annotations

import html
import re
from typing import Any


# ---------------------------------------------------------------------------
# 1. YAML frontmatter parser (stdlib only)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)

_FRONTMATTER_KEYS = ("title", "description", "tags", "series", "cover_image", "published")


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """
    Strip the leading YAML frontmatter block and return (dict, remaining_body).

    Only the keys listed in _FRONTMATTER_KEYS are extracted; everything else is
    ignored.  Handles scalar strings, booleans, and simple inline lists
    (e.g.  ``tags: [python, django]``) as well as multi-line block lists.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {k: None for k in _FRONTMATTER_KEYS}, text

    yaml_block = match.group(1)
    body = text[match.end():]

    fm: dict[str, Any] = {k: None for k in _FRONTMATTER_KEYS}

    current_key: str | None = None
    list_buffer: list[str] = []

    def _flush_list() -> None:
        if current_key and list_buffer:
            fm[current_key] = list_buffer[:]

    scalar_re = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)')
    list_item_re = re.compile(r'^\s+-\s+(.*)')

    for line in yaml_block.splitlines():
        item_m = list_item_re.match(line)
        scalar_m = scalar_re.match(line)

        if item_m:
            list_buffer.append(_yaml_scalar(item_m.group(1).strip()))
        elif scalar_m:
            _flush_list()
            list_buffer = []
            key = scalar_m.group(1)
            value_str = scalar_m.group(2).strip()
            current_key = key if key in _FRONTMATTER_KEYS else None

            if current_key is None:
                continue

            if value_str == "":
                fm[current_key] = None  # may be overwritten by _flush_list
            elif value_str.startswith("[") and value_str.endswith("]"):
                inner = value_str[1:-1]
                fm[current_key] = [
                    _yaml_scalar(s.strip()) for s in inner.split(",") if s.strip()
                ]
            else:
                fm[current_key] = _yaml_scalar(value_str)
        else:
            if line.strip() == "":
                _flush_list()
                list_buffer = []
                current_key = None

    _flush_list()

    return fm, body


def _yaml_scalar(value: str) -> Any:
    """Convert a raw YAML scalar string to an appropriate Python type."""
    if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() in ("null", "~", ""):
        return None
    return value


# ---------------------------------------------------------------------------
# 2. Inline and block markdown converter (stdlib only)
# ---------------------------------------------------------------------------
#
# Architecture:
#   _inline(text)     — process inline markdown within a single line/span
#   _convert_body(text) — full block-level + inline conversion
#
# Block processing is line-based:
#   1. Protect fenced code blocks as opaque tokens.
#   2. Split remaining text into blank-line-separated segments.
#   3. Render each segment as the appropriate HTML element.
#   4. Restore tokens.


# Sentinel that cannot appear in normal markdown text.
_TOKEN_FMT = "\x00BLOCK_{index}\x00"
_TOKEN_RE = re.compile(r"\x00BLOCK_(\d+)\x00")


def _store_block(blocks: list[str], rendered: str) -> str:
    idx = len(blocks)
    blocks.append(rendered)
    return _TOKEN_FMT.format(index=idx)


def _inline(text: str) -> str:
    """
    Process inline markdown within a span of text.
    Does NOT escape arbitrary HTML — preserves tokens untouched.
    Order matters: bold before italic, code before bold/italic.
    """
    # Inline code  `code`  — escape HTML inside, protect from further processing
    # We stash inline-code spans as mini-tokens first.
    code_tokens: list[str] = []
    code_token_fmt = "\x00CODE_{i}\x00"

    def stash_code(m: re.Match) -> str:
        i = len(code_tokens)
        code_tokens.append(f"<code>{html.escape(m.group(1))}</code>")
        return code_token_fmt.format(i=i)

    text = re.sub(r'`([^`]+)`', stash_code, text)

    # Images  ![alt](url)  — must come before links
    text = re.sub(
        r'!\[([^\]]*)\]\(([^)]+)\)',
        lambda m: (
            f'<img src="{html.escape(m.group(2), quote=True)}"'
            f' alt="{html.escape(m.group(1))}">'
        ),
        text,
    )

    # Links  [text](url)
    text = re.sub(
        r'\[([^\]]+)\]\(([^)]+)\)',
        lambda m: (
            f'<a href="{html.escape(m.group(2), quote=True)}">'
            f'{m.group(1)}</a>'
        ),
        text,
    )

    # Bold **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', lambda m: f"<strong>{m.group(1)}</strong>", text)
    text = re.sub(r'__(.+?)__',     lambda m: f"<strong>{m.group(1)}</strong>", text)

    # Italic *text* or _text_  (must come after bold)
    text = re.sub(r'\*([^*\n]+?)\*', lambda m: f"<em>{m.group(1)}</em>", text)
    text = re.sub(r'_([^_\n]+?)_',   lambda m: f"<em>{m.group(1)}</em>", text)

    # Restore inline-code tokens
    def restore_code(m: re.Match) -> str:
        return code_tokens[int(m.group(1))]

    text = re.sub(r'\x00CODE_(\d+)\x00', restore_code, text)

    return text


def _render_list_segment(lines: list[str], ordered: bool) -> str:
    tag = "ol" if ordered else "ul"
    item_re = re.compile(r'^[ \t]*(?:[-*+]|\d+\.)\s+(.*)')
    items: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            items.append(_inline(" ".join(buf)))
        buf.clear()

    for line in lines:
        m = item_re.match(line)
        if m:
            flush()
            buf.append(m.group(1))
        elif line.strip() and buf:
            buf.append(line.strip())

    flush()
    li_lines = "\n".join(f"  <li>{item}</li>" for item in items)
    return f"<{tag}>\n{li_lines}\n</{tag}>"


def _render_segment(seg: str, blocks: list[str]) -> str:
    """Render a single blank-line-separated segment to HTML."""
    seg = seg.strip()
    if not seg:
        return ""

    # Token passthrough — already rendered HTML
    if _TOKEN_RE.fullmatch(seg):
        return seg

    lines = seg.splitlines()
    first = lines[0]

    # ATX Heading  # … ######
    hm = re.match(r'^(#{1,6})\s+(.*)', first)
    if hm:
        level = len(hm.group(1))
        content = _inline(hm.group(2).rstrip("#").strip())
        return f"<h{level}>{content}</h{level}>"

    # Horizontal rule  (--- / *** / ___ alone on line)
    if len(lines) == 1 and re.match(r'^[ \t]*(-{3,}|\*{3,}|_{3,})[ \t]*$', first):
        return "<hr>"

    # Unordered list
    if re.match(r'^[ \t]*[-*+]\s', first):
        return _render_list_segment(lines, ordered=False)

    # Ordered list
    if re.match(r'^[ \t]*\d+\.\s', first):
        return _render_list_segment(lines, ordered=True)

    # Blockquote
    if first.startswith(">"):
        stripped = [re.sub(r'^>[ \t]?', '', l) for l in lines]
        inner = _inline(" ".join(stripped))
        return f"<blockquote><p>{inner}</p></blockquote>"

    # Default: paragraph
    # Join continuation lines with a space; honour explicit <br> (two spaces + newline)
    parts: list[str] = []
    for line in lines:
        if line.endswith("  "):
            parts.append(line.rstrip() + "<br>")
        else:
            parts.append(line)
    joined = " ".join(parts)
    return f"<p>{_inline(joined)}</p>"


def _convert_body(text: str) -> str:
    """
    Full markdown-to-HTML conversion of the article body (no frontmatter).
    The text may already contain HTML fragments produced by Liquid tag
    expansion; those are protected from further processing.
    """
    blocks: list[str] = []

    # --- Pass 1: protect fenced code blocks ---
    def protect_fenced(m: re.Match) -> str:
        lang = m.group(1).strip()
        code = m.group(2)
        lang_attr = f' class="language-{html.escape(lang)}"' if lang else ""
        rendered = f"<pre><code{lang_attr}>{html.escape(code)}</code></pre>"
        return "\n\n" + _store_block(blocks, rendered) + "\n\n"

    text = re.sub(
        r'```([^\n]*)\n(.*?)```',
        protect_fenced,
        text,
        flags=re.DOTALL,
    )

    # --- Pass 2: protect raw HTML blocks ---
    # An HTML block is any sequence of lines (possibly interleaved with
    # non-HTML content) that starts with a line beginning with "<" and
    # extends until the next blank line.  We capture whole paragraphs that
    # start with an HTML tag.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = re.split(r'\n{2,}', text)
    processed: list[str] = []
    for para in paragraphs:
        stripped = para.strip()
        if not stripped:
            continue
        first_line = stripped.splitlines()[0] if stripped else ""
        if _TOKEN_RE.fullmatch(stripped):
            # Already a token from Pass 1 — pass through without double-storing.
            processed.append(stripped)
        elif re.match(r'^<', first_line):
            # Raw HTML block — store as opaque token so inline processing
            # does not corrupt tag attributes or content.
            processed.append(_store_block(blocks, stripped))
        else:
            processed.append(stripped)

    # --- Pass 3: render segments ---
    out_parts: list[str] = []
    for para in processed:
        rendered = _render_segment(para, blocks)
        if rendered:
            out_parts.append(rendered)

    result = "\n\n".join(out_parts)

    # --- Pass 4: restore tokens ---
    def restore(m: re.Match) -> str:
        return blocks[int(m.group(1))]

    return _TOKEN_RE.sub(restore, result).strip()


# ---------------------------------------------------------------------------
# 3. Liquid tag → HTML pre-processor
# ---------------------------------------------------------------------------
#
# Liquid blocks are expanded BEFORE _convert_body() is called.  The inner
# content of block-level Liquid tags (card, details) is itself converted from
# markdown to HTML inline at expansion time, so that the final HTML block is
# self-contained and can be stored as an opaque token by the block protector.

def _replace_liquid_tags(text: str) -> str:
    """
    Replace Dev.to Liquid tags with HTML.  Called on the raw body BEFORE the
    markdown converter runs.  Inner markdown content is pre-rendered.
    """
    # {% card %}...{% endcard %}
    text = re.sub(
        r'\{%\s*card\s*%\}(.*?)\{%\s*endcard\s*%\}',
        _liquid_card,
        text,
        flags=re.DOTALL,
    )

    # {% details Title text %}...{% enddetails %}
    text = re.sub(
        r'\{%\s*details\s+(.*?)\s*%\}(.*?)\{%\s*enddetails\s*%\}',
        _liquid_details,
        text,
        flags=re.DOTALL,
    )

    # {% cta https://url %}Link text{% endcta %}
    text = re.sub(
        r'\{%\s*cta\s+(https?://\S+)\s*%\}(.*?)\{%\s*endcta\s*%\}',
        _liquid_cta,
        text,
        flags=re.DOTALL,
    )

    # {% embed https://url %}
    text = re.sub(
        r'\{%\s*embed\s+(https?://\S+?)\s*%\}',
        _liquid_embed,
        text,
    )

    return text


def _liquid_card(m: re.Match) -> str:
    inner_md = m.group(1).strip()
    inner_html = _convert_body(inner_md)
    return f'\n\n<div class="liquid-card">\n{inner_html}\n</div>\n\n'


def _liquid_details(m: re.Match) -> str:
    title = html.escape(m.group(1).strip())
    inner_md = m.group(2).strip()
    inner_html = _convert_body(inner_md)
    return (
        f'\n\n<details>\n<summary>{title}</summary>\n'
        f'{inner_html}\n'
        f'</details>\n\n'
    )


def _liquid_cta(m: re.Match) -> str:
    url = html.escape(m.group(1).strip(), quote=True)
    label = m.group(2).strip() or m.group(1).strip()
    return (
        f'\n\n<a class="liquid-cta" href="{url}">'
        f'{html.escape(label)}'
        f'</a>\n\n'
    )


def _liquid_embed(m: re.Match) -> str:
    url = m.group(1).strip()
    escaped_url = html.escape(url, quote=True)
    host_m = re.match(r'https?://([^/]+)', url)
    label = html.escape(host_m.group(1) if host_m else url)
    return (
        f'\n\n<div class="liquid-embed">'
        f'<a href="{escaped_url}" target="_blank" rel="noopener noreferrer">'
        f'{label}</a>'
        f'</div>\n\n'
    )


# ---------------------------------------------------------------------------
# 4. Public API
# ---------------------------------------------------------------------------

def render(markdown_text: str) -> tuple[dict, str]:
    """
    Convert a Dev.to article (with optional YAML frontmatter and Liquid tags)
    to HTML.

    Parameters
    ----------
    markdown_text:
        Raw article text as read from a ``.md`` file.

    Returns
    -------
    (frontmatter_dict, html_body)

    frontmatter_dict keys:
        title, description, tags, series, cover_image, published
        Any key absent from the frontmatter is set to ``None``.

    html_body:
        The article body as an HTML string.  No ``<html>`` or ``<body>``
        wrapper.  Liquid tags are converted to styled HTML elements.
    """
    frontmatter, body = _parse_frontmatter(markdown_text)
    body = _replace_liquid_tags(body)
    html_body = _convert_body(body)
    return frontmatter, html_body


# ---------------------------------------------------------------------------
# 5. Quick self-test (python3 renderer.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _SAMPLE = """\
---
title: "Getting Started with Python"
description: A quick tour of Python basics.
tags: [python, tutorial, beginner]
series: null
cover_image: https://example.com/cover.png
published: false
---

## Introduction

Welcome to this article about **Python**.  It is *great*.

Here is some `inline code` and a [link](https://python.org).

{% card %}
This is a **highlighted** callout box.
{% endcard %}

### Code example

```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```

{% details Click to expand %}
Hidden content goes here.
{% enddetails %}

{% cta https://example.com %}Read the docs{% endcta %}

{% embed https://github.com/python/cpython %}

- First item
- Second item
- Third item

1. Step one
2. Step two

> This is a blockquote.

---

![A logo](https://example.com/logo.png)
"""

    fm, body_html = render(_SAMPLE)
    print("=== FRONTMATTER ===")
    for k, v in fm.items():
        print(f"  {k}: {v!r}")
    print("\n=== HTML BODY ===")
    print(body_html)
