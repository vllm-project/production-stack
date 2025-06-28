#!/bin/bash

set -e

CHART_DIR="$1"
VALUES_DIR="$2"

if [[ -z "$CHART_DIR" || -z "$VALUES_DIR" ]]; then
  echo "Usage: $0 <helm_chart_dir> <values_dir>"
  exit 1
fi

if [[ ! -d "$CHART_DIR" || ! -d "$VALUES_DIR" ]]; then
  echo "Error: Both arguments must be directories."
  exit 1
fi

for values_file in "$VALUES_DIR"/values*.yaml; do
  if [[ -f "$values_file" ]]; then
    echo "🔍 Rendering with: $values_file"

    if ! helm template my-release "$CHART_DIR" -f "$values_file" > /dev/null; then
      echo "❌ Failed to render with $values_file" >&2
    else
      echo "✅ Success: $values_file"
    fi
  fi
done
