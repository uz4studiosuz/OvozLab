# OvozLab o'rnatuvchisini yig'ish: OvozLab-Setup-<versiya>.exe
#   powershell -ExecutionPolicy Bypass -File installer\build.ps1
# Talablar: Inno Setup 6 (winget install JRSoftware.InnoSetup), uv
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here

# 1) Versiya pyproject.toml dan
$version = (Select-String -Path "$root\pyproject.toml" -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "OvozLab $version"

# 2) uv.lock yangiligini tekshirish
Push-Location $root
uv lock --check
if ($LASTEXITCODE -ne 0) { throw "uv.lock eskirgan - 'uv lock' ni ishga tushiring" }
Pop-Location

# 3) uv.exe ni o'rnatuvchiga qo'shish (o'rnatilgan uv yoki rasmiy relizdan)
$bin = "$here\build\bin"
New-Item -ItemType Directory -Force $bin | Out-Null
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if ($uv) {
    Copy-Item $uv "$bin\uv.exe" -Force
} else {
    $zip = "$here\build\uv.zip"
    Invoke-WebRequest "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath "$here\build\uv" -Force
    Copy-Item "$here\build\uv\uv.exe" "$bin\uv.exe" -Force
}

# 4) Inno Setup kompilyatori
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 topilmadi. O'rnating: winget install JRSoftware.InnoSetup" }

# 5) Python keshlarini tozalash va yig'ish
Get-ChildItem $root\ovozlab, $root\omnivoice -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
& $iscc "/DAppVersion=$version" "$here\OvozLab.iss"
if ($LASTEXITCODE -ne 0) { throw "ISCC xatosi" }
Write-Host "`nTayyor: $here\Output\OvozLab-Setup-$version.exe"
