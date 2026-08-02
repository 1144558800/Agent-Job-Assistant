# -*- coding: utf-8 -*-
"""
爬虫管理器 - 统一管理所有平台的爬虫
每个平台使用 Playwright 进行真实浏览器抓取
支持并行搜索多个平台
"""
import asyncio
import time
import traceback
from typing import List, Optional, Dict
from loguru import logger

from .base import JobItem
from .boss import BossScraper
from .liepin import LiepinScraper
from .job51 import Job51Scraper
from .zhaopin import ZhaopinScraper
from .company_info import CompanyInfoCollector


class ScraperManager:
    """爬虫管理器"""

    def __init__(self):
        self.scrapers = {
            "boss": BossScraper(),
            "liepin": LiepinScraper(),
            "51job": Job51Scraper(),
            "zhaopin": ZhaopinScraper(),
        }
        self.company_collector = CompanyInfoCollector(max_jobs=10)
        self._last_search_results = []  # 缓存最近一次搜索结果，供 Agent Tools 使用

    async def search_all(self, keyword: str, city: str = "", page: int = 1, platforms: Optional[List[str]] = None) -> List[JobItem]:
        """在所有平台并行搜索，返回所有平台的岗位列表
        platforms: 可选，指定要搜索的平台ID列表，如 ["boss", "zhaopin"]，不指定则搜索全部
        """
        t_start = time.time()
        all_jobs = []

        # 确定要搜索的平台
        if platforms:
            target_scrapers = {k: v for k, v in self.scrapers.items() if k in platforms}
        else:
            target_scrapers = self.scrapers

        logger.info("[ScraperManager] === 开始搜索 ===")
        logger.info("[ScraperManager] keyword={}, city={}, page={}, platforms={}", 
                    keyword, city, page, list(target_scrapers.keys()))

        # 并行执行所有平台的搜索
        async def _search_one(name: str, scraper) -> tuple:
            t_pf_start = time.time()
            try:
                logger.info("[{}] 开始搜索（线程池模式）...", name)

                # 在线程中运行 Playwright 搜索
                def _run_in_thread():
                    return asyncio.run(scraper.search(keyword, city, page))

                loop = asyncio.get_running_loop()
                jobs = await loop.run_in_executor(None, _run_in_thread)

                t_pf_elapsed = time.time() - t_pf_start
                if jobs:
                    logger.info("[{}] 搜索完成: {} 个岗位, 耗时={:.2f}s", name, len(jobs), t_pf_elapsed)
                    for i, j in enumerate(jobs[:2]):
                        logger.info("[{}]   示例{}: {} | {} | {}", name, i+1, j.job_name, j.company_name, j.salary)
                else:
                    logger.warning("[{}] 未获取到数据, 耗时={:.2f}s", name, t_pf_elapsed)
                return (name, jobs)
            except Exception as e:
                t_pf_elapsed = time.time() - t_pf_start
                logger.error("[{}] 搜索异常: type={}, msg={}, 耗时={:.2f}s", name, type(e).__name__, str(e), t_pf_elapsed)
                logger.error("[{}] 异常堆栈:\n{}", name, traceback.format_exc())
                return (name, [])

        tasks = []
        for name, scraper in target_scrapers.items():
            tasks.append(_search_one(name, scraper))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error("[ScraperManager] asyncio.gather 异常: type={}, msg={}", type(result).__name__, str(result))
                logger.error("[ScraperManager] 异常堆栈:\n{}", traceback.format_exc())
                continue
            platform_name, jobs = result
            all_jobs.extend(jobs)

        t_elapsed = time.time() - t_start
        logger.info("[ScraperManager] === 搜索结束 ===")
        logger.info("[ScraperManager] 总耗时={:.2f}s, 总岗位数={}", t_elapsed, len(all_jobs))
        
        # 按平台统计
        platform_counts = {}
        for j in all_jobs:
            p = j.platform or "未知"
            platform_counts[p] = platform_counts.get(p, 0) + 1
        logger.info("[ScraperManager] 平台分布: {}", platform_counts)

        # 搜索结果按城市过滤
        if city and all_jobs:
            before_filter = len(all_jobs)
            filtered_jobs = []
            city_keywords = [city]
            if city == "北京":
                city_keywords.append("北京市")
            elif city == "上海":
                city_keywords.append("上海市")
            elif city == "广州":
                city_keywords.append("广州市")
            elif city == "深圳":
                city_keywords.append("深圳市")
            elif city == "南京":
                city_keywords.append("南京市")
            elif city == "杭州":
                city_keywords.append("杭州市")
            elif city == "成都":
                city_keywords.append("成都市")
            elif city == "武汉":
                city_keywords.append("武汉市")
            elif city == "苏州":
                city_keywords.append("苏州市")
            for j in all_jobs:
                loc = j.location or ""
                for ck in city_keywords:
                    if ck in loc:
                        filtered_jobs.append(j)
                        break
            all_jobs = filtered_jobs
            logger.info("[ScraperManager] 城市过滤前={}, 过滤后={}(城市={})", before_filter, len(all_jobs), city)

        if not all_jobs:
            logger.warning("[ScraperManager] 所有平台均未返回数据！请检查各平台登录状态和网络连接。")

        # 缓存搜索结果供 Agent Tools 使用
        self._last_search_results = all_jobs

        # 搜索完成后，异步后台采集公司信息
        if all_jobs:
            logger.info("[ScraperManager] 后台开始采集公司信息...")
            asyncio.create_task(self._collect_company_info_async(all_jobs))

        return all_jobs

    async def search_platform(self, platform: str, keyword: str, city: str = "", page: int = 1) -> List[JobItem]:
        """在指定平台搜索，并采集公司信息"""
        scraper = self.scrapers.get(platform)
        if not scraper:
            logger.warning("未知平台: {}", platform)
            return []

        try:
            jobs = await scraper.search(keyword, city, page)
            if jobs:
                # 缓存搜索结果供 Agent Tools 使用
                self._last_search_results = jobs
                # 异步后台采集公司信息
                logger.info("[{}] 搜索完成，获取到 {} 个岗位，后台开始采集公司信息...", platform, len(jobs))
                asyncio.create_task(self._collect_company_info_async(jobs))
            else:
                logger.warning("[{}] 未获取到数据", platform)
            return jobs
        except Exception as e:
            logger.error("[{}] 搜索失败: {}", platform, e)
            return []

    async def _collect_company_info_async(self, jobs: List[JobItem]) -> None:
        """后台异步采集公司信息"""
        try:
            await self.company_collector.collect(jobs)
            filled = sum(1 for j in jobs if j.company_info and len(j.company_info) > 20)
            logger.info("后台公司信息采集完成: {}/{} 个岗位已有公司介绍", filled, len(jobs))
        except Exception as e:
            logger.warning("后台公司信息采集失败(DeepSeek将补充): {} - {}", type(e).__name__, e)

    def get_supported_platforms(self) -> list:
        """获取支持的平台列表"""
        return [
            {"id": "boss", "name": "BOSS直聘"},
            {"id": "liepin", "name": "猎聘"},
            {"id": "51job", "name": "前程无忧"},
            {"id": "zhaopin", "name": "智联招聘"},
        ]
