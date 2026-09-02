#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -n "$(git -C "$PROJECT_DIR" status --porcelain)" ]]; then
  printf '更新失败：项目中存在未提交修改，请先处理。\n' >&2
  exit 1
fi

printf '正在更新 NodeSeek Bot……\n'
git -C "$PROJECT_DIR" pull --ff-only
docker compose --project-directory "$PROJECT_DIR" up -d --build
docker compose --project-directory "$PROJECT_DIR" ps
printf '更新完成。\n'
