# -*- coding: utf-8 -*-
"""
前程无忧(51Job)爬虫 - 使用 Playwright 真实浏览器抓取
"""
import os
import re
import time
import json
import traceback
from typing import List, Optional, Dict
from pathlib import Path
from urllib.parse import quote
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


class Job51Scraper(BaseScraper):
    """前程无忧爬虫"""

    def __init__(self):
        super().__init__()
        self.platform = "前程无忧"
        self.base_url = "https://www.51job.com"
        self.search_url = "https://search.51job.com/list/000000,000000,0000,00,9,99,{},2,{}.html"
        self.cookie_file = Path(__file__).resolve().parent / "job51_cookies.json"
        # 前程无忧城市编码
        self.city_codes = {
            "北京": "010000", "上海": "020000", "广州": "030200", "深圳": "040000",
            "杭州": "080200", "南京": "070200", "苏州": "070300", "成都": "090200",
            "武汉": "180200", "西安": "200200", "长沙": "190200", "重庆": "060000",
            "天津": "050000", "郑州": "170200", "合肥": "150200", "宁波": "080300",
            "青岛": "120300", "厦门": "110300", "大连": "230300", "沈阳": "230200",
            "济南": "120200", "福州": "110200", "哈尔滨": "220200", "长春": "220100",
            "昆明": "250200", "贵阳": "260200", "南宁": "270200", "海口": "280200",
            "太原": "140200", "兰州": "290200", "石家庄": "130200",
        }

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
        return False  # 前程无忧通过manual_login自动保存

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
            resp = session.get("https://i.51job.com/", timeout=10, allow_redirects=True)
            final_url = resp.url
            if "login" in final_url.lower() or "passport" in final_url.lower():
                logger.warning("[51Job] Cookie验证失败：重定向到登录页 url={}", final_url)
                return False
            body = resp.text[:5000]
            if 'passport' in body.lower() or '扫码登录' in body:
                logger.warning("[51Job] Cookie验证失败：页面包含登录表单")
                return False
            logger.info("[51Job] Cookie验证通过 final_url={}", final_url)
            return True
        except Exception as e:
            logger.warning("[51Job] Cookie验证异常：{}", e)
            return False

    # ---- 手动登录 ----
    async def manual_login(self) -> tuple:
        """打开浏览器窗口让用户手动登录前程无忧，完成后保存Cookie"""
        logger.info("[51Job] 打开浏览器窗口，请在弹出的Chrome中手动登录...")
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
                await page.goto("https://www.51job.com/", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                logger.info("[51Job] 已打开登录页面，等待用户完成登录（最多5分钟）...")

                logged_in = False
                # 等待页面完全加载后再开始检测（避免首帧即误判）
                await page.wait_for_timeout(3000)
                logger.info("[51Job] 开始检测登录状态，请在弹出窗口中扫码或输入账号...")
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
                        if has_user:
                            logged_in = True
                            break
                    await page.wait_for_timeout(1000)

                if logged_in:
                    cookies = await context.cookies()
                    with open(self.cookie_file, "w", encoding="utf-8") as f:
                        json.dump(cookies, f, ensure_ascii=False, indent=2)
                    logger.info("[51Job] 登录成功！Cookie已保存，共 {} 条。请关闭浏览器窗口...", len(cookies))
                    # 等待用户手动关闭浏览器窗口
                    try:
                        while True:
                            await page.wait_for_timeout(1000)
                    except Exception:
                        pass
                    return (True, [])
                else:
                    logger.warning("[51Job] 登录超时")
                    await context.close()
                    await browser.close()
                    return (False, [])
        except Exception as e:
            logger.error("[51Job] manual_login异常: {}", e)
            return (False, [])

    async def search(self, keyword: str, city: str = "", page: int = 1) -> List[JobItem]:
        """搜索岗位"""
        logger.info("[51Job] 搜索: keyword={}, city={}, page={}", keyword, city, page)
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
                page = await context.new_page()

                url = self.search_url.format(quote(keyword), page)
                if city:
                    city_code = self.city_codes.get(city, "")
                    if city_code:
                        url = url.replace("000000,000000,0000", f"{city_code},000000,0000", 1)
                logger.info(f"前程无忧访问: {url}")

                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(5000)

                # 等待岗位列表
                try:
                    await page.wait_for_selector(".j_joblist", timeout=10000)
                except Exception:
                    logger.warning("前程无忧未找到岗位列表元素")

                html = await page.content()
                soup = BeautifulSoup(html, 'html.parser')
                cards = soup.select(".joblist_item")

                for card in cards:
                    try:
                        job = JobItem(platform="前程无忧")

                        # 岗位名称
                        name_el = card.select_one(".jname, a[href*='/job/']")
                        if name_el:
                            job.job_name = name_el.get_text(strip=True)

                        # 公司名称
                        company_el = card.select_one(".cname")
                        if company_el:
                            job.company_name = company_el.get_text(strip=True)

                        # 薪资
                        salary_el = card.select_one(".sal")
                        if salary_el:
                            job.salary = salary_el.get_text(strip=True)

                        # 地点
                        location_el = card.select_one(".d_at")
                        if location_el:
                            job.location = location_el.get_text(strip=True)

                        # 详情链接
                        link_el = card.select_one("a[href*='/job/']")
                        if link_el and link_el.get("href"):
                            href = link_el["href"]
                            job.job_url = href if href.startswith("http") else f"{self.base_url}{href}"
                            # 提取岗位ID
                            match = re.search(r'/job/(\d+)', job.job_url)
                            if match:
                                job.platform_job_id = match.group(1)

                        if job.job_name:
                            jobs.append(job)
                    except Exception as e:
                        logger.warning(f"解析前程无忧卡片失败: {e}")
                        continue

                logger.info(f"前程无忧解析完成: {len(jobs)} 个岗位")
                await context.close()
                await browser.close()

        except Exception as e:
            logger.error("[51Job] 搜索异常: type={}, msg={}", type(e).__name__, str(e))
            logger.error("[51Job] 异常堆栈:\n{}", traceback.format_exc())

        return jobs

    async def parse_job_detail(self, url: str) -> Optional[JobItem]:
        logger.warning("前程无忧详情解析未实现")
        return None

    async def send_greeting(self, job_url: str, greeting_message: str) -> Dict:
        """向前程无忧岗位发送打招呼消息"""
        logger.info("[51Job][投递] === 开始投递 ===")
        if not job_url:
            return {"success": False, "message": "岗位URL为空"}
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
                )
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )

                if self.has_cookies():
                    await context.add_cookies(self.get_cookies())

                page = await context.new_page()
                await page.goto(job_url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000)

                # 查找申请/沟通按钮
                apply_selectors = [
                    'text=立即申请', 'text=申请职位', 'text=投递简历',
                    'a:has-text("申请")', 'button:has-text("申请")',
                    '[class*="apply"]', '[class*="btn_apply"]',
                ]
                apply_btn = None
                for sel in apply_selectors:
                    try:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            apply_btn = el
                            logger.info("[51Job][投递] 找到按钮: {}", sel)
                            break
                    except Exception:
                        continue

                if not apply_btn:
                    await context.close()
                    await browser.close()
                    return {"success": False, "message": "未找到申请/投递按钮"}

                await apply_btn.click()
                await page.wait_for_timeout(3000)

                msg_input = page.locator('textarea, [contenteditable="true"]')
                if await msg_input.count() > 0:
                    await msg_input.first.fill(greeting_message)
                    await page.wait_for_timeout(500)
                    send_btn = page.locator('button:has-text("发送"), button:has-text("提交"), [class*="send"]')
                    if await send_btn.count() > 0:
                        await send_btn.first.click()
                        await page.wait_for_timeout(2000)
                        await context.close()
                        await browser.close()
                        return {"success": True, "message": "已申请"}

                await context.close()
                await browser.close()
                return {"success": False, "message": "申请流程不完整"}
        except Exception as e:
            logger.error("[51Job][投递] 异常: {}", e)
            return {"success": False, "message": str(e)}
