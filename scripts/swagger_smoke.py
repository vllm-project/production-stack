#!/usr/bin/env python3
"""CLI Swagger smoke test script.

Uses the same tester logic as the e2e pytest but runnable standalone.
Exit code 0 = all pass; non-zero otherwise.
"""

# Copyright 2024-2025 The vLLM Production Stack Authors.
# Licensed under the Apache License, Version 2.0.

from __future__ import annotations

import os
import sys
from _swagger_smoke_core import run_smoke


def main():  # pragma: no cover
    base = sys.argv[1] if len(sys.argv) > 1 else os.getenv("SWAGGER_BASE_URL", "http://localhost:8080")
    ok = run_smoke(base)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":  # pragma: no cover
    main()
