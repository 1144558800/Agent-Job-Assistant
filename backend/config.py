# -*- coding: utf-8 -*-
"""
Agent 求职筛选助手 - 配置文件
敏感配置通过 .env 环境变量管理，不在此文件中硬编码。
复制 .env.example 为 .env 并填入你的密钥后使用。
"""
import os
from pathlib import Path

# 尝试加载 .env 文件（如果 python-dotenv 已安装）
try:
    from dotenv import load_dotenv
    # 先从项目根目录加载
    _root_env = Path(__file__).resolve().parent.parent / ".env"
    if _root_env.exists():
        load_dotenv(_root_env)
    # 再从 backend 目录加载
    _backend_env = Path(__file__).resolve().parent / ".env"
    if _backend_env.exists():
        load_dotenv(_backend_env, override=True)
except ImportError:
    pass

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# FAISS 索引存储路径（Agent版本使用独立路径，不与原版冲突）
_ascii_data_dir = os.environ.get("TEMP", str(Path.home() / "AppData" / "Local" / "Temp"))
FAISS_INDEX_DIR = Path(_ascii_data_dir) / "agent_job_assistant_faiss"
FAISS_INDEX_DIR.mkdir(parents=True, exist_ok=True)

# 数据存储目录
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# 爬取结果存储
SCRAPED_DATA_DIR = DATA_DIR / "scraped"
SCRAPED_DATA_DIR.mkdir(exist_ok=True)

# 上传文件存储
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# 定时任务存储
SCHEDULE_DIR = DATA_DIR / "schedules"
SCHEDULE_DIR.mkdir(exist_ok=True)

# 文档存储
DOCUMENTS_DIR = DATA_DIR / "documents"
DOCUMENTS_DIR.mkdir(exist_ok=True)

# Embedding 模型配置
EMBEDDING_MODEL_NAME = "shibing624/text2vec-base-chinese"

# 高德地图 API 配置（用于地点搜索等功能，可选）
AMAP_API_KEY = os.getenv("AMAP_API_KEY", "")

# AI 模型配置（必填，推荐使用 DeepSeek）
AI_PROVIDER = os.getenv("AI_PROVIDER", "openai")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_API_BASE = os.getenv("AI_API_BASE", "https://api.deepseek.com")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-chat")

# Ollama 本地部署配置（可选，用于离线场景）
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

# 服务器配置
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8001

# 爬虫配置
SCRAPER_TIMEOUT = 30
SCRAPER_DELAY = 2

# Hermes 自进化配置
HERMES_ENABLED = True                # 是否启用自进化功能
HERMES_AUTO_REFLECT_THRESHOLD = 10   # 累积多少条经验后自动触发反思（0=仅手动触发）
HERMES_MAX_EXPERIENCES = 500         # 最大经验记录数
HERMES_INSIGHT_INJECT = True         # 是否将洞察注入对话上下文（作为用户消息的一部分，不影响 Prompt Caching）

# Guardrails 约束配置
GUARDRAILS_ENABLED = True               # 是否启用约束防护
GUARDRAILS_DAILY_APPLY_LIMIT = 30       # 单日投递硬上限
GUARDRAILS_CONSECUTIVE_FAIL_LIMIT = 5   # 连续失败N次后触发熔断
GUARDRAILS_FAIL_COOLDOWN_MINUTES = 60   # 熔断冷却时间（分钟）
GUARDRAILS_SAME_PLATFORM_INTERVAL_SEC = 90  # 同平台最小投递间隔（秒）
GUARDRAILS_CONFIRM_THRESHOLD = 10       # 单次投递超过N个时提醒分批
GUARDRAILS_CONTENT_BLOCK_PATTERNS = []  # 自定义内容审核敏感词，格式: [{"pattern": "正则", "reason": "原因"}]

# 城市编码映射表
CITY_CODE_MAP = {
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "成都": "101270100",
    "南京": "101190100",
    "武汉": "101200100",
    "西安": "101110100",
    "重庆": "101040100",
    "苏州": "101190400",
    "天津": "101030100",
    "长沙": "101250100",
    "郑州": "101180100",
    "东莞": "101281600",
    "青岛": "101120200",
    "沈阳": "101070100",
    "宁波": "101210400",
    "昆明": "101290100",
    "大连": "101070200",
    "厦门": "101230200",
    "合肥": "101220100",
    "佛山": "101280300",
    "福州": "101230100",
    "哈尔滨": "101050100",
    "济南": "101120100",
    "温州": "101210700",
    "长春": "101060100",
    "石家庄": "101090100",
    "常州": "101191100",
    "泉州": "101230500",
    "南宁": "101300100",
    "贵阳": "101260100",
    "南昌": "101240100",
    "太原": "101100100",
    "烟台": "101120500",
    "嘉兴": "101210300",
    "南通": "101190500",
    "金华": "101210900",
    "珠海": "101280700",
    "惠州": "101280300",
    "徐州": "101190800",
    "海口": "101310100",
    "乌鲁木齐": "101130100",
    "绍兴": "101210500",
    "中山": "101281700",
    "台州": "101210600",
    "兰州": "101160100",
}
