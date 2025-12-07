@echo off
REM Set encoding to UTF-8
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
REM Set environment variables to support UTF-8 output
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

REM ============================================================================
REM LLM-Filter-Probe - One-Click Startup Script
REM Supported: Windows System
REM Features: Auto-check dependencies, install dependencies, start backend and frontend
REM ============================================================================

title LLM-Filter-Probe - System Startup

echo.
echo ============================================================================
echo  LLM-Filter-Probe - 启动中
echo ============================================================================
echo.

REM ============================================================================
REM Create logs directory
REM ============================================================================

if not exist "logs" mkdir logs

REM ============================================================================
REM Step 1: Check Environment
REM ============================================================================

echo [1/5] 检查系统环境...
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到 Python
    echo   请从 https://www.python.org 下载并安装 Python 3.8+
    echo   安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo ✓ Python %PYTHON_VERSION%

REM Check Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到 Node.js
    echo   请从 https://nodejs.org 下载并安装 Node.js 14.0+
    echo   安装时请勾选 "Add to PATH"
    pause
    exit /b 1
)
for /f %%i in ('node --version') do set NODE_VERSION=%%i
echo ✓ Node.js %NODE_VERSION%

echo.

REM ============================================================================
REM Step 2: Check Project Structure
REM ============================================================================

echo [2/5] 检查项目文件...
echo.

if not exist "backend\app.py" (
    echo 错误: 后端文件未找到
    echo   请确保在项目根目录运行此脚本
    pause
    exit /b 1
)
echo ✓ 后端文件

if not exist "frontend\package.json" (
    echo 错误: 前端文件未找到
    echo   请确保在项目根目录运行此脚本
    pause
    exit /b 1
)
echo ✓ 前端文件

echo.

REM ============================================================================
REM Step 3: Create venv and Install Backend Dependencies
REM ============================================================================

echo [3/5] 检查并配置后端环境 (venv)...

REM Check for venv directory
if not exist "backend\venv" (
    echo   未找到虚拟环境，正在创建 venv...
    pushd backend
    python -m venv venv > ..\logs\venv_setup.log 2>&1
    if errorlevel 1 (
        echo 错误: 创建 Python 虚拟环境失败。
        echo   请检查 Python 是否已正确安装并添加到 PATH。
        echo   日志: logs\venv_setup.log
        pause
        exit /b 1
    )
    popd
    echo   ✓ 虚拟环境创建成功。
) else (
    echo   ✓ 虚拟环境已存在。
)

echo   正在激活虚拟环境并安装依赖...
pushd backend
call venv\Scripts\activate.bat
pip install -r ..\requirements.txt ^
    -i https://pypi.tuna.tsinghua.edu.cn/simple ^
    --trusted-host pypi.tuna.tsinghua.edu.cn
if errorlevel 1 (
    echo 错误: 后端依赖安装失败。
    echo   请尝试在 backend 目录手动运行: venv\Scripts\activate.bat 然后 pip install -r ../requirements.txt
    pause
    exit /b 1
)
popd
echo ✓ 后端依赖已就绪。


echo.

REM ============================================================================
REM Step 4: Install Frontend Dependencies
REM ============================================================================

echo [4/5] 检查前端依赖...
echo.

cd frontend
if not exist "node_modules" (
    echo   正在安装前端依赖，请稍候...
    call npm install --legacy-peer-deps --registry=https://registry.npmmirror.com
    if errorlevel 1 (
        echo 前端依赖安装失败
        echo   请尝试手动安装: npm install
        pause
        exit /b 1
    )
)
echo ✓ 前端依赖已就绪
cd ..

echo.

REM ============================================================================
REM Step 5: Start Services
REM ============================================================================

echo [5/5] 启动服务...
echo.

echo 正在启动后端服务 (使用 venv)...
pushd backend
start "" /b venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 19002 --reload --log-level warning
popd

REM Wait for backend initialization
timeout /t 5 /nobreak >nul

echo 正在启动前端应用...
pushd frontend
REM 将 Vite 输出重定向到日志文件，避免控制台输出
start "" /b cmd /c "npm run dev > ..\logs\vite.log 2>&1"
popd

REM Wait for services to be ready (multiple retries)
set /a __tries=0
:wait_ready
set /a __tries+=1
if %__tries% gtr 15 goto show_done

REM Check backend health
netstat -ano | findstr ":19002" >nul 2>&1
if errorlevel 1 (
  echo 等待后端服务启动...(%__tries%/15)
  timeout /t 1 /nobreak >nul
  goto wait_ready
)

REM Check frontend port
netstat -ano | findstr ":19001" >nul 2>&1
if errorlevel 1 (
  echo 等待前端应用启动...(%__tries%/15)
  timeout /t 1 /nobreak >nul
  goto wait_ready
)

:show_done
echo.
echo ✓ 服务启动成功！
echo.
echo 访问地址:
echo   - 前端应用: http://localhost:19001
echo   - 后端 API: http://localhost:19002
echo   - API 文档: http://localhost:19002/docs
echo.
echo 提示: 按 Ctrl+C 可停止所有服务 在运行结束前 请不要关闭本窗口
echo.
echo 实时日志:
echo.

REM Keep window open, continue displaying output from two background tasks
REM (Using start /b has already merged subprocess output to current console)
pause >nul

