# -*- coding: utf-8 -*-
"""
智联招聘爬虫 - 使用 Playwright 真实浏览器抓取
"""
import os
import re
import time
import json
import traceback
from typing import List, Optional, Dict
from urllib.parse import quote
from pathlib import Path
from loguru import logger
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from .base import BaseScraper, JobItem

# 设置 Playwright 浏览器路径（确保能找到项目内安装的 Chromium）
_browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(
    Path(__file__).resolve().parent.parent.parent / "playwright-browsers"
)
if os.path.isdir(_browser_path):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browser_path


class ZhaopinScraper(BaseScraper):
    """智联招聘爬虫"""

    def __init__(self):
        super().__init__()
        self.platform = "智联招聘"
        self.base_url = "https://www.zhaopin.com"
        self.search_url = "https://sou.zhaopin.com/"
        # 智联招聘城市编码
        self.city_codes = {
            "北京": "530", "上海": "538", "广州": "763", "深圳": "765",
            "杭州": "653", "南京": "635", "苏州": "577", "成都": "801",
            "武汉": "736", "西安": "854", "长沙": "749", "重庆": "551",
            "天津": "531", "郑州": "559", "合肥": "591", "宁波": "573",
            "青岛": "570", "厦门": "586", "大连": "575", "沈阳": "563",
            "济南": "569", "福州": "591", "哈尔滨": "560", "长春": "561",
            "珠海": "776", "佛山": "769", "东莞": "773", "无锡": "571",
            "常州": "578", "昆明": "791", "贵阳": "792", "南宁": "785",
            "海口": "797", "太原": "548", "兰州": "831", "石家庄": "546",
        }
        self.cookie_file = Path(__file__).resolve().parent / "zhaopin_cookies.json"

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
        """快速验证Cookie是否有效（使用requests.Session，完整模拟浏览器Cookie行为）"""
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
            resp = session.get("https://i.zhaopin.com/", timeout=10, allow_redirects=True)
            final_url = resp.url
            if "login" in final_url.lower() or "passport" in final_url.lower():
                logger.warning("[智联] Cookie验证失败：重定向到登录页 url={}", final_url)
                return False
            body = resp.text[:5000]
            if 'passport' in body.lower() or '扫码登录' in body or '统一登录' in body or '登录智联' in body:
                logger.warning("[智联] Cookie验证失败：页面包含登录表单")
                return False
            logger.info("[智联] Cookie验证通过 final_url={}", final_url)
            return True
        except Exception as e:
            logger.warning("[智联] Cookie验证异常：{}", e)
            return False

    # ---- 手动登录 ----
    async def manual_login(self) -> tuple:
        """打开浏览器窗口让用户手动登录智联招聘，完成后保存Cookie"""
        logger.info("[智联] 打开浏览器窗口，请在弹出的Chrome中手动登录...")
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
                await page.goto("https://www.zhaopin.com/", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                logger.info("[智联] 已打开登录页面，等待用户完成登录（最多5分钟）...")

                logged_in = False
                # 等待页面完全加载后再开始检测（避免首帧即误判）
                await page.wait_for_timeout(3000)
                logger.info("[智联] 开始检测登录状态，请在弹出窗口中扫码或输入账号...")
                for i in range(300):
                    current_url = page.url
                    if "login" not in current_url.lower() and "passport" not in current_url.lower():
                        has_user = await page.evaluate("""
                            () => {
                                // 方式1: 检查页面是否有已登录专属文字
                                const bodyText = document.body.textContent || '';
                                const loginKeywords = ['退出登录', '我的简历', '我的收藏', '个人中心', '消息', '投递记录', '我的'];
                                if (loginKeywords.some(k => bodyText.includes(k))) {
                                    return true;
                                }
                                // 方式2: 检查DOM元素，排除"登录/注册"按钮
                                const userEls = document.querySelectorAll('[class*="user"], [class*="avatar"], [class*="header-user"], [class*="nickname"], [class*="personal"]');
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
                        if has_user or "i.zhaopin.com" in current_url:
                            logged_in = True
                            break
                    await page.wait_for_timeout(1000)

                if logged_in:
                    cookies = await context.cookies()
                    with open(self.cookie_file, "w", encoding="utf-8") as f:
                        json.dump(cookies, f, ensure_ascii=False, indent=2)
                    logger.info("[智联] 登录成功！Cookie已保存，共 {} 条。请关闭浏览器窗口...", len(cookies))
                    # 等待用户手动关闭浏览器窗口
                    try:
                        while True:
                            await page.wait_for_timeout(1000)
                    except Exception:
                        pass
                    return (True, [])
                else:
                    logger.warning("[智联] 登录超时")
                    await context.close()
                    await browser.close()
                    return (False, [])
        except Exception as e:
            logger.error("[智联] manual_login异常: {}", e)
            return (False, [])

    async def search(self, keyword: str, city: str = "", page: int = 1) -> List[JobItem]:
        logger.info("[智联] 搜索: keyword={}, city={}, page={}", keyword, city, page)
        jobs = []

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=[
                    "--disable-blink-features=AutomationControlled", "--no-sandbox",
                ])
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    locale="zh-CN", timezone_id="Asia/Shanghai",
                    viewport={"width": 1920, "height": 1080},
                )
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                """)
                await context.set_extra_http_headers({
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Referer": "https://www.zhaopin.com/",
                })
                page = await context.new_page()

                url = f"{self.search_url}?kw={quote(keyword)}"
                if city:
                    city_code = self.city_codes.get(city, "")
                    if city_code:
                        url += f"&jl={city_code}"
                    else:
                        url += f"&city={city}"
                logger.info(f"智联招聘访问: {url}")

                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(5000)

                # 等待岗位列表
                try:
                    await page.wait_for_selector(".joblist-box__item", timeout=10000)
                except Exception:
                    logger.warning("智联招聘未找到岗位列表元素")

                html = await page.content()
                soup = BeautifulSoup(html, 'html.parser')
                cards = soup.select(".joblist-box__item")

                for card in cards:
                    try:
                        job = JobItem(platform=self.platform)

                        # 岗位名称
                        name_el = card.select_one(".jobinfo__name")
                        if name_el:
                            job.job_name = name_el.get_text(strip=True)

                        # 薪资
                        salary_el = card.select_one(".jobinfo__salary")
                        if salary_el:
                            job.salary = salary_el.get_text(strip=True)

                        # 公司名称
                        company_el = card.select_one(".companyinfo__name")
                        if company_el:
                            job.company_name = company_el.get_text(strip=True)

                        # 地点 - 在 other-info 的标签中
                        info_items = card.select(".jobinfo__other-info-item")
                        if len(info_items) >= 3:
                            job.location = info_items[2].get_text(strip=True)
                        elif info_items:
                            job.location = info_items[0].get_text(strip=True)

                        # 详情链接
                        link_el = card.select_one("a[href*=\"zhaopin\"]") or card