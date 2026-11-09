#!/usr/bin/env bash
# Author: L. Saetta
# Date last modified: 2026-11-09
# License: MIT
# Description: Run a named Demo01 experiment using the agent-evals Conda environment.
set -euo pipefail

if [[ $# -eq 0 ]]; then
    echo 'Usage: ./demo01/run_experiment.sh EXPERIMENT_NAME [OPTIONS...]' >&2
    exit 2
fi
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    echo 'Usage: ./demo01/run_experiment.sh EXPERIMENT_NAME [OPTIONS...]'
    echo 'Example: ./demo01/run_experiment.sh "Express Order baseline" --split evaluation --sleep-seconds 5'
    exit 0
fi
experiment_name="$1"
shift
if [[ -z "${experiment_name//[[:space:]]/}" || "$experiment_name" == -* ]]; then
    echo 'Provide a non-blank experiment name before any options.' >&2
    exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/.." && pwd)"
cd "$repo_dir"
export PYTHONPATH="$repo_dir/src:$repo_dir${PYTHONPATH:+:$PYTHONPATH}"
exec conda run --no-capture-output -n agent-evals python -m demo01.evaluate \
    --experiment-name "$experiment_name" "$@"
