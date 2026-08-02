# -*- coding: utf-8 -*-
"""
爬虫基类 - 定义 JobItem 数据模型和 BaseScraper 抽象接口
"""
from typing import List, Optional, Dict
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field


class JobItem(BaseModel):
    """招聘岗位数据模型"""
    # 基本信息
    job_name: str = ""           # 岗位名称
    company_name: str = ""       # 公司名称
    salary: str = ""             # 薪资
    location: str = ""           # 工作地点
    platform: str = ""           # 来源平台
    platform_job_id: str = ""    # 平台上的岗位 ID
    job_url: str = ""            # 岗位详情链接

    # 详细信息
    responsibilities: str = ""   # 岗位职责
    requirements: str = ""       # 任职要求
    education: str = ""          # 学历要求
    experience: str = ""         # 经验要求

    # 公司信息
    company_industry: str = ""   # 公司行业
    company_size: str = ""       # 公司规模
    company_info: str = ""       # 公司介绍
    company_address: str = ""    # 公司地址

    # 其他
    welfare: str = ""            # 福利待遇
    publish_date: str = ""       # 发布日期


class BaseScraper(ABC):
    """爬虫基类"""

    def __init__(self):
        self.platform = ""
        self.base_url = ""
        self.search_url = ""

    @abstractmethod
    async def search(self, keyword: str, city: str = "", page: int = 1) -> List[JobItem]:
        """搜索岗位"""
        pass

    @abstractmethod
    async def parse_job_detail(self, url: str) -> Optional[JobItem]:
        """解析岗位详情"""
        pass

    @abstractmethod
    def has_cookies(self) -> bool:
        """是否已有 Cookie"""
        pass

    @abstractmethod
    def get_cookies(self) -> list:
        """获取 Cookie"""
        pass

    @abstractmethod
    def save_cookies(self, cookies_str: str = "") -> bool:
        """保存 Cookie"""
        pass

    @abstractmethod
    def verify_cookies(self) -> bool:
        """验证 Cookie 是否有效"""
        pass

    @abstractmethod
    async def manual_login(self) -> tuple:
        """手动登录"""
        pass
