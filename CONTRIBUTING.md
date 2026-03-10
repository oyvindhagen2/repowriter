# Contributing to writer

Thanks for being here. This is a small tool built to solve a real problem — contributions that make it more useful are genuinely welcome.

## The best contributions

- **Bug reports with reproduction steps** — especially platform-specific issues (Hashnode, Medium, Substack, etc.)
- **New publisher integrations** — if you add support for a new platform, that's a pull request that will get merged
- **Better prompt engineering** — the article generation prompts in `generate_blog.py` have room to improve; if you find wording that produces consistently better output, share it
- **Real-world feedback** — opened an issue to say "I ran this on my project and here's what was weird" is genuinely useful

## How to contribute

1. Fork the repo
2. Create a branch (`git checkout -b my-thing`)
3. Make your change
4. Test it against a real repo — `python3 generate_blog.py --repo /some/project --plan` should still work
5. Open a pull request with a short description of what you changed and why

No CLA, no contributor agreement, no bureaucracy.

## Issues

Use issues for:
- Bug reports (include Python version, OS, the command you ran, and the error)
- Feature requests (describe the problem you're trying to solve, not just the solution)
- Questions (if the README didn't answer it, that's worth knowing about)

## What won't get merged

- Changes that add hard dependencies beyond `anthropic`
- Platform-specific code without a clear abstraction path
- Anything that breaks the `--dry-run` flag

## Code style

No formatter enforced. Match the style of the file you're editing. Keep functions small and obvious. Prefer stdlib over new dependencies.
