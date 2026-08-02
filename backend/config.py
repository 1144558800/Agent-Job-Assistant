# -*- coding: utf-8 -*-
"""
全局配置文件
"""
import os
from pathlib import Path

# ---- 项目根目录 ----
BASE_DIR = Path(__file__).resolve().parent.parent

# ---- AI 配置 ----
AI_API_KEY = os.getenv("AI_API_KEY", "sk-your-deepseek-api-key")
AI_API_BASE = os.getenv("AI_API_BASE", "https://api.deepseek.com")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-chat")

# ---- 文件上传 ----
UPLOAD_DIR = BASE_DIR / os.getenv("UPLOAD_DIR", "uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 简历润色输出目录
POLISHED_DIR = BASE_DIR / os.getenv("POLISHED_DIR", "polished_resumes")
POLISHED_DIR.mkdir(parents=True, exist_ok=True)

# ---- RAG 配置 ----
FAISS_INDEX_DIR = BASE_DIR / os.getenv("FAISS_INDEX_DIR", "data/faiss_index")
FAISS_INDEX_DIR.mkdir(parents=True, exist_ok=True)

# ---- 定时任务配置 ----
SCHEDULE_DIR = BASE_DIR / os.getenv("SCHEDULE_DIR", "data/schedules")
SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)

# ---- 支持的城市列表 ----
SUPPORTED_CITIES = [
    "北京", "上海", "广州", "深圳", "杭州", "南京", "苏州", "成都",
    "武汉", "西安", "长沙", "重庆", "天津", "郑州", "合肥", "宁波",
    "青岛", "厦门", "大连", "沈阳", "济南", "福州", "哈尔滨", "长春",
    "珠海", "佛山", "东莞", "无锡", "常州", "昆明", "贵阳", "南宁",
    "海口", "太原", "兰州", "石家庄",
]

# ---- 支持的招聘平台 ----
SUPPORTED_PLATFORMS = [
    {"id": "boss", "name": "BOSS直聘"},
    {"id": "liepin", "name": "猎聘"},
    {"id": "51job", "name": "前程无忧"},
    {"id": "zhaopin", "name": "智联招聘"},
]

# ---- Ollama 本地模型配置 ----
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

# ---- Guardrails 安全配置 ----
MAX_APPLY_PER_HOUR = int(os.getenv("MAX_APPLY_PER_HOUR", "30"))
SAFETY_WINDOW = int(os.getenv("SAFETY_WINDOW", "3600"))

# ---- 输出校验配置 ----
OUTPUT_MAX_LENGTH = 8000          # 单次回复最大长度（字符）
OUTPUT_MIN_RESPONSE = 50          # 非工具调用回复，最小有效长度
