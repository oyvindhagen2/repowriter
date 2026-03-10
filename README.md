# writer

Turn any git repository into a published blog series — automatically.

`writer` reads your commit history, designs a multi-part narrative, generates polished articles using Claude, creates AI cover images, and publishes everything to Dev.to. One tool, zero boilerplate.

```
python3 generate_blog.py --repo /path/to/your/project --plan
python3 generate_blog.py --repo /path/to/your/project --generate all
python3 cover_generator.py --dir posts/my-project
python3 devto_publisher.py --push-all posts/my-project
```

---

## What it does

1. **Plans your series** — analyzes your git log and designs a chapter structure that reads like a developer travelogue, not a changelog
2. **Writes the articles** — generates 2000–2500 word chapters using Claude, with proper code snippets, callouts, and narrative arc
3. **Makes cover images** — generates unique 1000×420 cover art per article via [Pollinations.ai](https://pollinations.ai) (free, no key needed), uploads to a public CDN
4. **Publishes everywhere** — pushes to Dev.to with frontmatter, series linking, and state tracking so reruns are idempotent

---

## Install

```bash
git clone https://github.com/oyvindhagen2/writer
cd writer
pip install anthropic
```

Copy `.env.example` to `.env` and add your keys.

---

## Setup

```bash
cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY and DEVTO_API_KEY
```

Get your keys:
- **Anthropic**: [console.anthropic.com](https://console.anthropic.com)
- **Dev.to**: Settings → Account → DEV Community API Keys

---

## Usage

### 1. Plan your series

Point it at any git repository:

```bash
python3 generate_blog.py --repo /path/to/your/project --plan
```

This reads your commit history and writes a `series_plan.json` to the repo's `posts/<project>/` folder. Edit it freely before generating.

Add context about yourself to improve the narrative:

```bash
python3 generate_blog.py --repo /path/to/your/project --plan \
  --author-context "solo dev, 10 years in fintech, first big open-source project"
```

### 2. Check status

```bash
python3 generate_blog.py --repo /path/to/your/project --status
```

### 3. Generate articles

```bash
python3 generate_blog.py --repo /path/to/your/project --generate next   # one at a time
python3 generate_blog.py --repo /path/to/your/project --generate all    # whole series
python3 generate_blog.py --repo /path/to/your/project --generate 3      # specific chapter
```

#### Audience modes

```bash
python3 generate_blog.py --repo ... --generate all --audience public      # default: Dev.to style
python3 generate_blog.py --repo ... --generate all --audience internal    # team retrospective
python3 generate_blog.py --repo ... --generate all --audience executive   # non-technical summary
```

### 4. Generate cover images

```bash
python3 cover_generator.py --dir posts/my-project           # all articles
python3 cover_generator.py --file posts/my-project/article-01-*.md  # one article
python3 cover_generator.py --dir posts/my-project --dry-run # preview prompts
```

Cover images are saved locally to `posts/<project>/covers/` and uploaded to [catbox.moe](https://catbox.moe) (free, permanent hosting). The `cover_image` frontmatter field is updated automatically.

Override the generated prompt per-article by adding `image_prompt` to your frontmatter:

```yaml
---
title: My article
image_prompt: glowing neural network dissolving into raindrops, dark cinematic
---
```

### 5. Publish to Dev.to

```bash
python3 devto_publisher.py --push-all posts/my-project         # push all as drafts
python3 devto_publisher.py --push-all posts/my-project --live  # publish immediately
python3 devto_publisher.py --pull-all posts/my-project         # sync back from Dev.to
```

State is tracked in `posts/<project>/devto_state.json` — reruns only update what changed.

---

## Article frontmatter

Articles use standard Dev.to frontmatter:

```yaml
---
title: The thing I built and why it nearly broke me
published: false
description: One sentence that makes someone click.
tags: python, webdev, opensource
series: Building My Thing
cover_image: https://...
image_prompt: optional custom image generation prompt
---
```

---

## File layout

```
posts/
  my-project/
    series_plan.json        ← edit this to shape your narrative
    article-01-*.md
    article-02-*.md
    ...
    covers/
      article-01.png
      article-02.png
      ...
    devto_state.json        ← auto-managed, tracks Dev.to article IDs
```

---

## Cover image engines

| Engine | Cost | Quality | Notes |
|--------|------|---------|-------|
| `pollinations` | Free | Good | Default. Flux model via pollinations.ai |
| `imagen4` | Paid | Excellent | Google Imagen 4 — requires billing |
| `gemini` | Paid | Good | gemini-2.5-flash-image |
| `auto` | Free → Paid | Best available | Tries Imagen 4, falls back to Pollinations |

```bash
python3 cover_generator.py --dir posts/my-project --engine pollinations
python3 cover_generator.py --dir posts/my-project --engine imagen4
```

---

## Requirements

- Python 3.10+
- `pip install anthropic`
- Git (for commit history analysis)
- A Dev.to account (free)

No other dependencies. The cover generator and publisher use only the standard library.

---

## Tips

- **Edit `series_plan.json`** before generating — the plan is the most important input. Add context, adjust chapter angles, rename titles.
- **Generate one at a time** with `--generate next` and read each article before continuing. It's easier to course-correct early.
- **Use `--dry-run`** on the cover generator to preview what prompts will be sent before burning API quota.
- **The state file is your friend** — `devto_state.json` means you can run `--push-all` repeatedly without creating duplicates.

---

## License

MIT
