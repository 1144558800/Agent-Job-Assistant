# -*- coding: utf-8 -*-
"""
爬虫基类
"""
import time
import random
from abc import ABC, abstractmethod
from typing import List, Optional
from pydantic import BaseModel
from loguru import logger
import httpx
from bs4 import BeautifulSoup

class JobItem(BaseModel):
    """岗位信息数据模型"""
    platform: str = ""  # 招聘平台名称
    platform_job_id: str = ""  # 平台岗位ID（如BOSS的encryptId，用于投递/沟通）
    job_name: str = ""  # 岗位名称
    company_name: str = ""  # 公司名称
    company_info: str = ""  # 公司介绍/简介
    company_industry: str = ""  # 公司行业领域
    company_size: str = ""  # 公司规模
    salary: str = ""  # 薪资待遇
    location: str = ""  # 工作地点
    responsibilities: str = ""  # 岗位职责
    requirements: str = ""  # 技能要求
    job_url: str = ""  # 岗位链接
    company_address: str = ""  # 公司地址(用于地图)

class BaseScraper(ABC):
    """爬虫基类"""
    
    def __init__(self):
        self.headers = {
            "User-Agent": self._get_random_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Cache-Control": "max-age=0",
        }
        self.timeout = 30
    
    def _get_random_ua(self) -> str:
        """获取随机 User-Agent"""
        ua_list = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        ]
        return random.choice(ua_list)
    
    def _delay(self):
        """请求延迟，避免被封"""
        delay = random.uniform(1, 3)
        time.sleep(delay)
    
    async def _fetch(self, url: str) -> Optional[str]:
        """发送 HTTP 请求"""
        try:
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True
            ) as client:
                response = await client.get(url)
                response.encoding = "utf-8"
                if response.status_code == 200:
                    return response.text
                else:
                    logger.warning(f"请求失败 {url}: HTTP {response.status_code}")
                    return None
        except Exception as e:
            logger.error(f"请求异常 {url}: {str(e)}")
            return None
    
    @abstractmethod
    async def search(self, keyword: str, city: str = "", page: int = 1) -> List[JobItem]:
        """搜索岗位"""
        pass
    
    @abstractmethod
    async def parse_job_detail(self, url: str) -> Optional[JobItem]:
        """解析岗位详情"""
        pass
