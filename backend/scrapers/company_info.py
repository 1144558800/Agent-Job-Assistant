# -*- coding: utf-8 -*-
"""
公司信息采集器 - 搜索公司背景、融资、员工评价等信息
使用 Playwright 搜索 + DeepSeek AI 补充
"""
import re
import time
import json
import traceback
from typing import List, Dict, Optional, Set
from urllib.parse import quote
from loguru import logger
from playwright.async_api import async_playwright

from config import AI_API_KEY, AI_API_BASE, AI_MODEL


class CompanyInfoCollector:
    """公司信息采集器"""

    def __init__(self, max_jobs: int = 20):
        self.cache: Dict[str, str] = {}
        self._ai_client = None
        self.max_jobs = max_jobs

    def _get_ai_client(self):
        if self._ai_client is None:
            try:
                from openai import OpenAI
                self._ai_client = OpenAI(api_key=AI_API_KEY, base_url=AI_API_BASE)
            except Exception:
                pass
        return self._ai_client

    async def collect(self, jobs: list, resume_text: str = "") -> list:
        """
        采集公司信息并填充到岗位数据中
        jobs: JobItem 列表
        resume_text: 可选，求职者简历文本，用于 AI 分析时结合求职者背景
        """
        # 去重公司列表
        companies: Set[str] = set()
        for j in jobs:
            cn = (j.company_name if hasattr(j, 'company_name') else j.get('company_name', ''))
            if cn and cn not in companies:
                companies.add(cn)

        companies = set(list(companies)[:self.max_jobs])
        logger.info("[公司采集] 待采集公司: {} 家", len(companies))

        # 逐公司搜索
        for company_name in companies:
            if company_name in self.cache:
                continue
            info = await self._search_company(company_name)
            if info:
                self.cache[company_name] = info
            else:
                self.cache[company_name] = ""

        # 填充到岗位数据
        filled = 0
        for j in jobs:
            cn = (j.company_name if hasattr(j, 'company_name') else j.get('company_name', ''))
            if cn and cn in self.cache and self.cache[cn]:
                if hasattr(j, 'company_info'):
                    j.company_info = self.cache[cn]
                elif isinstance(j, dict):
                    j['company_info'] = self.cache[cn]
                filled += 1

        logger.info("[公司采集] 完成: {}/{} 个岗位已填充公司信息", filled, len(jobs))

        # AI 补充信息
        await self._ai_supplement(jobs, resume_text)

        return jobs

    async def _search_company(self, company_name: str) -> Optional[str]:
        """搜索单个公司的信息"""
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    locale="zh-CN",
                )
                page = await context.new_page()

                search_url = f"https://www.baidu.com/s?wd={quote(company_name + ' 公司介绍')}"
                await page.goto(search_url, wait_until="domcontentloaded", timeout=10000)
                await page.wait_for_timeout(2000)

                # 尝试提取搜索结果摘要
                html = await page.content()
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')

                results = []
                for item in soup.select('.c-container, .result, [class*="result"]'):
                    text = item.get_text(strip=True)
                    if len(text) > 30:
                        results.append(text)

                info = "\n".join(results[:5])[:2000] if results else ""

                await context.close()
                await browser.close()

                if info:
                    logger.info("[公司采集] {} - 获取到 {} 字符", company_name, len(info))
                else:
                    logger.warning("[公司采集] {} - 未获取到信息", company_name)

                return info
        except Exception as e:
            logger.warning("[公司采集] {} 搜索失败: {}", company_name, e)
            return None

    async def _ai_supplement(self, jobs: list, resume_text: str = ""):
        """使用 AI 补充公司信息（深度解析）"""
        client = self._get_ai_client()
        if not client:
            return

        # 仅处理没有公司介绍的岗位
        no_info_jobs = []
        for j in jobs:
            info = j.company_info if hasattr(j, 'company_info') else j.get('company_info', '')
            if not info or len(info) < 20:
                no_info_jobs.append(j)

        if not no_info_jobs:
            return

        logger.info("[公司采集] AI 补充 {} 个岗位的公司信息", len(no_info_jobs))

        jobs_summary = []
        for j in no_info_jobs[:10]:  # 每次最多10个
            cn = j.company_name if hasattr(j, 'company_name') else j.get('company_name', '')
            jn = j.job_name if hasattr(j, 'job_name') else j.get('job_name', '')
            jobs_summary.append(f"- {cn}: {jn}")

        resume_hint = ""
        if resume_text:
            resume_hint = f"\n求职者背景（请根据求职者技术栈，补充与岗位相关的技术关键词）:\n{resume_text[:800]}"

        try:
            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=[{
                    "role": "system",
                    "content": "你是公司信息分析师。" + resume_hint
                }, {
                    "role": "user",
                    "content": f"请简要介绍以下公司（每家公司2-3句话，50字以内）：\n" + "\n".join(jobs_summary)
                }],
                temperature=0.5,
                max_tokens=2000,
            )

            ai_text = response.choices[0].message.content
            logger.info("[公司采集] AI 返回 {} 字符", len(ai_text))

            # 解析并填充
            for j in no_info_jobs:
                cn = j.company_name if hasattr(j, 'company_name') else j.get('company_name', '')
                if cn and cn in ai_text:
                    for line in ai_text.split('\n'):
                        if cn in line:
                            info_text = line.split(cn, 1)[-1].strip().lstrip('：:').strip()[:200]
                            if hasattr(j, 'company_info'):
                                j.company_info = info_text
                            else:
                                j['company_info'] = info_text
                            break
        except Exception as e:
            logger.warning("[公司采集] AI 补充失败: {}", e)
