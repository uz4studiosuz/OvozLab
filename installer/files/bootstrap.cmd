@echo off
rem OvozLab - asosiy muhitni o'rnatish (setup.exe oxirida yashirin ishga tushadi).
rem Python o'rnatuvchining ichida keladi ({app}\python). Bu skript faqat yengil paketlarni
rem (~60 MB) yuklab, {app}\runtime virtual muhitini yaratadi.
rem Og'ir qism (PyTorch, modellar) keyin ilovaning o'rnatish ustasida yuklanadi.
setlocal
for %%I in ("%~dp0..") do set "APP=%%~fI"
set "UV_PROJECT_ENVIRONMENT=%APP%\runtime"
set "UV_PYTHON=%APP%\python\python.exe"
set "UV_PYTHON_DOWNLOADS=never"
rem Kesh qisqa yo'lda: ba'zi paketlar yig'ilganda Windows'ning 260 belgilik chegarasiga urilmaslik uchun.
set "UV_CACHE_DIR=%TEMP%\ovozlab-uv"
set "UV_LINK_MODE=copy"
set "UV_NO_PROGRESS=1"

echo [%date% %time%] OvozLab bootstrap: %APP% > "%APP%\install.log"
"%APP%\bin\uv.exe" sync --frozen --no-dev --no-install-project --directory "%APP%" >> "%APP%\install.log" 2>&1
set "ERR=%ERRORLEVEL%"
echo [%date% %time%] exit code %ERR% >> "%APP%\install.log"
rmdir /s /q "%TEMP%\ovozlab-uv" 2>nul
> "%APP%\bootstrap.exitcode" echo %ERR%
exit /b %ERR%
