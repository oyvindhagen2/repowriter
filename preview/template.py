def render_page(frontmatter: dict, body_html: str, article_path: str = "") -> str:
    """Returns a complete HTML page string."""

    title = frontmatter.get("title", "Untitled")
    cover_image = frontmatter.get("cover_image", "")
    series = frontmatter.get("series", "")
    tags = frontmatter.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    # Cover image block
    if cover_image:
        cover_block = f'<img class="cover-image" src="{cover_image}" alt="Cover image">'
    else:
        cover_block = ""

    # Series label
    if series:
        series_block = f'<div class="series-label">Part of the series: <span>{series}</span></div>'
    else:
        series_block = ""

    # Tags
    if tags:
        tag_pills = "".join(f'<span class="tag">#{tag}</span>' for tag in tags)
        tags_block = f'<div class="tags">{tag_pills}</div>'
    else:
        tags_block = ""

    # Nav: article filename
    article_filename = article_path.split("/")[-1] if article_path else ""
    nav_filename = f'<span class="nav-filename">{article_filename}</span>' if article_filename else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
  <style>
    *, *::before, *::after {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      background: #ffffff;
      color: #0d1117;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 18px;
      line-height: 1.8;
    }}

    /* ── Navigation bar ── */
    .nav-bar {{
      background: #ffffff;
      border-bottom: 1px solid #e5e7eb;
      padding: 0.6rem 1.5rem;
      display: flex;
      align-items: center;
      gap: 1rem;
      position: sticky;
      top: 0;
      z-index: 100;
    }}

    .nav-bar a.back-link {{
      color: #3b49df;
      text-decoration: none;
      font-size: 0.9rem;
      font-weight: 500;
    }}

    .nav-bar a.back-link:hover {{
      text-decoration: underline;
    }}

    .nav-filename {{
      color: #6b7280;
      font-size: 0.8rem;
      font-family: ui-monospace, "SFMono-Regular", Menlo, monospace;
      margin-left: auto;
    }}

    /* ── Main content column ── */
    .content-wrapper {{
      max-width: 680px;
      margin: 2.5rem auto;
      padding: 0 1.25rem 4rem;
    }}

    /* ── Cover image ── */
    .cover-image {{
      display: block;
      width: 100%;
      max-height: 340px;
      object-fit: cover;
      border-radius: 8px;
      margin-bottom: 1.75rem;
    }}

    /* ── Series label ── */
    .series-label {{
      font-size: 0.8rem;
      color: #6b7280;
      margin-bottom: 0.4rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}

    .series-label span {{
      color: #3b49df;
      font-weight: 600;
    }}

    /* ── Article title ── */
    .article-title {{
      font-size: 2.2rem;
      font-weight: 800;
      line-height: 1.2;
      color: #0d1117;
      margin-bottom: 0.75rem;
    }}

    /* ── Tags ── */
    .tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
      margin-bottom: 2rem;
    }}

    .tag {{
      background: #f0f0f0;
      color: #374151;
      font-size: 0.78rem;
      font-weight: 500;
      padding: 0.2rem 0.65rem;
      border-radius: 9999px;
    }}

    /* ── Article body typography ── */
    .article-body h1 {{
      font-size: 1.75rem;
      font-weight: 700;
      margin: 2rem 0 0.75rem;
      line-height: 1.3;
      color: #0d1117;
    }}

    .article-body h2 {{
      font-size: 1.5rem;
      font-weight: 700;
      margin: 1.8rem 0 0.65rem;
      line-height: 1.3;
      color: #0d1117;
    }}

    .article-body h3 {{
      font-size: 1.25rem;
      font-weight: 700;
      margin: 1.5rem 0 0.5rem;
      line-height: 1.35;
      color: #0d1117;
    }}

    .article-body h4, .article-body h5, .article-body h6 {{
      font-size: 1rem;
      font-weight: 700;
      margin: 1.2rem 0 0.4rem;
      color: #0d1117;
    }}

    .article-body p {{
      margin-bottom: 1.2rem;
    }}

    .article-body a {{
      color: #3b49df;
      text-decoration: none;
    }}

    .article-body a:hover {{
      text-decoration: underline;
    }}

    .article-body ul, .article-body ol {{
      margin: 0.75rem 0 1.2rem 1.5rem;
    }}

    .article-body li {{
      margin-bottom: 0.35rem;
    }}

    .article-body hr {{
      border: none;
      border-top: 1px solid #e5e7eb;
      margin: 2rem 0;
    }}

    .article-body blockquote {{
      border-left: 4px solid #3b49df;
      background: #f5f7ff;
      padding: 0.9rem 1.1rem;
      margin: 1.5rem 0;
      border-radius: 0 4px 4px 0;
      font-style: italic;
      color: #374151;
    }}

    .article-body blockquote p:last-child {{
      margin-bottom: 0;
    }}

    /* ── Code ── */
    .article-body pre {{
      background: #1e1e2e;
      border-radius: 8px;
      padding: 1.1rem 1.25rem;
      overflow-x: auto;
      margin: 1.2rem 0 1.5rem;
      font-size: 0.88rem;
      line-height: 1.6;
    }}

    .article-body pre code {{
      background: none;
      padding: 0;
      border-radius: 0;
      font-size: inherit;
      color: inherit;
    }}

    .article-body code {{
      background: #f0f0f0;
      color: #0d1117;
      font-family: ui-monospace, "SFMono-Regular", Menlo, "Courier New", monospace;
      font-size: 0.85em;
      padding: 0.15em 0.35em;
      border-radius: 4px;
    }}

    /* ── Images ── */
    .article-body img {{
      max-width: 100%;
      border-radius: 6px;
      display: block;
      margin: 1rem auto;
    }}

    /* ── Tables ── */
    .article-body table {{
      width: 100%;
      border-collapse: collapse;
      margin: 1.25rem 0;
      font-size: 0.9rem;
    }}

    .article-body th, .article-body td {{
      border: 1px solid #e5e7eb;
      padding: 0.5rem 0.75rem;
      text-align: left;
    }}

    .article-body th {{
      background: #f9fafb;
      font-weight: 600;
    }}

    /* ── Liquid tag: callout card ── */
    .article-body .devto-card {{
      background: #f0f4ff;
      border-left: 4px solid #3b49df;
      border-radius: 0 6px 6px 0;
      padding: 1rem 1.25rem;
      margin: 1.25rem 0;
      color: #1e2a6e;
    }}

    .article-body .devto-card p:last-child {{
      margin-bottom: 0;
    }}

    /* ── Liquid tag: details/summary ── */
    .article-body details {{
      background: #f9fafb;
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      padding: 0.75rem 1rem;
      margin: 1.25rem 0;
    }}

    .article-body details summary {{
      cursor: pointer;
      font-weight: 600;
      list-style: none;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      user-select: none;
    }}

    .article-body details summary::before {{
      content: "▶";
      font-size: 0.65em;
      transition: transform 0.2s ease;
      display: inline-block;
    }}

    .article-body details[open] summary::before {{
      transform: rotate(90deg);
    }}

    .article-body details[open] summary {{
      margin-bottom: 0.75rem;
    }}

    /* ── Liquid tag: CTA button ── */
    .article-body .devto-cta {{
      display: block;
      width: fit-content;
      margin: 1.5rem auto;
      background: #3b49df;
      color: #ffffff;
      text-decoration: none;
      font-weight: 600;
      font-size: 1rem;
      padding: 0.7rem 1.75rem;
      border-radius: 8px;
      text-align: center;
      transition: background 0.15s ease;
    }}

    .article-body .devto-cta:hover {{
      background: #2f3bba;
      text-decoration: none;
    }}

    /* ── Liquid tag: embed / link card ── */
    .article-body .devto-embed {{
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 0.9rem 1.1rem;
      background: #f9fafb;
      margin: 1.25rem 0;
      font-size: 0.9rem;
    }}

    .article-body .devto-embed a {{
      color: #3b49df;
      font-weight: 500;
    }}
  </style>
</head>
<body>

  <nav class="nav-bar">
    <a class="back-link" href="/">← Back to index</a>
    {nav_filename}
  </nav>

  <main class="content-wrapper">
    {cover_block}
    {series_block}
    <h1 class="article-title">{title}</h1>
    {tags_block}
    <article class="article-body">
      {body_html}
    </article>
  </main>

  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <script>hljs.highlightAll();</script>
  <script>
    const es = new EventSource('/events');
    es.onmessage = () => location.reload();
  </script>

</body>
</html>"""
