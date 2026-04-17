# 启用仓库自带的 Git hooks（仅需在本克隆执行一次）
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
git config core.hooksPath .githooks
Write-Host "已设置 core.hooksPath=.githooks ，提交后会自动 git push fork main ，并在改动 docs 静态页时同步子仓库。"
