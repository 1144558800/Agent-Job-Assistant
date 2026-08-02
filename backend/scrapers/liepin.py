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

# 设置 Playwright 浏览器路径（确保能找到项目内安装的 Chromium）
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
        return False  # 猎聘通过manual_login自动保存

    def verify_cookies(self) -> bool:
        """快速验证Cookie是否有效（使用requests.Session，完整模拟浏览器Cookie行为）"""
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
            # 请求个人中心页，不自动跟随重定向（手动检查）
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
                
                # 等待登录完成
                logged_in = False
                # 等待页面完全加载后再开始检测（避免首帧即误判）
                await page.wait_for_timeout(3000)
                logger.info("[猎聘] 开始检测登录状态，请在弹出窗口中扫码或输入账号...")
                for i in range(300):
                    current_url = page.url
                    if "login" not in current_url.lower() and "passport" not in current_url.lower():
                        # 检查页面是否有用户信息元素
                        has_user = await page.evaluate("""
                            () => {
                                // 方式1: 检查页面是否有已登录专属文字
                                const bodyText = document.body.textContent || '';
                                const loginKeywords = ['退出登录', '我的简历', '我的收藏', '个人中心', '消息中心', '投递记录', '我的'];
                                if (loginKeywords.some(k => bodyText.includes(k))) {
                                    return true;
                                }
                                // 方式2: 检查DOM元素，排除"登录/注册"按钮
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
                    # 等待用户手动关闭浏览器窗口
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
                    // 覆盖 webdriver 检测
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    // 覆盖 chrome 属性
                    window.chrome = {
                        runtime: { onConnect: { addListener: () => {} } },
                        loadTimes: function() { return {}; },
                        csi: function() { return {}; },
                    };
                    // 覆盖权限查询
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (p) => (
                        p.name === 'notifications' ? Promise.resolve({state: 'prompt'}) : originalQuery(p)
                    );
                    // 覆盖 plugins
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5],
                    });
                    // 覆盖 languages
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['zh-CN', 'zh'],
                    });
                """)
                page = await context.new_page()

                url = f"{self.search_url}?key={keyword}"
                logger.info(f"猎聘访问: {url}")

                # 使用 domcontentloaded 替代 networkidle，避免被页面持续请求阻塞
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(5000)

                # 检查页面是否被拦截（是否包含人机验证）
                page_title = await page.title()
                current_url = page.url
                if "captcha" in current_url.lower() or "verify" in current_url.lower() or "人机" in page_title:
                    logger.warning(f"猎聘触发人机验证: {page_title}")
                    # 尝试等待验证完成（最多 30 秒）
                    for _ in range(30):
                        if "captcha" not in page.url.lower() and "verify" not in page.url.lower():
                            logger.info("猎聘验证已通过")
                            break
                        await page.wait_for_timeout(1000)

                # 等待岗位卡片加载 - 尝试多个可能的选择器
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

                # 使用 DOM 结构直接提取各字段数据
                cards_data = await page.evaluate("""
                () => {
                    // 尝试多种选择器查找岗位卡片
                    let cards = document.querySelectorAll('[class*="job-card-pc-container"]');
                    if (!cards.length) cards = document.querySelectorAll('[class*="job-card"]');
                    if (!cards.length) cards = document.querySelectorAll('[class*="job-list"] > div');
                    if (!cards.length) cards = document.querySelectorAll('.job-list-box > div');

                    const results = [];
                    cards.forEach(card => {
                        // 通过文本特征提取各字段
                        const allText = card.textContent.trim();
                        if (!allText || allText.length < 5) return;

                        // 提取所有链接
                        const links = Array.from(card.querySelectorAll('a[href]')).map(a => a.href);
                        const jobLink = links.find(h => h.includes('/job/') || h.includes('/a/')) || links[0] || '';

                        // 尝试从特定元素中提取文本
                        const getText = (selector) => {
                            const el = card.querySelector(selector);
                            return el ? el.textContent.trim() : '';
                        };

                        results.push({
                            html: card.outerHTML.substring(0, 2000),
                            text: allText.substring(0, 500),
                            link: jobLink,
                            // 尝试多种可能的选择器
                            title: getText('[class*="job-title"]') || getText('[class*="job-name"]') || getText('[class*="title"]'),
                            salary: getText('[class*="salary"]') || getText('[class*="pay"]'),
                            company: getText('[class*="company"]') || getText('[class*="corp"]'),
                            location: getText('[class*="area"]') || getText('[class*="location"]'),
                        });
                    });
                    return results;
                }
                """)

                # 使用 AI 辅助解析混淆后的 DOM 数据
                if cards_data:
                    try:
                        jobs = self._ai_parse_cards(cards_data, keyword, city)
                        if not jobs:
                            logger.warning("[猎聘] AI解析为空，使用回退解析")
                            jobs = self._fallback_parse(cards_data)
                    except Exception as e:
                        logger.warning(f"[猎聘] AI解析失败({e})，使用回退解析")
                        jobs = self._fallback_parse(cards_data)

                logger.info(f"猎聘解析完成: {len(jobs)} 个岗位")
                await context.close()
                await browser.close()

        except Exception as e:
            logger.error("[猎聘] 搜索异常: type={}, msg={}", type(e).__name__, str(e))
            logger.error("[猎聘] 异常堆栈:\n{}", traceback.format_exc())

        return jobs

    def _ai_parse_cards(self, cards_data: list, keyword: str, city: str) -> List[JobItem]:
        """使用 AI 从混淆的 DOM 数据中提取岗位信息"""
        try:
            from openai import OpenAI
            import config as cfg
            client = OpenAI(api_key=cfg.AI_API_KEY, base_url=cfg.AI_API_BASE)

            # 截取前15个卡片
            sample = cards_data[:15]
            prompt = f"""你是一个招聘数据提取助手。下面是从猎聘网页中提取的岗位卡片原始数据（CSS类名已被混淆）。

请从每个卡片的 text 字段中提取以下信息，以 JSON 数组返回：
- job_name: 岗位名称
- company_name: 公司名称
- salary: 薪资（如"15-25K"）
- location: 工作地点

规则：
1. 只返回一个 JSON 数组
2. 如果某字段无法确定，填空字符串
3. 不要编造数据

原始数据：
{json.dumps([{"i": i, "text": c.get("text", ""), "link": c.get("link", "")[:80]} for i, c in enumerate(sample)], ensure_ascii=False)}"""

            response = client.chat.completions.create(
                model=cfg.AI_MODEL,
                messages=[
                    {"role": "system", "content": "你是数据提取助手，只输出 JSON，不输出任何其他内容。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=2000,
            )

            ai_text = response.choices[0].message.content.strip()
            if ai_text.startswith("```"):
                ai_text = ai_text.split("\n", 1)[1] if "\n" in ai_text else ai_text
                if "```" in ai_text:
                    ai_text = ai_text.rsplit("```", 1)[0]

            parsed = json.loads(ai_text)
            jobs = []
            for item in parsed:
                if not item.get("job_name"):
                    continue
                idx = item.get("i", 0)
                job = JobItem(
                    platform="猎聘",
                    job_name=item.get("job_name", ""),
                    company_name=item.get("company_name", ""),
                    salary=item.get("salary", ""),
                    location=item.get("location", ""),
                    job_url=cards_data[idx].get("link", "") if idx < len(cards_data) else "",
                )
                if city and job.location and city not in job.location:
                    job.location = f"{city}-{job.location}"
                jobs.append(job)

            logger.info("[猎聘] AI解析出 {} 个有效岗位", len(jobs))
            return jobs
        except Exception as e:
            logger.warning("[猎聘] AI解析失败: {}", e)
            return []

    def _fallback_parse(self, cards_data: list) -> List[JobItem]:
        """回退解析：基于文本模式的简单提取"""
        jobs = []
        for card in cards_data:
            text = card.get("text", "")
            if not text or len(text) < 5:
                continue

            job = JobItem(platform="猎聘", job_url=card.get("link", ""))

            # 使用正则提取薪资（如 15K-25K, 15000-25000）
            salary_match = re.search(r'(\d+[kK千]?\s*[-~至]\s*\d+[kK千]?)', text)
            if salary_match:
                job.salary = salary_match.group(1)

            # 大部分猎聘文本格式是: 岗位名 公司名 薪资 地点
            # 尝试按常见模式分割
            parts = text.split()
            if len(parts) >= 3:
                job.job_name = parts[0]
                job.company_name = parts[1]
                if len(parts) >= 4:
                    job.location = parts[-1]

            if job.job_name and len(job.job_name) < 50:
                jobs.append(job)

        return jobs

    async def parse_job_detail(self, url: str) -> Optional[JobItem]:
        """解析岗位详情"""
        logger.warning("猎聘详情解析未实现")
        return None

    async def send_greeting(self, job_url: str, greeting_message: str) -> Dict:
        """向猎聘岗位发送打招呼消息"""
        logger.info("[猎聘][投递] === 开始投递 ===")
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

                # 查找沟通/投递按钮
                chat_selectors = [
                    'text=立即沟通', 'text=立即投递', 'text=申请职位',
                    '[class*="apply"]', '[class*="chat"]',
                    'button:has-text("沟通")', 'button:has-text("投递")',
                ]
                chat_btn = None
                for sel in chat_selectors:
                    try:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            chat_btn = el
                            logger.info("[猎聘][投递] 找到按钮: {}", sel)
                            break
                    except Exception:
                        continue

                if not chat_btn:
                    await context.close()
                    await browser.close()
                    return {"success": False, "message": "未找到沟通/投递按钮"}

                await chat_btn.click()
                await page.wait_for_timeout(2000)

                msg_input = page.locator('textarea, [contenteditable="true"]')
                if await msg_input.count() > 0:
                    await msg_input.first.fill(greeting_message)
                    await page.wait_for_timeout(500)
                    send_btn = page.locator('button:has-text("发送"), [class*="send"]')
                    if await send_btn.count() > 0:
                        await send_btn.first.click()
                        await page.wait_for_timeout(2000)
                        await context.close()
                        await browser.close()
                        return {"success": True, "message": "消息已发送"}

                await context.close()
                await browser.close()
                return {"success": False, "message": "发送失败"}
        except Exception as e:
            logger.error("[猎聘][投递] 异常: {}", e)
            return {"success": False, "message": str(e)}
