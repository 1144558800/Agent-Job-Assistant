@echo off
chcp 65001 >nul
echo 正在关闭 Agent 求职助手服务...

:: 通过端口关闭进程（8001=后端, 3001=前端）
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001 " ^| findstr "LISTENING"') do (
    echo 关闭后端进程 PID: %%a
    taskkill /f /pid %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3001 " ^| findstr "LISTENING"') do (
    echo 关闭前端进程 PID: %%a
    taskkill /f /pid %%a >nul 2>&1
)

echo 服务已关闭。
pause
