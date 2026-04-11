#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/wsmxd/feishubot.git"
TARGET_DIR="feishubot"
RUN_MODE="chat"

usage() {
  cat <<'USAGE'
FeishuBot bootstrap script

Usage:
  bash scripts/bootstrap.sh [--repo-url <url>] [--target-dir <dir>] [--run <chat|gateway|none>]

Examples:
  # Download project then start terminal chat
  bash scripts/bootstrap.sh

  # Download to custom directory and do not start app
  bash scripts/bootstrap.sh --target-dir my-bot --run none

  # Run inside an existing repository checkout
  bash scripts/bootstrap.sh --run gateway
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url)
      REPO_URL="$2"
      shift 2
      ;;
    --target-dir)
      TARGET_DIR="$2"
      shift 2
      ;;
    --run)
      RUN_MODE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ "$RUN_MODE" != "chat" && "$RUN_MODE" != "gateway" && "$RUN_MODE" != "none" ]]; then
  echo "Invalid --run value: $RUN_MODE (allowed: chat, gateway, none)" >&2
  exit 1
fi

PROJECT_DIR="$PWD"
if [[ ! -f "$PROJECT_DIR/pyproject.toml" || ! -d "$PROJECT_DIR/src/feishubot" ]]; then
  PROJECT_DIR="$PWD/$TARGET_DIR"
  if [[ -d "$PROJECT_DIR/.git" ]]; then
    echo "Using existing repository: $PROJECT_DIR"
  else
    if [[ -e "$PROJECT_DIR" ]]; then
      echo "Target path already exists and is not a git checkout: $PROJECT_DIR" >&2
      exit 1
    fi
    echo "Cloning $REPO_URL -> $PROJECT_DIR"
    git clone "$REPO_URL" "$PROJECT_DIR"
  fi
fi

cd "$PROJECT_DIR"

echo "Project directory: $PROJECT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found, installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv installation failed or uv is not on PATH." >&2
  echo "Please add ~/.local/bin to PATH and retry." >&2
  exit 1
fi

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Syncing dependencies with uv..."
uv sync

case "$RUN_MODE" in
  chat)
    echo "Starting terminal chat (type /exit to quit)..."
    uv run feishubot chat
    ;;
  gateway)
    echo "Starting gateway on http://127.0.0.1:8000 ..."
    uv run feishubot gateway --host 127.0.0.1 --port 8000
    ;;
  none)
    echo "Bootstrap completed. Run manually with:"
    echo "  uv run feishubot chat"
    echo "  uv run feishubot gateway --host 127.0.0.1 --port 8000"
    ;;
esac
