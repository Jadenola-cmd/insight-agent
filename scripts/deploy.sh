#!/usr/bin/env bash
# 部署脚本：本地 git push 到服务器裸仓库，post-receive hook 自动 checkout 到工作区，
# 再 SSH 安装依赖、构建前端、重启 PM2。
#
# 背景（2026-06-19 改造）：此前用 `git archive | ssh ... tar -x` 整包传输，服务器端
# 没有 git 历史，不便回滚/diff；服务器从 GitHub 拉取 HTTPS 又经常超时（GFW间歇性
# 干扰），所以改为「本地 push 到服务器裸仓库」：服务器侧 `/www/insight-agent.git`
# 是裸仓库，`post-receive` hook 收到 `deploy` 分支推送后执行
# `git checkout -f deploy` 到 `/www/insight-agent` 工作区，既不需要服务器访问
# GitHub，又保留了完整 git 历史，可在服务器上直接 `git log`/`git diff` 排查。
#
# 用法：在本地仓库根目录执行 `bash scripts/deploy.sh`
#   - 部署前请先 commit（脚本 push 的是 HEAD，即已提交的内容，未 commit 的改动不会被部署）
#   - 默认部署 HEAD；如需部署其他 ref，传第一个参数，如 `bash scripts/deploy.sh origin/master`

set -euo pipefail

REMOTE="empirical"
REMOTE_DIR="/www/insight-agent"
REMOTE_BARE_REPO="/www/insight-agent.git"
REF="${1:-HEAD}"
SSH_CONFIG="${HOME}/.ssh/config"

cd "$(git rev-parse --show-toplevel)"

echo "==> push ${REF} 到 ${REMOTE}:${REMOTE_BARE_REPO}（deploy 分支，触发 post-receive 自动 checkout）"
GIT_SSH_COMMAND="ssh -F $SSH_CONFIG" git push "${REMOTE}:${REMOTE_BARE_REPO}" "${REF}:refs/heads/deploy" --force

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
