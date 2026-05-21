"""End-to-end pipeline entrypoint.

Stages: ingestion -> storage -> transformation -> quality -> metric -> signal.
Called by `make run` and by `.github/workflows/refresh.yml`.
"""

from __future__ import annotations

import logging
import sys


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger = logging.getLogger(__name__)
    logger.info("Pipeline entrypoint — implementation pending")
    return 0


if __name__ == "__main__":
    sys.exit(main())
