#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/setup-local-venv.sh TARGET_DIR [--venv NAME]

Create or update a Python virtual environment inside TARGET_DIR and install
this codex-workscribe checkout into it in editable mode.

Examples:
  scripts/setup-local-venv.sh ~/Source/hypknowledge
  scripts/setup-local-venv.sh ~/Source/hypknowledge --venv .workscribe-venv
EOF
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

target_dir=$1
shift
venv_name=.venv

while [[ $# -gt 0 ]]; do
  case "$1" in
    --venv)
      if [[ $# -lt 2 ]]; then
        echo "error: --venv requires a name" >&2
        exit 2
      fi
      venv_name=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd "$script_dir/.." && pwd -P)
target_path=$(cd "$target_dir" && pwd -P)
venv_path="$target_path/$venv_name"

if [[ ! -f "$repo_root/pyproject.toml" ]]; then
  echo "error: could not find pyproject.toml at $repo_root" >&2
  exit 1
fi

python_bin=${PYTHON:-python3}

if [[ ! -x "$venv_path/bin/python" ]]; then
  "$python_bin" -m venv "$venv_path"
fi

"$venv_path/bin/python" -m pip install --upgrade pip
"$venv_path/bin/python" -m pip install -e "$repo_root"

cat <<EOF
Workscribe is installed in:
  $venv_path

Launch the explorer with:
  $venv_path/bin/workscribe explore --path "$target_path"

Or activate the environment first:
  source "$venv_path/bin/activate"
  workscribe explore --path "$target_path"
EOF
