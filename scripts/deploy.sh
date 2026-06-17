#!/usr/bin/env bash
# 部署脚本：将本地 git HEAD 打包通过 SSH 传到腾讯云服务器解压，安装依赖、构建前端、重启 PM2。
#
# 背景：服务器从 GitHub 拉取 HTTPS 经常超时（GFW间歇性干扰），所以不走 git pull，
# 而是把本地已提交的代码直接 tar 流传过去，服务器侧无需访问 GitHub。
#
# 用法：在本地仓库根目录执行 `bash scripts/deploy.sh`
#   - 部署前请先 commit（脚本只打包 HEAD，即已提交的内容，未 commit 的改动不会被部署）
#   - 默认部署 HEAD；如需部署其他 ref，传第一个参数，如 `bash scripts/deploy.sh origin/master`

set -euo pipefail

REMOTE="empirical"
REMOTE_DIR="/www/insight-agent"
REF="${1:-HEAD}"
SSH_CONFIG="${HOME}/.ssh/config"

cd "$(git rev-parse --show-toplevel)"

echo "==> 打包 ${REF} 并传输到 ${REMOTE}:${REMOTE_DIR}"
git archive "$REF" | ssh -F "$SSH_CONFIG" "$REMOTE" "mkdir -p '$REMOTE_DIR' && tar -x -C '$REMOTE_DIR'"

echo "==> 远程安装依赖 + 构建 + 重启"
ssh -F "$SSH_CONFIG" "$REMOTE" bash -s -- "$REMOTE_DIR" <<'REMOTE_SCRIPT'
set -euo pipefail
REMOTE_DIR="$1"
cd "$REMOTE_DIR"

echo "-- 安装后端依赖 --"
source api/venv/bin/activate
pip install -q -r api/requirements.txt
deactivate

echo "-- 安装前端依赖 + 构建 --"
pnpm install --frozen-lockfile
pnpm build

echo "-- 重启 PM2 进程 --"
pm2 restart insight-api insight-web

echo "-- 健康检查 --"
sleep 5
if curl -sf http://127.0.0.1:8001/health > /dev/null; then
  echo "API health OK"
else
  echo "API health 检查失败，请查看 pm2 logs insight-api"
fi
if curl -sf -o /dev/null http://127.0.0.1:3002; then
  echo "Web OK"
else
  echo "Web 检查失败，请查看 pm2 logs insight-web"
fi
REMOTE_SCRIPT

echo "==> 部署完成"
