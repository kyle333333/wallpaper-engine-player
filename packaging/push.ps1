# ============================================================
#  把仓库推到 GitHub
#  由根目录的 推送到GitHub.bat 调用
# ============================================================
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$REPO = 'wallpaper-engine-player'      # 想换仓库名就改这一行
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host ''
if (-not (Test-Path (Join-Path $root '.git'))) {
    Write-Host '  ✗ 这里还不是 git 仓库。' -ForegroundColor Red
    Read-Host '按回车退出'
    exit 1
}

# ---------------------------------------------------------- 1) 身份
Write-Host '【1/3】提交身份' -ForegroundColor Cyan
$defaultUser = 'kyle333333'
Write-Host "  你的 GitHub 用户名（直接回车用 $defaultUser）："
$user = (Read-Host '  用户名').Trim()
if (-not $user) { $user = $defaultUser }
$email = "$user@users.noreply.github.com"

git config user.name $user
git config user.email $email
git commit --amend --reset-author --no-edit 2>$null | Out-Null
Write-Host "  提交作者：$user <$email>"

# ---------------------------------------------------------- 2) 远端
Write-Host ''
Write-Host '【2/3】远端地址' -ForegroundColor Cyan
$url = "https://github.com/$user/$REPO.git"
$hasOrigin = (git remote) -contains 'origin'
if ($hasOrigin) { git remote set-url origin $url } else { git remote add origin $url }
git branch -M main
Write-Host "  $url"

Write-Host ''
Write-Host '  如果这个仓库还不存在，先去建一个**空**仓库' -ForegroundColor Yellow
Write-Host '  （不要勾 Add README / .gitignore / license，否则首推会冲突）：'
Write-Host "  https://github.com/new?name=$REPO" -ForegroundColor Yellow
Write-Host ''
Write-Host '  仓库已存在的话直接回车。' -ForegroundColor Yellow
Write-Host ''
Read-Host '  按回车开始推送（会弹 GitHub 登录窗口）'

# ---------------------------------------------------------- 3) 推送
Write-Host ''
Write-Host '【3/3】推送' -ForegroundColor Cyan
Write-Host '  如果弹出 GitHub 窗口：点 "Sign in with GitHub" → 浏览器里授权即可。'
Write-Host ''
# 用系统默认凭据管理器（Git Credential Manager），走浏览器 OAuth，不依赖任何 token
git -c credential.helper=manager push -u origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '  推送失败。常见原因：' -ForegroundColor Red
    Write-Host '    1) 仓库还没在 GitHub 上创建（或名字拼错）'
    Write-Host '    2) 浏览器里的登录没完成、或账号没有该仓库权限'
    Write-Host '    3) 网络问题（可先跑 git ls-remote 试试）'
    Write-Host '    4) 仓库里已经有 README 等文件 → 用 git pull --rebase origin main 再推'
    Write-Host '    5) 若它在命令行里让你输"密码"：GitHub 早已不接受账号密码，'
    Write-Host '       要去 Settings → Developer settings → Personal access tokens'
    Write-Host '       建一个带 repo 权限的 token，粘贴在密码处。'
    Read-Host '  按回车退出'
    exit 1
}

Write-Host ''
Write-Host '  完成 🎉' -ForegroundColor Green
Write-Host "  仓库地址：https://github.com/$user/$REPO"
Write-Host ''
Read-Host '按回车退出'
