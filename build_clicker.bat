@echo off
chcp 65001 >nul
echo ================================
echo   打包自动连点器
echo ================================
echo.

REM 检查是否安装了pyinstaller
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo 正在安装 PyInstaller...
    pip install pyinstaller
)

echo 开始打包...
pyinstaller --onefile --windowed --icon=NONE --name "自动连点器" auto_clicker.py

echo.
echo ================================
echo   打包完成！
echo ================================
echo 可执行文件位置: dist\自动连点器.exe
echo.
pause
