"""Vercel Serverless Python 入口 — 客来来 FastAPI 后端。"""

import os
import sys
from pathlib import Path

# 将项目根目录加入 sys.path，使 `backend` 包可被正确导入
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Serverless 环境下数据目录指向 /tmp（Vercel 只允许写入 /tmp）
os.environ.setdefault("KELLAI_DATA_DIR", "/tmp")

# Vercel Serverless 环境：跳过生产环境严格校验（sys.exit 会杀掉函数实例）
# 安全由环境变量 KELLAI_JWT_SECRET 保证
os.environ.setdefault("KELLAI_APP_ENV", "development")
os.environ.setdefault("KELLAI_STRICT_AUTH", "0")

# 导入 FastAPI 实例，Vercel Python Runtime 会自动识别 ASGI app
from backend.app.main import app  # noqa: E402
