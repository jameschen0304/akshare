#!/bin/sh
# 启用仓库自带的 Git hooks（仅需在本克隆执行一次）
cd "$(dirname "$0")/.." || exit 1
git config core.hooksPath .githooks
echo "已设置 core.hooksPath=.githooks"
