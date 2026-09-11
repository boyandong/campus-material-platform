param([switch]$NoInstall)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvRoot = Join-Path $projectRoot '.venv'
$pythonExe = Join-Path $venvRoot 'Scripts\python.exe'
$pythonwExe = Join-Path $venvRoot 'Scripts\pythonw.exe'

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    Write-Host '首次运行：正在创建本地 Python 环境...'
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 -m venv $venvRoot
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        python -m venv $venvRoot
    } else {
        throw '未找到 Python 3。请先从 python.org 安装 Python 3.11 或更高版本。'
    }
}

$env:PYTHONUTF8 = '1'
$requirementsFile = Join-Path $projectRoot 'requirements.txt'
$dependencyMarker = Join-Path $venvRoot 'requirements.sha256'
$requirementsHash = (Get-FileHash -LiteralPath $requirementsFile -Algorithm SHA256).Hash
$installedHash = if (Test-Path -LiteralPath $dependencyMarker) { (Get-Content -LiteralPath $dependencyMarker -Raw).Trim() } else { '' }
if (-not $NoInstall -and $installedHash -ne $requirementsHash) {
    & $pythonExe -m pip install --disable-pip-version-check --timeout 300 -r (Join-Path $projectRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，未启动工作台；请检查网络后重试。' }
    # Generated dependency-state marker, not a secret/configuration file.
    Set-Content -LiteralPath $dependencyMarker -Value $requirementsHash -Encoding ASCII
}

$env:PYTHONPATH = $projectRoot
Set-Location -LiteralPath $projectRoot
Write-Host '正在打开本地桌面工作台...'
Start-Process -FilePath $pythonwExe -ArgumentList '-m', 'workbench.desktop' -WorkingDirectory $projectRoot
