#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

docker compose --project-directory "$PROJECT_DIR" down
printf '服务已停止并移除。数据卷和安装目录仍然保留。\n'
printf '如需彻底删除数据，请先备份，再手动执行：\n'
printf '  cd %q && docker compose down --volumes\n' "$PROJECT_DIR"
