@echo off
setlocal enabledelayedexpansion

REM Folder session custom
set SESSION_DIR=C:\Users\SwiftX-Gieh\afitech_api

REM Minta input username
set /p USERNAME=Masukkan username Instagram untuk login: 

REM Pastikan folder session ada
if not exist "%SESSION_DIR%" (
    mkdir "%SESSION_DIR%"
)

REM Jalankan Instaloader login dengan sessionfile custom
echo Menjalankan instaloader login untuk user %USERNAME% ...
instaloader --login %USERNAME% --sessionfile "%SESSION_DIR%\session-%USERNAME%"

REM Jika login berhasil, lanjut git
if errorlevel 1 (
    echo Terjadi kesalahan saat login dengan instaloader.
    pause
    exit /b 1
)

REM Masuk ke folder repo git (asumsi di session_dir juga)
cd /d "%SESSION_DIR%"

REM Pull remote terlebih dahulu
echo Melakukan git pull untuk update terbaru...
git pull origin main

REM Jika pull gagal, coba merge otomatis atau beri pesan
if errorlevel 1 (
    echo Gagal git pull, coba gabungkan manual dulu.
    pause
    exit /b 1
)

REM Add semua perubahan
git add .

REM Commit perubahan dengan pesan otomatis
for /f "tokens=*" %%a in ('powershell -Command "Get-Date -Format \"yyyy-MM-dd HH:mm:ss\" "') do set DATETIME=%%a
git commit -m "Update session file dan perubahan lain %DATETIME%"

REM Push ke remote
git push origin main

REM Cek status push
if errorlevel 1 (
    echo Gagal push ke remote repository. Coba pull dan push manual.
    pause
    exit /b 1
)

echo Selesai! Session disimpan di "%SESSION_DIR%\session-%USERNAME%"
pause
