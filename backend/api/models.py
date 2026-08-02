# -*- coding: utf-8 -*-
"""
API 请求/响应模型
"""
from pydantic import BaseModel
from typing import Optional, List


class ChatRequest(BaseModel):
    """聊天请求"""
    message: str
    thread_id: Optional[str] = "default"  # 会话ID，用于记忆隔离


class ChatResponse(BaseModel):
    """聊天响应"""
    success: bool
    message: str
    data: Optional[dict] = None


class LoginRequest(BaseModel):
    """登录请求"""
    platform: str


class ScheduleListResponse(BaseModel):
    """定时任务列表"""
    success: bool
    jobs: List[dict]


class StatusResponse(BaseModel):
    """系统状态"""
    success: bool
    faiss_total: int
    supported_platforms: List[str]
    model: str
