# OvozLab - bootstrap.cmd ni mustaqil jarayon sifatida ishga tushiradi va kutadi.
#
# Nega kerak: Inno Setup 6.5+ o'z jarayonlariga "RedirectionGuard" himoyasini yoqadi va u bola
# jarayonlarga meros bo'lib o'tadi. uv esa Python o'rnatayotganda junction (cpython-3.12 havolasi)
# yaratadi - himoya buni "untrusted mount point (os error 448)" deb bloklaydi.
# WMI orqali yaratilgan jarayon Setup'ning bolasi emas, shuning uchun cheklov unga o'tmaydi.
param([Parameter(Mandatory = $true)][string]$App)

$exitFile = Join-Path $App 'bootstrap.exitcode'
Remove-Item $exitFile -ErrorAction SilentlyContinue

$startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
$cmd = 'cmd.exe /c ""' + (Join-Path $App 'bin\bootstrap.cmd') + '""'
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $cmd; CurrentDirectory = $App; ProcessStartupInformation = $startup
}
if ($r.ReturnValue -ne 0) { exit 90 }

Wait-Process -Id $r.ProcessId -ErrorAction SilentlyContinue
if (Test-Path $exitFile) { exit [int]((Get-Content $exitFile -Raw).Trim()) }
exit 91
