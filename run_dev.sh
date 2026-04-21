#!/usr/bin/env bash
set -euo pipefail

poetry run python src/run_service.py 2>&1 | tee /tmp/opey.log
