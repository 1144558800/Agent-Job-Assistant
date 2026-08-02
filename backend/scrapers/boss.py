# -*- coding: utf-8 -*-
"""
BOSS直聘爬虫 - 使用 Playwright + 真实浏览器环境
支持 Cookie 登录态恢复和城市编码筛选
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
from playwright.async_api import async_playwright, Page

from .base import BaseScraper, JobItem

# 设置 Playwright 浏览器路径（确保能找到项目内安装的 Chromium）
_browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(
    Path(__file__).resolve().parent.parent.parent / "playwright-browsers"
)
if os.path.isdir(_browser_path):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browser_path


class BossScraper(BaseScraper):
    """BOSS直聘爬虫"""

    def __init__(self):
        super().__init__()
        self.platform = "BOSS直聘"
        self.base_url = "https://www.zhipin.com"
        self.search_url = "https://www.zhipin.com/web/geek/job"
        self.cookie_file = Path(__file__).resolve().parent / "boss_cookies.json"

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

    def save_cookies(self, cookies_json: str = "") -> bool:
        """从 JSON 字符串保存 Cookie（接口兼容）"""
        if not cookies_json:
            return False
        try:
            cookies = json.loads(cookies_json) if isinstance(cookies_json, str) else cookies_json
            with open(self.cookie_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            logger.info("[BOSS] Cookie 已保存，共 {} 条", len(cookies) if isinstance(cookies, list) else 1)
            return True
        except Exception as e:
            logger.error("[BOSS] 保存 Cookie 失败: {}", e)
            return False

    def verify_cookies(self) -> bool:
        """
        快速验证Cookie是否有效（使用requests.Session，完整模拟浏览器Cookie行为）
        """
        if not self.has_cookies():
            return False
        try:
            import requests
            cookies = self.get_cookies()
            session = requests.Session()
            # 设置所有Cookie到Session的cookie jar
            for c in cookies:
                session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""), path=c.get("path", "/"))
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            # 请求BOSS直聘首页，不自动跟随重定向（手动检查）
            resp = session.get("https://www.zhipin.com/", timeout=10, allow_redirects=True)
            final_url = resp.url
            if "login" in final_url.lower() or "unuthorized" in final_url.lower():
                logger.warning("[BOSS] Cookie验证失败：重定向到登录页 url={}", final_url)
                return False
            body = resp.text[:5000]
            if '未登录' in body or '请先登录' in body or 'passport' in body.lower():
                logger.warning("[BOSS] Cookie验证失败：页面包含登录提示")
                return False
            logger.info("[BOSS] Cookie验证通过 final_url={}", final_url)
            return True
        except Exception as e:
            logger.warning("[BOSS] Cookie验证异常：{}", e)
            return False

    # ---- 手动登录 ----
    async def manual_login(self) -> tuple:
        """打开浏览器窗口让用户手动登录BOSS直聘，完成后保存Cookie"""
        logger.info("[BOSS] 打开浏览器窗口，请在弹出的Chrome中手动登录...")
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
                await page.goto("https://www.zhipin.com/web/user/?ka=header-login", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                logger.info("[BOSS] 已打开登录页面，等待用户完成登录（最多5分钟）...")

                # BOSS直聘通常首页就是登录页，先点一下"登录/注册"
                try:
                    login_btn = page.locator('text=登录/注册')
                    if await login_btn.count() > 0:
                        await login_btn.first.click()
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass

                # 等待登录完成（检测 URL 变化）
                logged_in = False
                # 等待页面完全加载后再开始检测（避免首帧即误判）
                await page.wait_for_timeout(3000)
                logger.info("[BOSS] 开始检测登录状态，请在弹出窗口中扫码或输入账号...")
                for i in range(300):
                    current_url = page.url
                    if "login" not in current_url.lower() and "passport" not in current_url.lower():
                        has_user = await page.evaluate("""
                            () => {
                                const bodyText = document.body.textContent || '';
                                const loginKeywords = ['我的', '已登录', '退出', '消息', '简历', '收藏', '投递'];
                                if (loginKeywords.some(k => bodyText.includes(k))) {
                                    return true;
                                }
                                const userEls = document.querySelectorAll('[class*="user"], [class*="avatar"], [class*="header-user"], [class*="nickname"]');
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
                    logger.info("[BOSS] 登录成功！Cookie已保存，共 {} 条。请关闭浏览器窗口...", len(cookies))
                    # 等待用户手动关闭浏览器窗口
                    try:
                        while True:
                            await page.wait_for_timeout(1000)
                    except Exception:
                        pass
                    return (True, [])
                else:
                    logger.warning("[BOSS] 登录超时")
                    await context.close()
                    await browser.close()
                    return (False, [])
        except Exception as e:
            logger.error("[BOSS] manual_login异常: {}", e)
            return (False, [])

    async def search(self, keyword: str, city: str = "", page: int = 1) -> List[JobItem]:
        """搜索岗位"""
        logger.info("[BOSS] 搜索: keyword={}, city={}, page={}", keyword, city, page)
        jobs = []
        t0 = time.time()

        try:
            logger.info("[BOSS] 步骤1: 启动 Playwright 浏览器...")
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
                )
                t1 = time.time()
                logger.info("[BOSS] 步骤1 完成: 浏览器启动耗时={:.2f}s", t1 - t0)
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
                # 加载隐身脚本
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
                """)
                page = await context.new_page()

                # 加载Cookie
                t2 = time.time()
                if self.has_cookies():
                    cookies = self.get_cookies()
                    await context.add_cookies(cookies)
                    logger.info("[BOSS] 步骤2 完成: Cookie已加载({})，耗时={:.2f}s", len(cookies), time.time() - t2)
                else:
                    logger.warning("[BOSS] 无Cookie文件，搜索结果可能受限")

                # 构建搜索URL
                query_params = [f"query={quote(keyword)}"]
                if city:
                    code = config_city_codes.get(city, "")
                    if code:
                        query_params.append(f"city={code}")
                    else:
                        logger.warning("[BOSS] 未找到城市编码: {}", city)
                query_params.append(f"page={page}")
                url = f"{self.search_url}?{'&'.join(query_params)}"
                logger.info(f"[BOSS] 搜索URL: {url}")

                # 访问搜索页
                t3 = time.time()
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(5000)
                logger.info("[BOSS] 步骤3 完成: 页面加载，耗时={:.2f}s", time.time() - t3)

                # 等待岗位列表加载
                t4 = time.time()
                try:
                    await page.wait_for_selector(".job-list-box", timeout=10000)
                except Exception:
                    # 可能被拦截，尝试等待更久
                    logger.warning("[BOSS] 未找到.job-list-box，尝试等待更久...")
                    await page.wait_for_timeout(5000)
                logger.info("[BOSS] 步骤4 完成: 等待岗位列表，耗时={:.2f}s", time.time() - t4)

                # 解析结果
                t5 = time.time()
                html = await page.content()
                soup = BeautifulSoup(html, 'html.parser')
                cards = soup.select(".job-card-box")

                for card in cards:
                    try:
                        job = JobItem(platform="BOSS直聘")

                        # 岗位名称
                        name_el = card.select_one(".job-name")
                        if name_el:
                            job.job_name = name_el.get_text(strip=True)

                        # 公司名称
                        company_el = card.select_one(".company-name")
                        if company_el:
                            job.company_name = company_el.get_text(strip=True)

                        # 薪资
                        salary_el = card.select_one(".salary")
                        if salary_el:
                            job.salary = salary_el.get_text(strip=True)

                        # 地点
                        area_el = card.select_one(".job-area")
                        if area_el:
                            job.location = area_el.get_text(strip=True)

                        # 详情链接
                        link_el = card.select_one("a[href*='job_detail']")
                        if link_el and link_el.get("href"):
                            href = link_el["href"]
                            job.job_url = href if href.startswith("http") else f"{self.base_url}{href}"
                            job_id_match = re.search(r'job_detail/([a-zA-Z0-9_-]+)', href)
                            if job_id_match:
                                job.platform_job_id = job_id_match.group(1)

                        # 标签（学历、经验等）
                        tag_items = card.select(".tag-item")
                        for tag in tag_items:
                            text = tag.get_text(strip=True)
                            if "年" in text:
                                job.experience = text
                            elif any(k in text for k in ["本科", "大专", "硕士", "学历"]):
                                job.education = text

                        if job.job_name:
                            jobs.append(job)
                    except Exception as e:
                        logger.warning(f"[BOSS] 解析卡片失败: {e}")
                        continue

                t6 = time.time()
                logger.info("[BOSS] 解析完成: {} 个岗位, 耗时={:.2f}s", len(jobs), t6 - t5)

                await context.close()
                await browser.close()
                t_total = time.time() - t0
                logger.info("[BOSS] 搜索总耗时={:.2f}s", t_total)

        except Exception as e:
            logger.error("[BOSS] 搜索异常: type={}, msg={}", type(e).__name__, str(e))
            logger.error("[BOSS] 异常堆栈:\n{}", traceback.format_exc())

        return jobs

    async def parse_job_detail(self, url: str) -> Optional[JobItem]:
        """解析岗位详情"""
        logger.info("[BOSS] 获取详情: {}", url)
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                """)
                page = await context.new_page()

                if self.has_cookies():
                    await context.add_cookies(self.get_cookies())

                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000)

                html = await page.content()
                soup = BeautifulSoup(html, 'html.parser')

                job = JobItem(platform="BOSS直聘", job_url=url)

                # 岗位职责
                desc_el = soup.select_one(".job-sec-text, .job-detail-section-text")
                if desc_el:
                    job.responsibilities = desc_el.get_text(strip=True)[:2000]

                # 公司信息
                company_info_el = soup.select_one(".company-info, .business-info")
                if company_info_el:
                    job.company_info = company_info_el.get_text(strip=True)[:1000]

                await context.close()
                await browser.close()
                return job
        except Exception as e:
            logger.error("[BOSS] 详情解析失败: {}", e)
            return None

    async def send_greeting(self, job_url: str, greeting_message: str) -> Dict:
        """向BOSS直聘岗位发送打招呼消息"""
        logger.info("[BOSS][投递] === 开始投递 ===")
        logger.info("[BOSS][投递] url={}, message_len={}", job_url[:80], len(greeting_message))
        logger.debug("[BOSS][投递] 消息内容: {}", greeting_message[:100])

        if not job_url:
            logger.error("[BOSS][投递] 岗位URL为空，终止")
            return {"success": False, "message": "岗位URL为空"}

        try:
            # 步骤1: 打开浏览器并加载Cookie
            logger.info("[BOSS][投递] 步骤1/5: 启动 Playwright 浏览器并加载Cookie...")
            t1 = time.time()
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
                )
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = { runtime: {} };
                """)
                page = await context.new_page()

                # 加载Cookie
                if self.has_cookies():
                    cookies = self.get_cookies()
                    await context.add_cookies(cookies)
                    logger.info("[BOSS][投递] Cookie已加载({})，耗时={:.2f}s", len(cookies), time.time() - t1)
                else:
                    logger.warning("[BOSS][投递] 无Cookie文件")

                # 步骤2: 访问岗位详情页
                logger.info("[BOSS][投递] 步骤2/5: 访问岗位详情页...")
                t2 = time.time()
                await page.goto(job_url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000)
                logger.info("[BOSS][投递] 步骤2 完成，耗时={:.2f}s", time.time() - t2)

                # 步骤3: 查找"立即沟通"按钮
                logger.info("[BOSS][投递] 步骤3/5: 查找沟通按钮...")
                t3 = time.time()
                chat_btn = None
                chat_selectors = [
                    'text=立即沟通',
                    'text=立即沟通按钮',
                    '.btn-startchat',
                    '[class*="chat"]',
                    '[class*="op-btn"]',
                    'button:has-text("沟通")',
                ]
                for sel in chat_selectors:
                    try:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            chat_btn = el
                            logger.info("[BOSS][投递] 找到沟通按钮: {}", sel)
                            break
                    except Exception:
                        continue

                if not chat_btn:
                    logger.warning("[BOSS][投递] 未找到沟通按钮，尝试截图分析...")
                    await page.screenshot(path=str(SCREENSHOT_DIR / f"boss_apply_{int(time.time())}.png"), full_page=False)
                    await context.close()
                    await browser.close()
                    return {"success": False, "message": "未找到沟通按钮（页面可能已变更或需更新Cookie）"}

                logger.info("[BOSS][投递] 步骤3 完成，耗时={:.2f}s", time.time() - t3)

                # 步骤4: 点击沟通按钮
                logger.info("[BOSS][投递] 步骤4/5: 点击沟通按钮...")
                t4 = time.time()
                await chat_btn.click()
                await page.wait_for_timeout(2000)
                logger.info("[BOSS][投递] 步骤4 完成，耗时={:.2f}s", time.time() - t4)

                # 步骤5: 输入招呼语并发送
                logger.info("[BOSS][投递] 步骤5/5: 输入招呼语并发送...")
                t5 = time.time()
                msg_input = page.locator('textarea, [contenteditable="true"], .input-area textarea, [class*="input"] textarea')
                if await msg_input.count() > 0:
                    await msg_input.first.fill(greeting_message)
                    await page.wait_for_timeout(500)

                    send_btn = page.locator('button:has-text("发送"), .send-btn, [class*="send"]')
                    if await send_btn.count() > 0:
                        await send_btn.first.click()
                        await page.wait_for_timeout(2000)
                        logger.info("[BOSS][投递] 步骤5 完成，消息已发送，耗时={:.2f}s", time.time() - t5)
                        await context.close()
                        await browser.close()
                        return {"success": True, "message": "消息已发送"}
                    else:
                        logger.warning("[BOSS][投递] 找到输入框但未找到发送按钮")
                        await context.close()
                        await browser.close()
                        return {"success": False, "message": "找到输入框但未找到发送按钮"}
                else:
                    logger.warning("[BOSS][投递] 未找到消息输入框")
                    await context.close()
                    await browser.close()
                    return {"success": False, "message": "未找到消息输入框"}

        except Exception as e:
            logger.error("[BOSS][投递] 异常: {}", e)
            logger.error("[BOSS][投递] 堆栈:\n{}", traceback.format_exc())
            return {"success": False, "message": str(e)}


# ---- 城市编码映射 ----
config_city_codes = {
    "北京": "101010100", "上海": "101020100", "广州": "101280100", "深圳": "101280600",
    "杭州": "101210100", "南京": "101190100", "苏州": "101190400", "成都": "101270100",
    "武汉": "101200100", "西安": "101110100", "长沙": "101250100", "重庆": "101040100",
    "天津": "101030100", "郑州": "101180100", "合肥": "101220100", "宁波": "101210400",
    "青岛": "101120200", "厦门": "101230200", "大连": "101070200", "沈阳": "101070100",
    "济南": "101120100", "福州": "101230100", "哈尔滨": "101050100", "长春": "101060100",
    "珠海": "101280700", "佛山": "101280800", "东莞": "101281600", "无锡": "101190200",
    "常州": "101191100", "昆明": "101290100", "贵阳": "101260100", "南宁": "101300100",
    "海口": "101310100", "太原": "101100100", "兰州": "101160100", "石家庄": "101090100",
}
