#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../laptop"
python -m machine_vision_client.main

