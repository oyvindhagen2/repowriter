#!/usr/bin/env python3
"""
Blog generator: reads git history → generates Medium-ready narrative articles.

Uses the "Marco Polo dispatches" format — a developer journey told as a travelogue.
Each article is a chapter; chapters are based on ideas, milestones, and pivots —
not individual commits.

Usage:
  python3 generate_blog.py --repo /path/to/repo --plan
  python3 generate_blog.py --repo /path/to/repo --status
  python3 generate_blog.py --repo /path/to/repo --generate 1
  python3 generate_blog.py --repo /path/to/repo --generate next
  python3 generate_blog.py --repo /path/to/repo --generate all
  python3 generate_blog.py --repo /path/to/repo --generate 3 --internal
  python3 generate_blog.py --repo /path/to/repo --generate 3 --audience executive

Flags:
  --repo           Path to any git repository (default: current dir)
  --plan           Analyze git history and design the chapter plan
  --replan         Overwrite an existing plan
  --generate N     Generate article N (or 'next' or 'all')
  --audience       Audience mode: public (default), internal, executive
  --internal       Alias for --audience internal (backwards compatibility)
  --status         Show plan + which articles are drafted
  --output DIR     Output directory (default: ./posts)
  --project-name   Override project name derived from repo folder name
  --author-context Brief description: who you are / what you're building (used in prompts)

Requirements:
  pip install anthropic python-dotenv
  ANTHROPIC_API_KEY must be set in environment or .env file in the repo root
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ── dependency bootstrap ──────────────────────────────────────────────────────

def _ensure_deps():
    try:
        import anthropic  # noqa: F401
    except ImportError:
        print("Error: anthropic package not found.\n"
              "Install it: pip install anthropic\n"
              "Or activate your project venv first.", file=sys.stderr)
        sys.exit(1)

_ensure_deps()

import anthropic  # noqa: E402

MODEL = "claude-sonnet-4-6"
MAX_DIFF_CHARS = 6000   # per commit in article generation
MAX_PLAN_STAT_LINES = 20  # file lines shown per commit in plan prompt


def _clean_tag(t: str) -> str:
    """Normalise a tag to Dev.to rules: lowercase alphanumeric only."""
    return re.sub(r"[^a-z0-9]", "", t.lower().strip())


# ── .env loader (optional) ────────────────────────────────────────────────────

def _load_env(repo: str):
    """Load .env — checks writer dir, then repo root, then home dir."""
    candidates = [
        Path(__file__).parent / ".env",  # writer/.env (preferred)
        Path(repo) / ".env",             # repo root
        Path.home() / ".env",            # fallback
    ]
    for env_file in candidates:
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k not in os.environ:
                        os.environ[k] = v


# ── git helpers ───────────────────────────────────────────────────────────────

def _git(repo: str, *args, check=True) -> str:
    r = subprocess.run(
        ["git", "-C", repo] + list(args),
        capture_output=True, text=True, check=check
    )
    return r.stdout.strip()


def get_commits(repo: str) -> list[dict]:
    """Return all commits in chronological order with metadata."""
    raw = _git(repo, "log", "--format=%H|||%s|||%ad|||%an", "--date=short")
    commits = []
    for line in raw.splitlines():
        parts = line.split("|||")
        if len(parts) >= 4:
            commits.append({
                "hash": parts[0].strip(),
                "subject": parts[1].strip(),
                "date": parts[2].strip(),
                "author": parts[3].strip(),
            })
    return list(reversed(commits))  # oldest first


def get_diff_samples(repo: str, commits: list[dict], max_chars_per_commit: int = 1500) -> dict[str, str]:
    """Sample actual code diffs for each commit (for planning context)."""
    samples: dict[str, str] = {}
    for c in commits:
        try:
            diff = _git(
                repo, "show", "--no-color", "--format=",
                "--", "*.py", "*.ts", "*.tsx", "*.js", "*.go", "*.rs", "*.sql",
                c["hash"]
            )
            if diff:
                if len(diff) > max_chars_per_commit:
                    diff = diff[:max_chars_per_commit] + f"\n... [truncated — {len(diff)} chars total]"
                samples[c["hash"]] = diff
        except subprocess.CalledProcessError:
            pass
    return samples


def get_history_for_planning(repo: str, commits: list[dict], diff_samples: Optional[dict[str, str]] = None) -> str:
    """Return compact git history with file stats and optional diff samples — used for the plan prompt."""
    # git log --stat gives interleaved commit headers + file stats
    raw = _git(
        repo, "log", "--stat",
        "--format=COMMIT|%H|%s|%ad",
        "--date=short", "--reverse"
    )
    # Truncate individual file blocks to MAX_PLAN_STAT_LINES lines each
    out_lines: list[str] = []
    block: list[str] = []
    current_hash: Optional[str] = None

    def flush(b: list[str], commit_hash: Optional[str]):
        if not b:
            return
        stat_lines = [l for l in b if "|" in l or "changed" in l]
        truncated = stat_lines[:MAX_PLAN_STAT_LINES]
        if len(stat_lines) > MAX_PLAN_STAT_LINES:
            truncated.append(f"  ... and {len(stat_lines) - MAX_PLAN_STAT_LINES} more files")
        out_lines.extend(truncated)
        # Append diff sample if available
        if diff_samples and commit_hash and commit_hash in diff_samples:
            out_lines.append("Diff sample:")
            out_lines.append(diff_samples[commit_hash])
            out_lines.append("")

    for line in raw.splitlines():
        if line.startswith("COMMIT|"):
            flush(block, current_hash)
            block = []
            out_lines.append(line)
            # Extract hash from COMMIT|<hash>|<subject>|<date>
            parts = line.split("|", 3)
            current_hash = parts[1] if len(parts) > 1 else None
        else:
            block.append(line)
    flush(block, current_hash)

    return "\n".join(out_lines)


def get_readme(repo: str) -> str:
    """Return README content (first 3000 chars) if it exists."""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = Path(repo) / name
        if p.exists():
            return p.read_text()[:3000]
    return ""


def get_commit_detail(repo: str, commit_hash: str) -> dict:
    """Get body, stat, and code diff for a single commit."""
    body = _git(repo, "show", "-s", "--format=%b", commit_hash).strip()
    stat = _git(repo, "show", "--stat", "--format=", commit_hash)
    try:
        diff = _git(
            repo, "show", "--no-color", "--format=",
            "--", "*.py", "*.ts", "*.tsx", "*.js", "*.jsx",
            "*.go", "*.rs", "*.sql", "*.yaml", "*.yml", "*.toml",
            commit_hash
        )
        if len(diff) > MAX_DIFF_CHARS:
            diff = diff[:MAX_DIFF_CHARS] + f"\n... [truncated — {len(diff)} chars total]"
    except subprocess.CalledProcessError:
        diff = ""
    return {"body": body, "stat": stat, "diff": diff}


# ── Claude calls ──────────────────────────────────────────────────────────────

def plan_series(
    repo: str,
    commits: list[dict],
    project_name: str,
    author_context: str,
) -> dict:
    """Ask Claude to design the chapter structure for the whole series."""
    client = anthropic.Anthropic()

    diff_samples = get_diff_samples(repo, commits)
    history = get_history_for_planning(repo, commits, diff_samples=diff_samples)
    readme = get_readme(repo)
    readme_section = f"\nProject README (first 3000 chars):\n{readme}\n" if readme else ""

    prompt = f"""You are a narrative architect designing a blog series for Medium.com.

Project: {project_name}
Author: {author_context}
{readme_section}
Below is the full git history (chronological) with file-change statistics and code diff samples.

{history}

---

Your task: design a compelling series of developer-journey articles — "Marco Polo dispatches from the code frontier."

Rules:
- Group the journey into chapters based on *ideas, milestones, pivots, discoveries* — not individual commits.
- One commit can span multiple chapters; multiple commits can form one chapter.
- 5–8 chapters total. First chapter: origin story (the why, the spark, the vision).
- Every chapter must have a narrative tension: a problem, decision, or discovery that matters.
- Chapters should cover the arc: initial vision → architecture choices → first working version → key pivots or hard problems → system growth → current state / what's next.
- Titles: compelling, specific, sentence case, 6–12 words. Think like a reader who doesn't know the project.

Return valid JSON only — no other text, no code fences:
{{
  "series_title": "compelling title for the whole series (6–10 words, sentence case)",
  "series_tagline": "one sentence that makes a reader click",
  "series_description": "2–3 sentences describing the journey arc",
  "medium_tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "chapters": [
    {{
      "id": 1,
      "title": "chapter title",
      "subtitle": "one line expanding the title",
      "theme": "2–3 sentences: what this chapter is really about",
      "narrative_angle": "the hook, tension, or insight that makes this chapter interesting to a stranger",
      "commits": ["full_commit_hash_1", "full_commit_hash_2"],
      "medium_tags": ["tag1", "tag2", "tag3"],
      "opening_hook_idea": "one sentence: the incident/question/claim to open with",
      "word_count_target": 1500
    }}
  ]
}}"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.content[0].text.strip()
    # Strip code fences if Claude wrapped anyway
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()
    return json.loads(text)


def generate_article(
    repo: str,
    chapter: dict,
    all_commits: list[dict],
    series_plan: dict,
    audience: str = "public",
    prev_chapter: Optional[dict] = None,
    next_chapter: Optional[dict] = None,
) -> str:
    """Generate a full Medium-ready article for one chapter."""
    client = anthropic.Anthropic()

    # Gather commit data for this chapter
    chapter_hashes = set(chapter.get("commits", []))
    relevant = [c for c in all_commits if c["hash"] in chapter_hashes]

    commit_blocks: list[str] = []
    for c in relevant:
        detail = get_commit_detail(repo, c["hash"])
        block = f"[Commit: {c['subject']} — {c['date']}]\n"
        block += f"Files changed:\n{detail['stat']}\n"
        if detail["body"]:
            block += f"Commit notes: {detail['body'][:400]}\n"
        if detail["diff"]:
            block += f"Code changes:\n```\n{detail['diff']}\n```\n"
        commit_blocks.append(block)

    commit_context = "\n---\n".join(commit_blocks) if commit_blocks else \
        "(No commits tagged — infer narrative from chapter plan)"

    # Sensitivity and style rules per audience
    if audience == "internal":
        sensitivity = (
            "AUDIENCE: Internal — include all technical details, architecture decisions, "
            "tool names, implementation specifics. Only exclude: credentials, passwords, "
            "API tokens, personally identifiable information."
        )
        writing_guidelines = """WRITING GUIDELINES:

Voice: Marco Polo travelogue — you are filing dispatches from the frontier of building something real.
First person. Present-tense narrative feel even when describing past events.
The reader travels *with* you — they feel the decisions, the wrong turns, the breakthroughs.

Structure (follow in order):
1. **Opening hook** (100–150 words): drop straight into an incident, a decision under pressure,
   or a counterintuitive claim. Zero preamble. No "In this article..."
2. **## Where we are** — brief context: the journey so far, what led to this chapter
3. **## The problem** — what challenge/decision/idea drives this chapter. Make the stakes clear.
4. **## Into the unknown** — what you explored, what you tried, what failed or surprised you
5. **## What worked** — the solution, the breakthrough, the pattern that clicked
6. **## What this changed** — implications, lessons, what you'd do differently
7. **Signpost** (50–100 words): forward hook. End with a genuine reader question (drives comments).

Formatting rules:
- ## headers for the 5 main sections (sentence case). DO NOT use # H1 — title is in frontmatter.
- Use {% card %}...{% endcard %} to call out 1–2 key insight sentences (replaces bold-only emphasis)
- Use {% details summary %}...{% enddetails %} for code snippets that illustrate a wrong turn or dead end — keeps narrative flow clean
- Always specify language on code fences (```python, ```bash, etc.) for syntax highlighting
- **Bold** 1–2 additional insight sentences beyond the card
- Short paragraphs (2–3 sentences max) for mobile readability
- Target: 2,000–2,500 words (8–10 minute read) — longer content performs better on Dev.to"""

    elif audience == "executive":
        sensitivity = (
            "AUDIENCE: Executive / non-technical — plain English throughout.\n"
            "Rules:\n"
            "- NO code blocks whatsoever.\n"
            "- NO framework names, library names, or technical jargon.\n"
            "- DO NOT reveal competitive architectural secrets or internal proprietary details.\n"
            "- DO NOT include credentials, authentication flows, or internal API specifics.\n"
            "- Frame everything as: what was built, why it matters, what changed for the business or team.\n"
            "- Think: a LinkedIn article a non-developer CTO would read and share.\n"
            "- Emphasise business value, decision-making under uncertainty, and human lessons."
        )
        writing_guidelines = """WRITING GUIDELINES:

Voice: Marco Polo travelogue — you are filing dispatches from the frontier of building something real.
First person. Present-tense narrative feel even when describing past events.
The reader travels *with* you — they feel the decisions, the wrong turns, the breakthroughs.
Write as if explaining to a smart, busy executive who cares about outcomes, not implementations.

Structure (follow in order):
1. **Opening hook** (80–120 words): drop straight into a business decision, a moment of uncertainty,
   or a counterintuitive insight. Zero preamble. No "In this article..."
2. **## Where we are** — brief context: the journey so far, what led to this chapter
3. **## The challenge** — what problem or opportunity drove this chapter. Make the stakes clear in business terms.
4. **## What we tried** — what was explored, what failed or surprised, without technical specifics
5. **## What worked** — the breakthrough, in plain language. What changed and why it matters.
6. **## What this means** — implications, lessons, what you'd do differently
7. **Signpost** (40–70 words): forward hook. End with a genuine reader question (drives comments).

Formatting rules:
- ## headers for the 5 main sections (sentence case). DO NOT use # H1.
- **Bold** 2–3 key insight sentences
- NO code blocks
- Short paragraphs (2–3 sentences max) for mobile readability
- Target: 500–700 words (2–3 minute read)"""

    else:  # public
        sensitivity = (
            "AUDIENCE: Public (Medium.com) — follow these rules strictly:\n"
            "- Do NOT reveal core architectural patterns that are competitive advantages.\n"
            "- Do NOT name internal proprietary systems, internal tooling, or client/employer names "
            "unless they are publicly known.\n"
            "- Do NOT include authentication flows, credentials, or internal API details.\n"
            "- DO include: open-source tools and libraries by name, general technical approaches, "
            "failures and lessons, code snippets that illustrate problems without revealing the "
            "full proprietary solution, the human story of decisions and trade-offs.\n"
            "- When you'd normally name a competitive architectural secret, abstract it to the "
            "principle it represents (e.g. instead of revealing the specific data model, describe "
            "the problem it solves and why conventional approaches fell short)."
        )
        writing_guidelines = """WRITING GUIDELINES:

Voice: Marco Polo travelogue — you are filing dispatches from the frontier of building something real.
First person. Present-tense narrative feel even when describing past events.
The reader travels *with* you — they feel the decisions, the wrong turns, the breakthroughs.

Structure (follow in order):
1. **Opening hook** (100–150 words): drop straight into an incident, a decision under pressure,
   or a counterintuitive claim. Zero preamble. No "In this article..."
2. **## Where we are** — brief context: the journey so far, what led to this chapter
3. **## The problem** — what challenge/decision/idea drives this chapter. Make the stakes clear.
4. **## Into the unknown** — what you explored, what you tried, what failed or surprised you
5. **## What worked** — the solution, the breakthrough, the pattern that clicked
6. **## What this changed** — implications, lessons, what you'd do differently
7. **Signpost** (50–100 words): forward hook. End with a genuine reader question (drives comments).

Formatting rules:
- ## headers for the 5 main sections (sentence case). DO NOT use # H1 — title is in frontmatter.
- Use {% card %}...{% endcard %} to call out 1–2 key insight sentences (the ones a reader should remember)
- Use {% details summary %}...{% enddetails %} for code that illustrates a wrong approach or dead end
- Always specify language on code fences (```python, ```bash, etc.) for syntax highlighting
- **Bold** 1–2 additional insight sentences beyond the card
- Short paragraphs (2–3 sentences max) for mobile readability
- Target: 2,000–2,500 words (8–10 minute read) — longer content performs better on Dev.to"""

    prev_note = f'Previous chapter: "{prev_chapter["title"]}"' if prev_chapter else "This is the opening chapter."
    next_note = f'Next chapter will be: "{next_chapter["title"]}"' if next_chapter else "This is the final chapter."
    total = len(series_plan["chapters"])

    prompt = f"""You are writing a dispatch for a developer journey blog series on Medium.com.

Series: "{series_plan['series_title']}"
Chapter {chapter['id']} of {total}: "{chapter['title']}"
Subtitle: {chapter['subtitle']}
Theme: {chapter['theme']}
Narrative angle: {chapter['narrative_angle']}
Opening hook idea: {chapter['opening_hook_idea']}
{prev_note}
{next_note}

{sensitivity}

Git data for this chapter:
{commit_context}

---

{writing_guidelines}

Output the complete article. Start with the title, then the body. No meta-commentary.

Format:
# {chapter['title']}
*{chapter['subtitle']}*

[article body]

---
*Part {chapter['id']} of {total} in the series "{series_plan['series_title']}"*
**Tags:** {', '.join(chapter.get('medium_tags', series_plan.get('medium_tags', []))[:5])}
"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.content[0].text.strip()

    # ── Post-process ──────────────────────────────────────────────────────────
    # Strip leading H1 (Dev.to renders title from frontmatter)
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        if lines and not lines[0].strip():
            lines = lines[1:]
        text = "\n".join(lines)

    # Strip **Tags:** footer line (tags go in frontmatter)
    text = re.sub(r"\n\*\*Tags:\*\*.*$", "", text, flags=re.MULTILINE).rstrip()

    # Build clean tags (Dev.to: alphanumeric only, max 4)
    raw_tags = chapter.get("medium_tags", series_plan.get("medium_tags", []))
    clean_tags = [_clean_tag(t) for t in raw_tags if t.strip()][:4]

    # Build frontmatter
    subtitle = chapter.get("subtitle", "")
    description = f"{subtitle} Part {chapter['id']} of {total}.".strip()
    series_title = series_plan.get("series_title", "")
    frontmatter = (
        f"---\n"
        f"title: {chapter['title']}\n"
        f"published: false\n"
        f"description: {description}\n"
        f"tags: {', '.join(clean_tags)}\n"
        f"series: {series_title}\n"
        f"---\n"
    )

    return frontmatter + text + "\n"


# ── state helpers ─────────────────────────────────────────────────────────────

def slugify(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:55]


def article_path(output_dir: Path, chapter: dict, audience: str) -> Path:
    slug = slugify(chapter["title"])
    if audience == "internal":
        suffix = "-internal"
    elif audience == "executive":
        suffix = "-executive"
    else:
        suffix = ""
    return output_dir / f"article-{chapter['id']:02d}-{slug}{suffix}.md"


def load_plan(output_dir: Path) -> Optional[dict]:
    p = output_dir / "series_plan.json"
    return json.loads(p.read_text()) if p.exists() else None


def save_plan(output_dir: Path, plan: dict):
    output_dir.mkdir(parents=True, exist_ok=True)
    p = output_dir / "series_plan.json"
    p.write_text(json.dumps(plan, indent=2))
    print(f"Plan saved → {p}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate Medium-ready blog articles from git history"
    )
    parser.add_argument("--repo", default=".", help="Path to git repository")
    parser.add_argument("--plan", action="store_true", help="Analyze repo and create chapter plan")
    parser.add_argument("--replan", action="store_true", help="Re-analyze and overwrite existing plan")
    parser.add_argument("--generate", metavar="N|next|all",
                        help="Generate article(s): chapter number, 'next', or 'all'")
    parser.add_argument("--audience", choices=["public", "internal", "executive"],
                        default="public",
                        help="Audience mode: public (default), internal, executive")
    parser.add_argument("--internal", action="store_true",
                        help="Alias for --audience internal (backwards compatibility)")
    parser.add_argument("--status", action="store_true",
                        help="Show series plan and article generation status")
    parser.add_argument("--output", default="./posts", help="Output directory (default: ./posts)")
    parser.add_argument("--project-name", help="Project name (default: repo folder name)")
    parser.add_argument(
        "--author-context", default="",
        help='Brief description of who you are / what you\'re building. '
             'Example: "A developer at a Nordic securities firm building AI-powered research tools"'
    )
    parser.add_argument(
        "--publish", choices=["devto", "medium"],
        help="Publish generated article(s) to a platform (devto, medium). Creates a draft by default."
    )
    parser.add_argument(
        "--live", action="store_true",
        help="When used with --publish, publish immediately (public) instead of saving as draft"
    )
    parser.add_argument(
        "--unlisted", action="store_true",
        help="When used with --publish medium, publish as unlisted instead of draft"
    )
    args = parser.parse_args()

    # --internal is a backwards-compatible alias for --audience internal
    audience = args.audience
    if args.internal:
        audience = "internal"

    repo = str(Path(args.repo).resolve())
    output_dir = Path(args.output)

    # Load .env
    _load_env(repo)

    # Validate repo
    try:
        _git(repo, "rev-parse", "--git-dir")
    except subprocess.CalledProcessError:
        print(f"Error: {repo} is not a git repository", file=sys.stderr)
        sys.exit(1)

    project_name = args.project_name or Path(repo).name
    author_context = args.author_context or f"A developer building {project_name}"

    # ── PLAN ──
    if args.plan or args.replan:
        existing = load_plan(output_dir)
        if existing and not args.replan:
            print(f"Plan already exists ({len(existing['chapters'])} chapters). "
                  f"Use --replan to overwrite.\n")
            _print_plan(existing, output_dir)
            sys.exit(0)

        commits = get_commits(repo)
        if not commits:
            print("No commits found.", file=sys.stderr)
            sys.exit(1)

        print(f"Analyzing {len(commits)} commits in '{project_name}'...")
        plan = plan_series(repo, commits, project_name, author_context)
        save_plan(output_dir, plan)
        print()
        _print_plan(plan, output_dir)
        return

    # ── STATUS ──
    if args.status:
        plan = _require_plan(output_dir)
        _print_plan(plan, output_dir)
        return

    # ── GENERATE ──
    if args.generate:
        plan = _require_plan(output_dir)
        commits = get_commits(repo)
        chapters = plan["chapters"]
        chapters_by_id = {ch["id"]: ch for ch in chapters}

        if args.generate == "all":
            to_generate = chapters
        elif args.generate == "next":
            to_generate = []
            for ch in chapters:
                if not article_path(output_dir, ch, audience).exists():
                    to_generate = [ch]
                    break
            if not to_generate:
                print("All articles already generated.")
                return
        else:
            try:
                n = int(args.generate)
                to_generate = [ch for ch in chapters if ch["id"] == n]
                if not to_generate:
                    print(f"Chapter {n} not found in plan.")
                    sys.exit(1)
            except ValueError:
                print(f"Invalid --generate value: '{args.generate}'")
                sys.exit(1)

        for ch in to_generate:
            out_file = article_path(output_dir, ch, audience)
            print(f"Generating [{audience}] chapter {ch['id']}: {ch['title']} ...")

            article = generate_article(
                repo=repo,
                chapter=ch,
                all_commits=commits,
                series_plan=plan,
                audience=audience,
                prev_chapter=chapters_by_id.get(ch["id"] - 1),
                next_chapter=chapters_by_id.get(ch["id"] + 1),
            )

            output_dir.mkdir(parents=True, exist_ok=True)
            out_file.write_text(article, encoding="utf-8")
            print(f"  Saved → {out_file}")

            if args.publish == "devto":
                from devto_publisher import publish_article as devto_publish, _parse_markdown_file
                title, body, tags = _parse_markdown_file(out_file)
                series_name = plan.get("series_title", "")
                devto_publish(
                    title=title,
                    body_markdown=body,
                    tags=tags[:4],
                    published=args.live,
                    series=series_name or None,
                )
            elif args.publish == "medium":
                from medium_publisher import publish_article as medium_publish, _parse_markdown_file as _parse_md
                title, body, tags = _parse_md(out_file)
                if args.live:
                    status = "public"
                elif args.unlisted:
                    status = "unlisted"
                else:
                    status = "draft"
                medium_publish(
                    title=title,
                    body_markdown=body,
                    tags=tags[:5],
                    publish_status=status,
                )
            print()
        return

    parser.print_help()


def _print_plan(plan: dict, output_dir: Path):
    print(f"Series:  {plan['series_title']}")
    print(f"Tagline: {plan['series_tagline']}")
    print(f"Tags:    {', '.join(plan.get('medium_tags', []))}")
    print()
    for ch in plan["chapters"]:
        pub = article_path(output_dir, ch, "public")
        intl = article_path(output_dir, ch, "internal")
        exec_ = article_path(output_dir, ch, "executive")
        drafted = []
        if pub.exists():
            drafted.append("public")
        if intl.exists():
            drafted.append("internal")
        if exec_.exists():
            drafted.append("executive")
        status = f"[{', '.join(drafted)}]" if drafted else "[ pending ]"
        print(f"  {status}  {ch['id']:2d}. {ch['title']}")
        print(f"            {ch['narrative_angle']}")
    print()


def _require_plan(output_dir: Path) -> dict:
    plan = load_plan(output_dir)
    if not plan:
        print("No plan found. Run with --plan first.", file=sys.stderr)
        sys.exit(1)
    return plan


if __name__ == "__main__":
    main()
