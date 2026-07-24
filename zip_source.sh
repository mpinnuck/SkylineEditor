#!/usr/bin/env bash
set -euo pipefail

# Creates a source zip from the repository while excluding requirements.md.
# Usage:
#   ./zip_source.sh

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_root"

output_zip="source.zip"
file_list="$(mktemp)"
trap 'rm -f "$file_list"' EXIT

find . -type f \
  ! -path './.git/*' \
  ! -path './.venv/*' \
  ! -path '*/__pycache__/*' \
  ! -path './.pytest_cache/*' \
  ! -name 'requirements.md' \
  ! -name '*.pyc' \
  ! -name '.DS_Store' \
  ! -name '*.zip' \
  -print | sed 's#^\./##' > "$file_list"

if [[ ! -s "$file_list" ]]; then
  echo "No files found to archive."
  exit 1
fi

rm -f "$output_zip"
zip -q -@ "$output_zip" < "$file_list"

echo "Created: $output_zip"
