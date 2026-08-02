# -*- coding: utf-8 -*-
"""
猎聘爬虫 - 使用 Playwright 真实浏览器抓取
猎聘使用 CSS modules，类名被混淆，改为从 DOM 结构直接提取数据
"""
import os
import re
import time
import json
import traceback
from typing import List, Optional, Dict
from pathlib import Path
from loguru import logger
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from .base import BaseScraper, JobItem

_browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(
    Path(__file__).resolve().parent.parent.parent / "playwright-browsers"
)
if os.path.isdir(_browser_path):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browser_path


class LiepinScraper(BaseScraper):
    """猎聘爬虫"""

    def __init__(self):
        super().__init__()
        self.platform = "猎聘"
        self.base_url = "https://www.liepin.com"
        self.search_url = "https://www.liepin.com/zhaopin/"
        self.cookie_file = Path(__file__).resolve().parent / "liepin_cookies.json"

    # ---- Cookie 管理 ----
    def has_cookies(self) -> bool:
        return self.cookie_file.exists()

    def get_cookies(self) -> list:
        if not self.has_cookies():
            return []
        try:
            with open(self.cookie_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def save_cookies(self, cookies_str: str = "") -> bool:
        return False

    def verify_cookies(self) -> bool:
        """快速验证Cookie是否有效"""
        if not self.has_cookies():
            return False
        try:
            import requests
            cookies = self.get_cookies()
            session = requests.Session()
            for c in cookies:
                session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""), path=c.get("path", "/"))
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            resp = session.get("https://d.liepin.com/", timeout=10, allow_redirects=True)
            final_url = resp.url
            if "login" in final_url.lower() or "passport" in final_url.lower():
                logger.warning("[猎聘] Cookie验证失败：重定向到登录页 url={}", final_url)
                return False
            body = resp.text[:5000]
            if 'passport' in body.lower() or '扫码登录' in body or '统一登录' in body:
                logger.warning("[猎聘] Cookie验证失败：页面包含登录表单")
                return False
            logger.info("[猎聘] Cookie验证通过 final_url={}", final_url)
            return True
        except Exception as e:
            logger.warning("[猎聘] Cookie验证异常：{}", e)
            return False

    # ---- 手动登录 ----
    async def manual_login(self) -> tuple:
        """打开浏览器窗口让用户手动登录猎聘，完成后保存Cookie"""
        logger.info("[猎聘] 打开浏览器窗口，请在弹出的Chrome中手动登录...")
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=False,
                    args=["--no-sandbox", "--disable-infobars"]
                )
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                )
                page = await context.new_page()
                await page.goto("https://www.liepin.com/", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                logger.info("[猎聘] 已打开登录页面，等待用户完成登录（最多5分钟）...")
                
                logged_in = False
                await page.wait_for_timeout(3000)
                logger.info("[猎聘] 开始检测登录状态，请在弹出窗口中扫码或输入账号...")
                for i in range(300):
                    current_url = page.url
                    if "login" not in current_url.lower() and "passport" not in current_url.lower():
                        has_user = await page.evaluate("""
                            () => {
                                const bodyText = document.body.textContent || '';
                                const loginKeywords = ['退出登录', '我的简历', '我的收藏', '个人中心', '消息中心', '投递记录', '我的'];
                                if (loginKeywords.some(k => bodyText.includes(k))) {
                                    return true;
                                }
                                const userEls = document.querySelectorAll('[class*="user"], [class*="avatar"], [class*="profile"], [class*="nickname"], [class*="menu"]');
                                for (const el of userEls) {
                                    const text = el.textContent.trim();
                                    if (!text || text === '登录' || text === '注册' || text === 'Login' || text === 'Sign in' || text.includes('登录/注册')) {
                                        continue;
                                    }
                                    return true;
                                }
                                return false;
                            }
                        """)
                        if has_user:
                            logged_in = True
                            break
                    await page.wait_for_timeout(1000)
                
                if logged_in:
                    cookies = await context.cookies()
                    with open(self.cookie_file, "w", encoding="utf-8") as f:
                        json.dump(cookies, f, ensure_ascii=False, indent=2)
                    logger.info("[猎聘] 登录成功！Cookie已保存，共 {} 条。请关闭浏览器窗口...", len(cookies))
                    try:
                        while True:
                            await page.wait_for_timeout(1000)
                    except Exception:
                        pass
                    return (True, [])
                else:
                    logger.warning("[猎聘] 登录超时")
                    await context.close()
                    await browser.close()
                    return (False, [])
        except Exception as e:
            logger.error("[猎聘] manual_login异常: {}", e)
            return (False, [])

    async def search(self, keyword: str, city: str = "", page: int = 1) -> List[JobItem]:
        """搜索岗位"""
        logger.info("[猎聘] 搜索: keyword={}, city={}, page={}", keyword, city, page)
        jobs = []
        t0 = time.time()

        try:
            logger.info("[猎聘] 步骤1: 启动 Playwright 浏览器...")
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=[
                    "--disable-blink-features=AutomationControlled", "--no-sandbox",
                ])
                t1 = time.time()
                logger.info("[猎聘] 步骤1 完成: 浏览器启动耗时={:.2f}s", t1 - t0)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    locale="zh-CN", timezone_id="Asia/Shanghai",
                    viewport={"width": 1920, "height": 1080},
                    permissions=["geolocation", "notifications"],
                )
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = {
                        runtime: { onConnect: { addListener: () => {} } },
                        loadTimes: function() { return {}; },
                        csi: function() { return {}; },
                    };
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (p) => (
                        p.name === 'notifications' ? Promise.resolve({state: 'prompt'}) : originalQuery(p)
                    );
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5],
                    });
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['zh-CN', 'zh'],
                    });
                """)
                page = await context.new_page()

                url = f"{self.search_url}?key={keyword}"
                logger.info(f"猎聘访问: {url}")

                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(5000)

                page_title = await page.title()
                current_url = page.url
                if "captcha" in current_url.lower() or "verify" in current_url.lower() or "人机" in page_title:
                    logger.warning(f"猎聘触发人机验证: {page_title}")
                    for _ in range(30):
                        if "captcha" not in page.url.lower() and "verify" not in page.url.lower():
                            logger.info("猎聘验证已通过")
                            break
                        await page.wait_for_timeout(1000)

                card_selectors = [
                    '[class*="job-card-pc-container"]',
                    '[class*="job-card"]',
                    '[class*="job-list"] > div',
                    '.job-list-box > div',
                    '[data-selector^="job-card"]',
                ]
                found_selector = None
                for sel in card_selectors:
                    try:
                        await page.wait_for_selector(sel, timeout=5000)
                        found_selector = sel
                        logger.info("猎聘找到卡片容器: {}", sel)
                        break
                    except Exception:
                        continue
                if not found_selector:
                    logger.warning("猎聘未找到岗位卡片容器，尝试直接解析DOM")

                cards_data = await page.evaluate("""
                () => {
                    let cards = document.querySelectorAll('[class*="job-card-pc-container"]');
                    if (!cards.length) cards = document.querySelectorAll('[class*="job-card"]');
                    if (!cards.length) cards = document.querySelectorAll('[class*="job-list"] > div');
                    if (!cards.length) cards = document.querySelectorAll('.job-list-box > div');
                    
                    const results = [];
                    cards.forEach((card) => {
                        const links = card.querySelectorAll('a[href*="job"]');
                        const href = links.length > 0 ? links[0].href : '';
                        const text = card.textContent.trim();
                        results.push({ text, href });
                    });
                    return results;
                }
                """)

                for card in cards_data:
                    try:
                        job = JobItem(platform="猎聘")
                        text = card.get("text", "")
                        href = card.get("href", "")
                        
                        lines = text.split('\n')
                        parts = [l.strip() for l in lines if l.strip()]
                        
                        if len(parts) >= 1:
                            job.job_name = parts[0] if parts[0] else job.job_name
                        if len(parts) >= 2:
                            job.salary = parts[1] if parts[1] else job.salary
                        if len(parts) >= 3:
                            info = parts[2]
                            city_match = re.search(r'[京津沪渝]|[\u4e00-\u9fff]{2,3}市?', info)
                            if city_match:
                                job.location = city_match.group()
                            exp_match = re.search(r'(\d+-\d+年|\d+年以上|经验不限)', info)
                            if exp_match:
                                job.experience = exp_match.group()
                            edu_match = re.search(r'(本科|大专|硕士|博士|学历不限)', info)
                            if edu_match:
                                job.education = edu_match.group()
                        
                        for part in parts:
                            if '公司' in part or '有限' in part or '集团' in part:
                                job.company_name = part
                                break
                        
                        if href:
                            job.job_url = href if href.startswith("http") else f"{self.base_url}{href}"
                            jid = re.search(r'job/(\d+)', href)
                            if jid:
                                job.platform_job_id = jid.group(1)
                        
                        if job.job_name:
                            jobs.append(job)
                    except Exception as e:
                        logger.warning(f"解析猎聘卡片失败: {e}")
                        continue

                logger.info(f"猎聘解析完成: {len(jobs)} 个岗位")
                await context.close()
                await browser.close()

        except Exception as e:
            logger.error("[猎聘] 搜索异常: type={}, msg={}", type(e).__name__, str(e))
            logger.error("[猎聘] 异常堆栈:\n{}", traceback.format_exc())

        return jobs

    async def parse_job_detail(self, url: str) -> Optional[JobItem]:
        logger.warning("猎聘详情解析未实现")
        return None
