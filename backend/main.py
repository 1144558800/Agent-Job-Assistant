# -*- coding: utf-8 -*-
"""
FastAPI 主应用 - Agent 求职筛选助手
"""
import sys
import os
from contextlib import asynccontextmanager
from pathlib import Path

# 确保 backend 目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from api.routes import router as api_router
from config import UPLOAD_DIR, POLISHED_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=" * 50)
    logger.info("Agent 求职筛选助手 - 后端启动中...")
    logger.info("=" * 50)

    # 启动定时任务调度器
    try:
        from scheduler.scheduler import get_scheduler
        scheduler = get_scheduler()
        scheduler.start()
        logger.info("[定时任务] 调度器已启动")
    except Exception as e:
        logger.warning(f"[定时任务] 调度器启动失败（可能缺少依赖）: {e}")

    yield

    # 关闭时清理
    try:
        from scheduler.scheduler import get_scheduler
        scheduler = get_scheduler()
        scheduler.shutdown()
        logger.info("[定时任务] 调度器已关闭")
    except Exception:
        pass

    logger.info("Agent 求职筛选助手 - 后端已停止")


app = FastAPI(
    title="Agent 求职筛选助手",
    description="AI 智能求职筛选与自动化沟通系统",
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

# 挂载上传目录为静态文件服务（允许前端访问上传的简历）
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/polished", StaticFiles(directory=str(POLISHED_DIR)), name="polished")

# 注册路由
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "Agent 求职筛选助手 API", "version": "2.0.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}
