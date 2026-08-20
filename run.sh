#!/bin/bash
# ===========================================
# 法拍监控系统 - 启动脚本 (macOS / Linux)
# ===========================================
export PYTHONIOENCODING=utf-8

# 切到脚本所在目录
cd "$(dirname "$0")"

# 创建虚拟环境（如果不存在）
if [ ! -d ".venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv .venv
fi

# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
echo "安装依赖..."
pip install -q -r requirements.txt

# 启动 Web 服务
echo "=== 启动 Web 服务 ==="
echo "访问 http://127.0.0.1:5002"
echo "如果需要定时跑批，请另开一个终端执行:  python scheduler.py"
python3 web.py
