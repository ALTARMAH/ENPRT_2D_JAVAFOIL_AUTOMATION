#!/usr/bin/env python3
"""
make_pdf.py - backwards-compatible alias for the documentation build.

Rebuilds the dark-themed docs/TECHNICAL_GUIDE.pdf (full technical report with
verbatim code) and docs/USER_MANUAL.pdf.

  python make_pdf.py            -> build both
  python make_pdf.py --only m   -> manual only
  python make_pdf.py --only r   -> report only
"""
import sys

import build_docs


def main():
    return build_docs.main()


if __name__ == "__main__":
    sys.exit(main())