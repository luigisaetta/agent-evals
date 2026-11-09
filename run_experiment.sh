#!/usr/bin/env bash
# Author: L. Saetta
# Date last modified: 2026-11-09
# License: MIT
# Description: Forward legacy root-level commands to the Demo01 launcher.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$script_dir/demo01/run_experiment.sh" "$@"
