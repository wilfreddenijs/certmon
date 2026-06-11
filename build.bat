@echo off
echo Installing dependencies...
pip install flask cryptography openpyxl pystray pillow pyinstaller

echo.
echo Building CertMon.exe...
pyinstaller certmon.spec --clean --noconfirm

echo.
if exist dist\CertMon.exe (
    echo Build successful! EXE is at: dist\CertMon.exe
    echo.
    echo You can move CertMon.exe anywhere — it is fully standalone.
    echo certmon_data.json will be created next to the .exe on first run.
) else (
    echo Build failed. Check the output above for errors.
)
pause
