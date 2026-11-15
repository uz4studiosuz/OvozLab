@echo off
rem OvozLab - asosiy muhitni o'rnatish/yangilash (setup.exe oxirida yashirin ishga tushadi).
rem Python o'rnatuvchining ichida keladi ({app}\python). Bu skript yengil paketlarni (~60 MB) yuklab,
rem {app}\runtime virtual muhitini yaratadi yoki yangilaydi.
rem Og'ir qism (PyTorch, modellar) ilovaning o'rnatish ustasida yuklanadi va YANGILASHDA SAQLANADI.
setlocal EnableDelayedExpansion
for %%I in ("%~dp0..") do set "APP=%%~fI"
set "UV_PROJECT_ENVIRONMENT=%APP%\runtime"
set "UV_PYTHON_DOWNLOADS=never"
rem Kesh qisqa yo'lda: ba'zi paketlar yig'ilganda Windows'ning 260 belgilik chegarasiga urilmaslik uchun.
set "UV_CACHE_DIR=%TEMP%\ovozlab-uv"
set "UV_LINK_MODE=copy"
set "UV_NO_PROGRESS=1"

echo [%date% %time%] OvozLab bootstrap: %APP% > "%APP%\install.log"

rem Muhit hali yo'q bo'lsagina ichki Python'ni ko'rsatamiz. Mavjud muhitga boshqa Python berilsa,
rem uv uni noldan qayta yaratadi va o'rnatilgan PyTorch (~4 GB) o'chib ketadi.
if not exist "%APP%\runtime\pyvenv.cfg" set "UV_PYTHON=%APP%\python\python.exe"

rem O'rnatilgan PyTorch qaysi qurilma uchun ekanini aniqlaymiz va uni sync ga qo'shamiz.
set "EXTRA="
for /d %%D in ("%APP%\runtime\Lib\site-packages\torch-*.dist-info") do (
  set "TD=%%~nxD"
  set "EXTRA=--extra cpu"
  echo !TD! | findstr /c:"+xpu" >nul && set "EXTRA=--extra xpu"
  echo !TD! | findstr /c:"+cu" >nul && set "EXTRA=--extra cuda"
)
echo PyTorch: !EXTRA! >> "%APP%\install.log"

rem --inexact: ro'yxatda bo'lmagan paketlar (masalan, foydalanuvchi qo'shgani) o'chirilmaydi.
"%APP%\bin\uv.exe" sync --frozen --no-dev --inexact --no-install-project !EXTRA! --directory "%APP%" >> "%APP%\install.log" 2>&1
set "ERR=!ERRORLEVEL!"
echo [%date% %time%] exit code !ERR! >> "%APP%\install.log"
rmdir /s /q "%TEMP%\ovozlab-uv" 2>nul
> "%APP%\bootstrap.exitcode" echo !ERR!
exit /b !ERR!
