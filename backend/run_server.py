# -*- coding: utf-8 -*-
"""启动服务器脚本"""
import uvicorn
from config import SERVER_HOST, SERVER_PORT

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=False,
        log_level="info",
    )
