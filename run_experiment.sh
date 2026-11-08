#!/usr/bin/env bash
# Author: L. Saetta
# Date last modified: 2026-11-08
# License: MIT
# Description: Run a named experiment using the agent-evals Conda environment.
set -euo pipefail

if [[ $# -eq 0 ]]; then
    echo 'Usage: ./run_experiment.sh EXPERIMENT_NAME [OPTIONS...]' >&2
    exit 2
fi
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    echo 'Usage: ./run_experiment.sh EXPERIMENT_NAME [OPTIONS...]'
    echo 'Example: ./run_experiment.sh "Express Order baseline" --split evaluation --sleep-seconds 5'
    exit 0
fi
experiment_name="$1"
shift
if [[ -z "${experiment_name//[[:space:]]/}" || "$experiment_name" == -* ]]; then
    echo 'Provide a non-blank experiment name before any options.' >&2
    exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"
export PYTHONPATH="$script_dir/src${PYTHONPATH:+:$PYTHONPATH}"
exec conda run --no-capture-output -n agent-evals python -m agent_evals.evaluate \
    --experiment-name "$experiment_name" "$@"
