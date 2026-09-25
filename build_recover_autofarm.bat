@echo off
chcp 65001 >nul
echo ================================
echo   打包死亡恢复+挂机
echo ================================
echo.

conda run -n TLBB pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo 正在安装 PyInstaller...
    conda run -n TLBB pip install pyinstaller
)

echo 开始打包...
conda run -n TLBB pyinstaller ^
  --onefile ^
  --windowed ^
  --icon=NONE ^
  --name "死亡恢复挂机" ^
  --add-data "templates;templates" ^
  --add-data "config;config" ^
  recover_autofarm_gui.py

echo.
echo ================================
echo   打包完成！
echo ================================
echo 可执行文件位置: dist\死亡恢复挂机.exe
echo.
pause
