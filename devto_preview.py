#!/usr/bin/env python3
"""
Dev.to article previewer — renders articles locally with live reload.

Usage:
  python3 devto_preview.py --dir posts/arctic_digital
  python3 devto_preview.py --dir posts/arctic_digital --port 4242
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from preview.server import serve


def main():
    parser = argparse.ArgumentParser(description="Preview Dev.to articles locally")
    parser.add_argument("--dir", metavar="DIR", required=True, help="Directory containing article-*.md files")
    parser.add_argument("--port", type=int, default=4242, help="Port to serve on (default: 4242)")
    args = parser.parse_args()

    directory = Path(args.dir).resolve()
    if not directory.exists():
        print(f"Directory not found: {directory}", file=sys.stderr)
        sys.exit(1)

    serve(str(directory), port=args.port)


if __name__ == "__main__":
    main()
