# -*- coding: utf-8 -*-
"""
Pydantic 请求/响应模型
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class ChatRequest(BaseModel):
    """对话请求"""
    message: str = Field(..., description="用户消息")
    thread_id: str = Field(default="default", description="对话线程ID")


class FilePreviewRequest(BaseModel):
    """文件预览请求"""
    thread_id: str = Field(..., description="对话线程ID")
    filename: str = Field(..., description="文件名")


class UploadResponse(BaseModel):
    """文件上传响应"""
    success: bool
    file_name: str
    file_path: str
    resume_data: Optional[Dict[str, Any]] = None


class StatusResponse(BaseModel):
    """系统状态响应"""
    faiss_total: int = 0
    boss_online: bool = False
    memory_insights_count: int = 0


class CookieStatusResponse(BaseModel):
    """Cookie 状态响应"""
    platform: str
    has_cookies: bool
    valid: bool


class LoginResponse(BaseModel):
    """登录触发响应"""
    platform: str
    logged_in: bool


class ScheduleRequest(BaseModel):
    """定时任务请求"""
    keyword: str = Field(..., description="搜索关键词")
    city: str = Field(default="", description="城市")
    cron: str = Field(..., description="Cron 表达式")
    platforms: Optional[str] = Field(default=None, description="平台列表，逗号分隔")


class ScheduleResponse(BaseModel):
    """定时任务响应"""
    success: bool
    job_id: Optional[str] = None
    message: str


class ExportRequest(BaseModel):
    """导出请求"""
    jobs: List[Dict[str, Any]] = Field(..., description="要导出的岗位列表")
    format: str = Field(default="excel", description="导出格式: excel 或 csv")
    filename: Optional[str] = Field(default=None, description="文件名")


class ExportResponse(BaseModel):
    """导出响应"""
    success: bool
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    count: int = 0
    message: str = ""
