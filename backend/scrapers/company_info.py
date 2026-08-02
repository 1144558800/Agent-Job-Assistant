# -*- coding: utf-8 -*-
"""
公司信息采集器 - 从各平台职位详情页提取公司介绍等公开信息
通过 DeepSeek AI 补充缺失的公司背景介绍
"""
import os
import re
import json
import asyncio
from typing import List, Optional
from pathlib import Path
from loguru import logger
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

from .base import JobItem

# 设置 Playwright 浏览器路径
_browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(
    Path(__file__).resolve().parent.parent.parent / "playwright-browsers"
)
if os.path.isdir(_browser_path):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browser_path


class CompanyInfoCollector:
    """公司信息采集器 - 批量提取各平台的公司介绍"""

    def __init__(self, max_jobs: int = 10):
        self.max_jobs = max_jobs
        self._ai_client = None

    def _get_ai_client(self):
        """初始化 DeepSeek AI 客户端"""
        if self._ai_client is not None:
            return self._ai_client, self._ai_model
        from openai import OpenAI
        import config as cfg
        self._ai_client = OpenAI(
            api_key=cfg.AI_API_KEY,
            base_url=cfg.AI_API_BASE
        )
        self._ai_model = cfg.AI_MODEL
        return self._ai_client, self._ai_model

    def _call_deepseek_sync(self, client, model, prompt):
        """同步调用 DeepSeek API"""
        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是专业的中国企业信息查询助手，请仔细搜索并回答。返回纯 JSON，不要用 markdown 代码块包裹。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=800,
            extra_body={"enable_search": True}
        )

    async def _enrich_with_deepseek(self, jobs: List[JobItem]) -> None:
        """用 DeepSeek AI 补充缺失的公司信息"""
        company_names = set()
        for job in jobs:
            name = job.company_name.strip()
            if name and len(name) >= 2:
                company_names.add(name)

        if not company_names:
            logger.info("没有公司名需要 AI 补充")
            return

        logger.info(f"DeepSeek 补充公司信息: {len(company_names)} 家公司")
        client, model = self._get_ai_client()

        company_info_cache = {}
        for idx, company_name in enumerate(sorted(company_names)):
            try:
                existing_jobs = [j for j in jobs if j.company_name == company_name]
                has_info = any(j.company_info and len(j.company_info) > 30 for j in existing_jobs)
                if has_info:
                    continue

                prompt = f"""请提供以下中国公司的基本信息，要求真实准确：

公司名称：{company_name}

请用中文返回 JSON 格式（不要用 markdown 代码块标记），包含以下字段：
1. company_intro: 公司简介（1-3句话，100-300字，介绍主营业务、成立时间、定位等）
2. industry: 所属行业
3. company_size: 公司规模（如"500-2000人"）
4. website: 公司官网地址（如果知道的话，不知道就返回空字符串）

如果不知道这家公司，请如实返回：{{"company_intro": "", "industry": "", "company_size": "", "website": ""}}
请直接返回 JSON，不要加任何额外文字。"""

                response = await asyncio.to_thread(self._call_deepseek_sync, client, model, prompt)

                raw = response.choices[0].message.content.strip()
                if raw.startswith("```"):
                    raw = re.sub(r'^```(?:json)?\s*', '', raw)
                    raw = re.sub(r'\s*```$', '', raw)
                raw = raw.strip()

                info = json.loads(raw)
                company_info_cache[company_name] = info
                logger.info(f"DeepSeek 获取 [{company_name}]: 行业={info.get('industry','')}, 简介={len(info.get('company_intro',''))}字")

                for job in existing_jobs:
                    if info.get("company_intro") and len(info["company_intro"]) > 10:
                        job.company_info = info["company_intro"]
                    if info.get("industry"):
                        job.company_industry = info["industry"]
                    if info.get("company_size"):
                        job.company_size = info["company_size"]

            except json.JSONDecodeError:
                logger.warning(f"DeepSeek 返回非 JSON [{company_name}]，尝试用文本重试")
                try:
                    retry_prompt = f"请简要介绍公司：{company_name}\n包括：主营业务、行业、规模（200字以内）"
                    response2 = await asyncio.to_thread(self._call_deepseek_sync, client, model, retry_prompt)
                    text = response2.choices[0].message.content.strip()
                    if text and len(text) > 30:
                        existing_jobs[0].company_info = text[:500]
                        logger.info(f"DeepSeek 文本重试成功 [{company_name}]: {len(text)}字")
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"DeepSeek 查询 [{company_name}] 失败: {e}")

            if (idx + 1) % 5 == 0:
                await asyncio.sleep(1)

        logger.info(f"DeepSeek 补充完成: {len(company_info_cache)}/{len(company_names)} 家公司")

    async def collect(self, jobs: List[JobItem]) -> List[JobItem]:
        """批量采集公司信息，更新 JobItem 并返回"""
        # 第一步：Playwright 从详情页提取
        target_jobs = [j for j in jobs if j.job_url]
        logger.info(f"开始采集公司信息: {len(target_jobs)}/{len(jobs)} 个岗位有详情链接")

        if target_jobs:
            # 分组：按平台分批处理
            platforms = {}
            for job in target_jobs:
                p = job.platform
                if p not in platforms:
                    platforms[p] = []
                platforms[p].append(job)

            # 限制每个平台处理数量
            for p in platforms:
                if len(platforms[p]) > self.max_jobs:
                    logger.info(f"{p} 限制采集 {self.max_jobs}/{len(platforms[p])} 个")
                    platforms[p] = platforms[p][:self.max_jobs]

            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(
                        headless=True,
                        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
                    )
                    context = await browser.new_context(
                        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                                    "Chrome/125.0.0.0 Safari/537.36"),
                        locale="zh-CN",
                        viewport={"width": 1920, "height": 1080},
                    )
                    await context.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    """)

                    for platform_name, platform_jobs in platforms.items():
                        logger.info(f"采集 {platform_name} 公司信息: {len(platform_jobs)} 个")
                        for idx, job in enumerate(platform_jobs):
                            try:
                                await self._extract_company_info(context, job, platform_name)
                                if (idx + 1) % 5 == 0:
                                    logger.info(f"{platform_name}: 已处理 {idx+1}/{len(platform_jobs)}")
                            except Exception as e:
                                logger.warning(f"采集公司信息失败 [{job.job_name}]: {e}")

                    await context.close()
                    await browser.close()
            except Exception as e:
                import traceback
                logger.warning("Playwright 公司信息采集失败（将跳过，由 DeepSeek 补充）: {} - {}", type(e).__name__, e)
                logger.debug("Playwright 详细错误:\n{}", traceback.format_exc())

        # 第二步：DeepSeek AI 补充缺失的公司信息（对所有公司名）
        await self._enrich_with_deepseek(jobs)

        filled = sum(1 for j in jobs if j.company_info and len(j.company_info) > 20)
        logger.info(f"公司信息采集完成: {filled}/{len(jobs)} 个岗位已有公司介绍")
        return jobs

    async def _extract_company_info(self, context, job: JobItem, platform: str):
        """打开职位详情页，提取公司介绍"""
        page = await context.new_page()
        try:
            await page.goto(job.job_url, wait_until="domcontentloaded", timeout=10000)
            await page.wait_for_timeout(1000)

            # 根据平台选择不同的提取策略
            if platform == "猎聘":
                await self._extract_liepin(page, job)
            elif platform == "前程无忧":
                await self._extract_51job(page, job)
            elif platform == "智联招聘":
                await self._extract_zhaopin(page, job)
            elif platform == "BOSS直聘":
                await self._extract_boss(page, job)
            else:
                await self._extract_generic(page, job)
        finally:
            await page.close()

    async def _extract_liepin(self, page, job: JobItem):
        """从猎聘职位详情页提取公司信息"""
        info = await page.evaluate("""
            () => {
                const result = {info: '', industry: '', size: ''};
                // 公司介绍区域
                const introSelectors = [
                    '.company-intro-content',
                    '[class*="company-intro"]',
                    '[class*="company-info"]',
                    '.job-detail-company-desc',
                ];
                for (const sel of introSelectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        result.info = el.textContent.trim().substring(0, 1000);
                        break;
                    }
                }
                // 行业和规模
                const companyTags = document.querySelectorAll('[class*="company-tag"], [class*="tag-item"], [class*="company-label"]');
                const texts = [];
                companyTags.forEach(el => texts.push(el.textContent.trim()));
                if (texts.length > 0) {
                    result.industry = texts[0] || '';
                    if (texts.length > 1) result.size = texts[1] || '';
                }
                if (!result.info) {
                    // 兜底：找详情页中"公司介绍"附近的文本
                    const allText = document.body.innerText;
                    const match = allText.match(/公司介绍[：:]([\\s\\S]{1,500})/);
                    if (match) result.info = match[1].trim();
                }
                return result;
            }
        """)
        if info.get("info"):
            job.company_info = info["info"]
        if info.get("industry"):
            job.company_industry = info["industry"]
        if info.get("size"):
            job.company_size = info["size"]

    async def _extract_51job(self, page, job: JobItem):
        """从前程无忧职位详情页提取公司信息"""
        info = await page.evaluate("""
            () => {
                const result = {info: '', industry: '', size: ''};
                // 公司信息区域 - we.51job.com 新平台的常见类名
                const selectors = [
                    '[class*="company-desc"]',
                    '[class*="com_intro"]',
                    '[class*="company-info"]',
                    '[class*="com-info"]',
                    '[class*="job-company"]',
                    '.cominfo',
                    '.job_detail_company',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        result.info = el.textContent.trim().substring(0, 1000);
                        break;
                    }
                }

                // 如果上面没找到，从整个页面的文本中提取公司介绍
                if (!result.info) {
                    const allText = document.body.innerText;
                    const introMatch = allText.match(/(?:公司介绍|公司简介|关于我们)[：:]([\\s\\S]{1,500}?)(?:\\n{2,}|$)/);
                    if (introMatch) result.info = introMatch[1].trim();
                }

                // 行业信息
                const industrySelectors = [
                    '[class*="industry"]',
                    '[class*="com_name"]',
                    '[class*="com-name"]',
                    '[class*="company-tag"]',
                ];
                for (const sel of industrySelectors) {
                    const el = document.querySelector(sel);
                    if (el && el.textContent.trim()) {
                        result.industry = el.textContent.trim();
                        break;
                    }
                }
                if (!result.industry) {
                    const allText = document.body.innerText;
                    const indMatch = allText.match(/(?:行业|领域)[：:]([^\\n]{1,50})/);
                    if (indMatch) result.industry = indMatch[1].trim();
                }

                // 公司规模
                const sizeMatch = document.body.innerText.match(/(?:规模|人数)[：:]([^\\n]{1,50})/);
                if (sizeMatch) result.size = sizeMatch[1].trim();

                return result;
            }
        """)
        if info.get("info"):
            job.company_info = info["info"]
        if info.get("industry"):
            job.company_industry = info["industry"]
        if info.get("size"):
            job.company_size = info["size"]

        # 如果还是没找到公司介绍，尝试打开公司主页
        if not job.company_info:
            try:
                company_page_url = await page.evaluate("""
                    () => {
                        const links = document.querySelectorAll('a[href*="company"]');
                        for (const link of links) {
                            if (link.href && !link.href.includes('javascript')) return link.href;
                        }
                        return '';
                    }
                """)
                if company_page_url:
                    await page.goto(company_page_url, wait_until="domcontentloaded", timeout=10000)
                    await page.wait_for_timeout(1000)
                    company_text = await page.evaluate("() => document.body.innerText.substring(0, 2000)")
                    # 找公司描述段落（较长的文本块）
                    lines = [l.strip() for l in company_text.split('\n') if len(l.strip()) > 50]
                    if lines:
                        job.company_info = lines[0][:1000]
            except Exception:
                pass

    async def _extract_zhaopin(self, page, job: JobItem):
        """从智联招聘职位详情页提取公司信息"""
        info = await page.evaluate("""
            () => {
                const result = {info: '', industry: '', size: ''};
                // 公司介绍
                const selectors = [
                    '[class*="company-description"]',
                    '[class*="branding-desc"]',
                    '[class*="company-info"]',
                    '.job-company-info',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        result.info = el.textContent.trim().substring(0, 1000);
                        break;
                    }
                }
                // 行业和规模
                const allText = document.body.innerText;
                // 尝试匹配"行业"和"规模"
                const industryMatch = allText.match(/行业[：:]([^\\n]{1,50})/);
                if (industryMatch) result.industry = industryMatch[1].trim();
                const sizeMatch = allText.match(/规模[：:]([^\\n]{1,50})/);
                if (sizeMatch) result.size = sizeMatch[1].trim();
                return result;
            }
        """)
        if info.get("info"):
            job.company_info = info["info"]
        if info.get("industry"):
            job.company_industry = info["industry"]
        if info.get("size"):
            job.company_size = info["size"]

    async def _extract_boss(self, page, job: JobItem):
        """从BOSS直聘职位详情页提取公司信息"""
        info = await page.evaluate("""
            () => {
                const result = {info: '', industry: '', size: ''};
                // BOSS直聘公司信息
                const selectors = [
                    '[class*="company-info-content"]',
                    '[class*="job-sec"]',
                    '[class*="company-intro"]',
                    '.boss-company-info',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        result.info = el.textContent.trim().substring(0, 1000);
                        break;
                    }
                }
                // 行业标签
                const tags = document.querySelectorAll('[class*="tag-item"], [class*="company-tag"]');
                const texts = [];
                tags.forEach(el => texts.push(el.textContent.trim()));
                if (texts.length > 0) result.industry = texts[0] || '';
                if (texts.length > 1) result.size = texts[1] || '';
                return result;
            }
        """)
        if info.get("info"):
            job.company_info = info["info"]
        if info.get("industry"):
            job.company_industry = info["industry"]
        if info.get("size"):
            job.company_size = info["size"]

    async def _extract_generic(self, page, job: JobItem):
        """通用提取方法 - 从页面文本中找公司相关信息"""
        try:
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text("\n", strip=True)

            # 找公司介绍
            patterns = [
                r"公司介绍[：:]\s*(.+?)(?:\n\n|\n$|$)",
                r"公司简介[：:]\s*(.+?)(?:\n\n|\n$|$)",
                r"关于我们[：:]\s*(.+?)(?:\n\n|\n$|$)",
            ]
            for p in patterns:
                match = re.search(p, text, re.IGNORECASE | re.DOTALL)
                if match:
                    content = match.group(1).strip()
                    if len(content) > 20:
                        job.company_info = content[:1000]
                        break

            # 找行业
            industry_match = re.search(r"(?:行业|领域)[：:]\s*([^\n]{1,50})", text)
            if industry_match:
                job.company_industry = industry_match.group(1).strip()

            # 找规模
            size_match = re.search(r"(?:规模|人数)[：:]\s*([^\n]{1,50})", text)
            if size_match:
                job.company_size = size_match.group(1).strip()

        except Exception as e:
            logger.warning(f"通用提取失败: {e}")
