# writer

Every developer I know has a graveyard of half-built things they never wrote about.

Not because they weren't proud of them. Not because they didn't have anything to say. But because writing is a separate skill from building, it lives in a separate tool, and after the hard part is done the last thing you want to do is context-switch into a blank document and explain yourself.

`writer` is an attempt to close that gap. Point it at any git repository. It reads your commit history — the actual record of decisions made, directions changed, things that didn't work — and turns it into a multi-part narrative series. Then it generates cover images. Then it publishes everything to Dev.to, with state tracking so reruns don't create duplicates.

Your commits already tell a story. This just writes it down.

---

## The meta problem

This tool was built to document a different project. That project had hundreds of commits across six months — architecture decisions, wrong turns, things rebuilt twice. The kind of project that *deserves* a write-up but will never get one the normal way because normal writing is too slow and too separate from the work itself.

The insight was simple: git log is a structured record of everything you did and when you did it. The diff tells you what changed. The commit message tells you why. The sequence tells you the shape of the thinking. That's most of a blog post already. What's missing is the narrative voice, the context a reader needs, and the honest reflection on what worked.

Claude can provide those things. The git log can't be fabricated. The combination turns out to be surprisingly readable.

---

## What it actually does

```bash
python3 generate_blog.py --repo /path/to/your/project --plan
```

This reads your entire commit history, infers themes and turning points, and designs a chapter structure — not a commit-by-commit recap, but an actual narrative arc. The output is a `series_plan.json` you can edit before generating anything. The plan is the most important part. Shape it.

```bash
python3 generate_blog.py --repo /path/to/your/project --generate all
```

Each article comes out at roughly 2000–2500 words. It knows to use `{% card %}` for key insights, `{% details %}` for dead-end code that's instructive but not central, proper code fence languages, no H1 in the body because that comes from frontmatter. It produces Dev.to-ready markdown.

```bash
python3 cover_generator.py --dir posts/my-project
```

Generates a unique 1000×420 cover image per article via [Pollinations.ai](https://pollinations.ai) — free, no billing, no key. Uploads to a public CDN. Updates the `cover_image` frontmatter field automatically.

```bash
python3 devto_publisher.py --push-all posts/my-project
```

Pushes everything to Dev.to as drafts. A state file tracks article IDs so you can run this repeatedly without creating duplicates. Add `--live` to publish immediately.

---

## The pipeline, honestly

It doesn't always work perfectly the first time.

Pollinations rate-limits aggressively if you hit it too fast — there's a 30-second sleep between articles and a retry loop with backoff. The image generation is genuinely probabilistic; the same prompt returns different images on different days, and sometimes the model backend just fails. The retry logic is more patient than you'd want it to be.

The Dev.to API has a quirk where `published: false` in the body markdown overrides the `published: true` in the API payload — so the publisher rewrites the frontmatter file before pushing when you go live. The draft endpoint returns 404 on the public article route, so syncing drafts back requires hitting `/articles/me/unpublished`. These are the kinds of things you learn by running into them.

The state file pattern ended up being the most useful design decision. Every `article-*.md` file maps to a Dev.to article ID in `devto_state.json`. No more manually tracking which article is which. Reruns are idempotent. Edit locally, push again, it updates.

---

## Setup

```bash
git clone https://github.com/oyvindhagen2/repowriter
cd repowriter
pip install anthropic
cp .env.example .env
# Add ANTHROPIC_API_KEY and DEVTO_API_KEY
```

Get your keys:
- **Anthropic**: [console.anthropic.com](https://console.anthropic.com)
- **Dev.to**: Settings → Account → DEV Community API Keys

The cover generator and publisher have no dependencies beyond the standard library. Only `generate_blog.py` needs the `anthropic` package.

---

## Full usage

### Plan your series

```bash
python3 generate_blog.py --repo /path/to/your/project --plan
```

Add context about yourself — it improves the narrative voice significantly:

```bash
python3 generate_blog.py --repo /path/to/your/project --plan \
  --author-context "backend engineer, first time building in public, side project"
```

Edit `posts/<project>/series_plan.json` before generating. Change the chapter angles. Rename titles. Add things the git log doesn't know about.

### Generate

```bash
python3 generate_blog.py --repo ... --status                 # what's been written
python3 generate_blog.py --repo ... --generate next          # one chapter at a time
python3 generate_blog.py --repo ... --generate 3             # specific chapter
python3 generate_blog.py --repo ... --generate all           # everything
```

#### Audience modes

```bash
--audience public       # Dev.to style (default)
--audience internal     # team retrospective
--audience executive    # non-technical summary
```

### Covers

```bash
python3 cover_generator.py --dir posts/my-project --dry-run  # preview prompts first
python3 cover_generator.py --dir posts/my-project            # generate + upload
python3 cover_generator.py --dir posts/my-project --force    # regenerate existing
```

Override the generated prompt per-article via frontmatter:

```yaml
image_prompt: glowing neural network dissolving into raindrops, dark cinematic
```

### Publish

```bash
python3 devto_publisher.py --push-all posts/my-project         # drafts
python3 devto_publisher.py --push-all posts/my-project --live  # publish
python3 devto_publisher.py --pull-all posts/my-project         # sync from Dev.to
```

---

## File layout

```
posts/
  my-project/
    series_plan.json        ← edit this before generating
    article-01-*.md
    article-02-*.md
    ...
    covers/
      article-01.png
      article-02.png
    devto_state.json        ← auto-managed
```

---

## Cover image engines

| Engine | Cost | Notes |
|--------|------|-------|
| `pollinations` | Free | Flux model. Default. |
| `imagen4` | Paid | Google Imagen 4. Requires billing. |
| `gemini` | Paid | gemini-2.5-flash-image. |
| `auto` | Free → Paid | Tries Imagen 4, falls back to Pollinations. |

---

## Requirements

- Python 3.10+
- `pip install anthropic`
- Git

---

## The thing it can't do

It can't replace your judgment about whether something is worth writing about, or whether the angle the planner chose is actually the interesting one. Read the `series_plan.json` before generating. The plan is a hypothesis about what your project's story is. You know if it's right.

The articles it produces are good first drafts, not finished pieces. They'll be close, but they're not you. Edit them.

---

## License

MIT
