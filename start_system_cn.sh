#!/bin/bash

################################################################################
# LLM-Filter-Probe - One-Click Startup Script
# Supported: macOS, Linux
# Features: Auto-check dependencies, install dependencies, start backend and frontend
################################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create logs directory
mkdir -p logs

echo ""
echo "================================================================================"
echo -e "${BLUE}  LLM-Filter-Probe - 启动中${NC}"
echo "================================================================================"
echo ""

################################################################################
# Step 1: Check Environment
################################################################################

echo -e "${BLUE}[1/5] 检查系统环境...${NC}"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}错误: 未找到 Python3${NC}"
    echo "  请从 https://www.python.org 下载并安装 Python 3.9+"
    exit 1
fi
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo -e "${GREEN}✓ Python ${PYTHON_VERSION}${NC}"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}错误: 未找到 Node.js${NC}"
    echo "  请从 https://nodejs.org 下载并安装 Node.js 16.0+"
    exit 1
fi
NODE_VERSION=$(node --version)
echo -e "${GREEN}✓ Node.js ${NODE_VERSION}${NC}"

# Check npm
if ! command -v npm &> /dev/null; then
    echo -e "${RED}错误: 未找到 npm${NC}"
    echo "  npm 应该随 Node.js 一起安装"
    exit 1
fi
NPM_VERSION=$(npm --version)
echo -e "${GREEN}✓ npm ${NPM_VERSION}${NC}"

echo ""

################################################################################
# Step 2: Check Project Structure
################################################################################

echo -e "${BLUE}[2/5] 检查项目文件...${NC}"
echo ""

if [ ! -f "backend/app.py" ]; then
    echo -e "${RED}错误: 后端文件未找到${NC}"
    echo "  请确保在项目根目录运行此脚本"
    exit 1
fi
echo -e "${GREEN}✓ 后端文件${NC}"

if [ ! -f "frontend/package.json" ]; then
    echo -e "${RED}错误: 前端文件未找到${NC}"
    echo "  请确保在项目根目录运行此脚本"
    exit 1
fi
echo -e "${GREEN}✓ 前端文件${NC}"

echo ""

################################################################################
# Step 3: Create venv and Install Backend Dependencies
################################################################################

echo -e "${BLUE}[3/5] 检查并配置后端环境 (venv)...${NC}"
echo ""

if [ ! -d "backend/venv" ]; then
    echo "  未找到虚拟环境，正在创建 venv..."
    python3 -m venv backend/venv > logs/venv_setup.log 2>&1
    if [ $? -ne 0 ]; then
        echo -e "${RED}错误: 创建 Python 虚拟环境失败${NC}"
        echo "  请检查 Python 是否已正确安装"
        echo "  日志: logs/venv_setup.log"
        exit 1
    fi
    echo -e "${GREEN}  ✓ 虚拟环境创建成功${NC}"
else
    echo -e "${GREEN}  ✓ 虚拟环境已存在${NC}"
fi

echo "  正在激活虚拟环境并安装依赖..."
source backend/venv/bin/activate
pip install -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn
if [ $? -ne 0 ]; then
    echo -e "${RED}错误: 后端依赖安装失败${NC}"
    echo "  请尝试手动运行: source backend/venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi
deactivate
echo -e "${GREEN}✓ 后端依赖已就绪${NC}"

echo ""

################################################################################
# Step 4: Install Frontend Dependencies
################################################################################

echo -e "${BLUE}[4/5] 检查前端依赖...${NC}"
echo ""

if [ ! -d "frontend/node_modules" ]; then
    echo "  正在安装前端依赖，请稍候..."
    cd frontend
    npm install --legacy-peer-deps --registry=https://registry.npmmirror.com
    if [ $? -ne 0 ]; then
        echo -e "${RED}错误: 前端依赖安装失败${NC}"
        echo "  请尝试手动安装: npm install"
        cd ..
        exit 1
    fi
    cd ..
fi
echo -e "${GREEN}✓ 前端依赖已就绪${NC}"

echo ""

################################################################################
# Step 5: Start Services
################################################################################

echo -e "${BLUE}[5/5] 启动服务...${NC}"
echo ""

# Function to cleanup on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}正在关闭服务...${NC}"
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    wait $BACKEND_PID 2>/dev/null || true
    wait $FRONTEND_PID 2>/dev/null || true
    echo -e "${GREEN}✓ 服务已关闭${NC}"
    exit 0
}

# Set trap to cleanup on Ctrl+C
trap cleanup SIGINT SIGTERM

echo "正在启动后端服务..."
source backend/venv/bin/activate
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 19002 --reload --log-level warning > ../logs/backend.log 2>&1 &
BACKEND_PID=$!
cd ..
deactivate

# Wait for backend to start
sleep 3

echo "正在启动前端应用..."
cd frontend
npm run dev > ../logs/vite.log 2>&1 &
FRONTEND_PID=$!
cd ..

# Wait for frontend to start
sleep 3

echo ""
echo -e "${GREEN}✓ 服务启动成功！${NC}"
echo ""
echo -e "${BLUE}访问地址:${NC}"
echo "  - 前端应用: http://localhost:19001"
echo "  - 后端 API: http://localhost:19002"
echo "  - API 文档: http://localhost:19002/docs"
echo ""
echo -e "${YELLOW}提示: 按 Ctrl+C 可停止所有服务${NC}"
echo ""
echo -e "${BLUE}实时日志:${NC}"
echo "  - 后端日志: logs/backend.log"
echo "  - 前端日志: logs/vite.log"
echo ""

# Wait for both processes
wait $BACKEND_PID $FRONTEND_PID

