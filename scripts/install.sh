#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY_URL="${NODESEEK_REPOSITORY_URL:-https://github.com/meloay/nodeseek-bot.git}"
INSTALL_DIR="${NODESEEK_INSTALL_DIR:-${HOME}/nodeseek-bot}"
BRANCH="${NODESEEK_BRANCH:-main}"

info() {
  printf '\033[1;34m[NodeSeek Bot]\033[0m %s\n' "$*"
}

fail() {
  printf '\033[1;31m[安装失败]\033[0m %s\n' "$*" >&2
  exit 1
}

need_command() {
  command -v "$1" >/dev/null 2>&1 || fail "缺少 $1，请先安装后重试。"
}

read_secret() {
  local prompt="$1"
  local value

  if [[ ! -r /dev/tty ]]; then
    fail "当前环境无法交互输入，请通过 TELEGRAM_BOT_TOKEN 环境变量提供 Token。"
  fi

  printf '%s' "$prompt" >/dev/tty
  IFS= read -r -s value </dev/tty
  printf '\n' >/dev/tty
  printf '%s' "$value"
}

need_command git
need_command docker
docker compose version >/dev/null 2>&1 || fail "需要 Docker Compose v2（docker compose）。"
docker info >/dev/null 2>&1 || fail "Docker 尚未启动，或当前用户无权访问 Docker。"

token="${TELEGRAM_BOT_TOKEN:-}"
if [[ -z "$token" ]]; then
  token="$(read_secret '请输入 BotFather 提供的 Telegram Bot Token：')"
fi
if [[ ! "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
  fail "Telegram Bot Token 格式不正确。"
fi

admin_id="${TELEGRAM_ADMIN_ID:-}"
if [[ -n "$admin_id" && ! "$admin_id" =~ ^-?[0-9]+$ ]]; then
  fail "TELEGRAM_ADMIN_ID 必须是整数。"
fi

if [[ "$INSTALL_DIR" == "/" ]]; then
  fail "安装目录不能是根目录。"
fi

if [[ -d "$INSTALL_DIR/.git" ]]; then
  info "发现已有安装，正在更新源码……"
  existing_origin="$(git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null || true)"
  normalized_origin="${existing_origin%/}"
  normalized_origin="${normalized_origin%.git}"
  normalized_repository="${REPOSITORY_URL%/}"
  normalized_repository="${normalized_repository%.git}"
  if [[ "$normalized_origin" != "$normalized_repository" ]]; then
    fail "$INSTALL_DIR 属于其他 Git 仓库，不会自动覆盖。"
  fi
  if [[ -n "$(git -C "$INSTALL_DIR" status --porcelain)" ]]; then
    fail "$INSTALL_DIR 存在未提交修改，请处理后再运行安装器。"
  fi
  git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH"
  git -C "$INSTALL_DIR" checkout "$BRANCH"
  git -C "$INSTALL_DIR" merge --ff-only FETCH_HEAD
elif [[ -e "$INSTALL_DIR" ]]; then
  fail "安装目录已存在且不是 Git 仓库：$INSTALL_DIR"
else
  info "正在下载源码到 ${INSTALL_DIR}……"
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --depth 1 --branch "$BRANCH" "$REPOSITORY_URL" "$INSTALL_DIR"
fi

umask 077
{
  printf 'TELEGRAM_BOT_TOKEN=%s\n' "$token"
  printf 'TELEGRAM_ADMIN_ID=%s\n' "$admin_id"
  printf 'LOG_LEVEL=%s\n' "${LOG_LEVEL:-INFO}"
} >"$INSTALL_DIR/.env"
chmod 600 "$INSTALL_DIR/.env"

info "正在构建并启动服务……"
docker compose --project-directory "$INSTALL_DIR" up -d --build

info "安装完成。"
printf '\n安装目录：%s\n' "$INSTALL_DIR"
printf '查看状态：cd %q && docker compose ps\n' "$INSTALL_DIR"
printf '查看日志：cd %q && docker compose logs -f --tail=100 bot\n' "$INSTALL_DIR"
printf '更新版本：%q\n' "$INSTALL_DIR/scripts/update.sh"
