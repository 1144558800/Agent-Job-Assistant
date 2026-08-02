# -*- coding: utf-8 -*-
"""
Agent 求职筛选助手 - FastAPI 主应用
"""
import os
import sys
from contextlib import asynccontextmanager
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from config import SERVER_HOST, SERVER_PORT, UPLOAD_DIR
from api.routes import router as api_router

# 配置日志
logger.add(
    "logs/app.log",
    rotation="10 MB",
    retention="7 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    encoding="utf-8",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("Agent 求职筛选助手启动中...")
    
    # 启动定时任务调度器
    from scheduler.scheduler import get_scheduler
    scheduler = get_scheduler()
    scheduler.start()
    
    # 预加载 Agent
    from agent.graph import get_agent
    get_agent()
    logger.info("Agent 已就绪")
    
    yield
    
    # 关闭
    scheduler.shutdown()
    logger.info("Agent 求职筛选助手已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="Agent 求职筛选助手",
    description="基于 LangGraph Agent 的智能求职筛选助手，通过对话完成岗位搜索、分析、匹配等操作",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(api_router, prefix="/api")

# 静态文件服务（上传文件访问）
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# 前端静态文件（生产模式）
frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "Agent 求职筛选助手"}


@app.get("/api/status")
async def api_status():
    return {"status": "ok", "service": "Agent 求职筛选助手"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=True,
        log_level="info",
    )
