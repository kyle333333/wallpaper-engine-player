# ============================================================
#  WE 壁纸播放器 — 打包脚本（免安装绿色版）
#  由 打包.bat 调用；也可直接右键「使用 PowerShell 运行」
#  产出：dist\WE壁纸播放器\  和  dist\WE壁纸播放器.zip
# ============================================================
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root  = Split-Path -Parent $PSScriptRoot                 # 工程根目录
$dist  = Join-Path $root 'dist\WE壁纸播放器'
$tools = Join-Path $root 'dist\_tools'
$zip   = Join-Path $root 'dist\WE壁纸播放器.zip'
$exeName = '启动播放器.exe'
$pyZip = 'python-3.13.1-embed-amd64.zip'
$pyUrl = "https://www.python.org/ftp/python/3.13.1/$pyZip"

function Info($msg) { Write-Host $msg }

Info ''
Info '[1/6] 清理旧产物 ...'
Remove-Item $dist -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $zip -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path (Join-Path $dist 'runtime') -Force | Out-Null
New-Item -ItemType Directory -Path $tools -Force | Out-Null

Info '[2/6] 准备 Python 嵌入式运行时 ...'
$cache = Join-Path $tools $pyZip
if (-not (Test-Path $cache)) {
    Info '      首次需要联网下载约 10 MB，请稍候 ...'
    try {
        Invoke-WebRequest -Uri $pyUrl -OutFile $cache -UseBasicParsing
    } catch {
        Info ''
        Info '  ✗ 下载运行时失败。请手动下载下面这个文件：'
        Info "      $pyUrl"
        Info "    放到 $tools 之后重新运行本脚本。"
        exit 1
    }
}
Expand-Archive -Path $cache -DestinationPath (Join-Path $dist 'runtime') -Force
# ._pth 存在时脚本所在目录默认不在 sys.path 里，补上应用根目录
Add-Content -Path (Join-Path $dist 'runtime\python313._pth') -Value '..' -Encoding Ascii
Info "      运行时就绪：$((Get-ChildItem (Join-Path $dist 'runtime') -File).Count) 个文件"

Info '[3/6] 拷贝程序文件 ...'
Copy-Item (Join-Path $root 'we_player.py') $dist -Force
Copy-Item (Join-Path $root 'web') $dist -Recurse -Force
Copy-Item (Join-Path $root 'docs') $dist -Recurse -Force
Copy-Item (Join-Path $root 'README.md') $dist -Force
foreach ($f in @('使用说明.txt', '备用启动.vbs', '调试启动.bat')) {
    Copy-Item (Join-Path $PSScriptRoot $f) $dist -Force
}

Info '[4/6] 编译启动器 exe ...'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
if (Test-Path $csc) {
    # 先编译成 ASCII 名，再用 PowerShell 改名 —— 避免中文路径经过原生进程命令行被转码弄坏
    $tmpExe = Join-Path $dist '_launcher.exe'
    & $csc /nologo /target:winexe /optimize+ /r:System.Windows.Forms.dll `
        "/win32icon:$(Join-Path $PSScriptRoot 'app.ico')" `
        "/out:$tmpExe" (Join-Path $PSScriptRoot 'launcher.cs') | Out-Null
    if (Test-Path $tmpExe) {
        Move-Item $tmpExe (Join-Path $dist $exeName) -Force
        Info "      已生成 $exeName"
    } else {
        Info '      ✗ 编译失败，包内改用「备用启动.vbs」双击启动'
    }
} else {
    Info '      没找到 csc.exe（.NET Framework 编译器），包内改用「备用启动.vbs」双击启动'
}

Info '[5/6] 打包成 zip ...'
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $dist, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $true)

Info '[6/6] 完成。'
$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Info ''
Info "  产物：$zip"
Info "  体积：$size MB"
Info ''
Info '  把这个 zip 发给对方；对方解压后双击「启动播放器.exe」即可。'
Info ''
