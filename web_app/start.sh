#!/bin/bash

# 注塑成型工艺参数智能推荐系统 - Web 版启动脚本

set -e

echo "🚀 启动注塑成型工艺参数智能推荐系统 (Web 版)"
echo "=============================================="

# 检查是否在项目目录
cd "$(dirname "$0")"

# 检查虚拟环境
if [ -f ../.venv/bin/activate ]; then
    echo "📦 激活虚拟环境..."
    source ../.venv/bin/activate
elif [ -f .venv/bin/activate ]; then
    echo "📦 激活虚拟环境..."
    source .venv/bin/activate
fi

# 安装依赖（如果未安装）
echo "📥 检查依赖..."
if ! python -c "import fastapi" 2>/dev/null; then
    echo "安装依赖..."
    uv pip install -e "." || pip install -e "."
fi

# 确保目录存在
mkdir -p checkpoints
mkdir -p static

# 复制前端文件到 static 目录
echo "📁 准备静态文件..."
cp -r frontend/* static/ 2>/dev/null || true

# 启动服务器
echo ""
echo "🌐 启动服务器..."
echo "访问地址: http://localhost:8000"
echo "API 文档: http://localhost:8000/docs"
echo "按 Ctrl+C 停止"
echo ""

cd backend
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
