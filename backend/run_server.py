# -*- coding: utf-8 -*-
"""
后端服务启动脚本
"""
import os
import sys
import uvicorn

if __name__ == "__main__":
    # 确保当前目录在路径中
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info",
    )
