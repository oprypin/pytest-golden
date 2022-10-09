#!/bin/sh
set -e

cd "$(dirname "$0")/.."

PYTHONPATH=$(pwd)/example pytest -q example
