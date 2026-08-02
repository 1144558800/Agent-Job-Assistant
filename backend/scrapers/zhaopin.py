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
                        link_el = card.select_one("a[href*=\"zhaopin\"]") or card.select_one("a[href*=\"job\"]")
                        if link_el and link_el.get("href"):
                            href = link_el["href"]
                            job.job_url = href if href.startswith("http") else f"https:{href}"
                            # 从URL中提取岗位ID
                            job_id = ""
                            if job.job_url:
                                m = re.search(r'jobs\.zhaopin\.com/([A-Z0-9]+)', job.job_url, re.I) or re.search(r'/job_detail/(\d+)', job.job_url)
                                if m:
                                    job_id = m.group(1)
                            job.platform_job_id = job_id

                        # 确保location字段包含搜索城市名（智联招聘location可能只有区名或错误字段）
                        location_raw = job.location
                        if city and location_raw and city not in location_raw:
                            # 检查是否是有效的城市/区名（不是经验年限等）
                            if not any(kw in location_raw for kw in ['经验', '学历', '大专', '本科', '硕士', '年']):
                                job.location = f"{city}-{location_raw}"
                            else:
                                # 如果取到的不是地点信息，直接用城市名
                                job.location = city

                        if job.job_name:
                            jobs.append(job)
                    except Exception as e:
                        logger.warning(f"解析智联招聘卡片失败: {e}")
                        continue

                logger.info(f"智联招聘解析完成: {len(jobs)} 个岗位")
                await context.close()
                await browser.close()

        except Exception as e:
            logger.error("[智联] 搜索异常: type={}, msg={}", type(e).__name__, str(e))
            logger.error("[智联] 异常堆栈:\n{}", traceback.format_exc())

        return jobs

    async def parse_job_detail(self, url: str) -> Optional[JobItem]:
        logger.warning("智联招聘详情解析未实现")
        return None

    async def send_greeting(self, job_url: str, greeting_message: str) -> Dict:
        """向智联招聘岗位发送打招呼消息"""
        logger.info("[智联][投递] === 开始投递 ===")
        logger.info("[智联][投递] url={}, message_len={}", job_url[:80], len(greeting_message))
        logger.debug("[智联][投递] 消息内容: {}", greeting_message[:100])
        
        if not job_url:
            logger.error("[智联][投递] 岗位URL为空，终止")
            return {"success": False, "message": "岗位URL为空"}

        try:
            # 步骤1: 打开浏览器并加载Cookie
            logger.info("[智联][投递] 步骤1/4: 启动 Playwright 浏览器并加载Cookie...")
            t1_start = time.time()
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
                )
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                # 加载已保存的登录Cookie
                if self.has_cookies():
                    cookies = self.get_cookies()
                    await context.add_cookies(cookies)
                    logger.info("[智联][投递] 已加载 {} 条Cookie", len(cookies))

                page = await context.new_page()
                t1_end = time.time()
                logger.info("[智联][投递] 步骤1完成: 浏览器启动耗时={:.2f}s", t1_end - t1_start)

                # 步骤2: 访问岗位详情页
                logger.info("[智联][投递] 步骤2/4: 访问岗位详情页...")
                t2_start = time.time()
                await page.goto(job_url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000)
                t2_end = time.time()

                # 检查是否登录
                current_url = page.url
                if "login" in current_url.lower() or "passport" in current_url.lower():
                    logger.warning("[智联][投递] 步骤2失败: 未登录, 重定向到={}", current_url[:80])
                    await browser.close()
                    return {"success": False, "message": "智联招聘未登录，Cookie可能已过期，请重新登录"}
                logger.info("[智联][投递] 步骤2完成: 页面加载正常, 耗时={:.2f}s", t2_end - t2_start)

                # 步骤3: 查找并点击沟通/投递按钮（原生DOM遍历）
                logger.info("[智联][投递] 步骤3/4: 查找沟通/投递按钮(原生DOM遍历)...")
                t3_start = time.time()
                apply_clicked = await page.evaluate("""
                    () => {
                        // 原生DOM遍历，搜索投递关键词
                        const keywords = ['立即沟通', '立即投递', '投递简历', '聊一聊', '沟通', '申请职位'];
                        const elements = document.querySelectorAll('button, a, [role="button"], span');
                        for (const el of elements) {
                            const text = (el.textContent || '').trim();
                            for (const kw of keywords) {
                                if (text === kw || text.includes(kw)) {
                                    if (el.offsetParent !== null) {
                                        el.click();
                                        return 'clicked: ' + kw + ' on <' + el.tagName + '>';
                                    }
                                }
                            }
                        }
                        // 兜底：class前缀匹配
                        const classSelectors = ['[class*="btn-chat"]', '[class*="apply-btn"]', '[class*="btn-apply"]'];
                        for (const sel of classSelectors) {
                            const btn = document.querySelector(sel);
                            if (btn && btn.offsetParent !== null) {
                                btn.click();
                                return sel;
                            }
                        }
                        return null;
                    }
                """)

                if apply_clicked:
                    await page.wait_for_timeout(2000)
                    t3_end = time.time()
                    logger.info("[智联][投递] 步骤3完成: 点击成功({}), 耗时={:.2f}s",
                               apply_clicked, t3_end - t3_start)
                    
                    # 步骤4: 输入消息并发送
                    logger.info("[智联][投递] 步骤4/4: 输入消息文本...")
                    t4_start = time.time()
                    has_input = await page.evaluate("""
                        (msg) => {
                            const inputs = document.querySelectorAll('textarea, input[type="text"]');
                            for (const inp of inputs) {
                                if (inp.offsetParent !== null) {
                                    inp.value = msg;
                                    inp.dispatchEvent(new Event('input', { bubbles: true }));
                                    return true;
                                }
                            }
                            return false;
                        }
                    """, greeting_message)
                    
                    if has_input:
                        logger.info("[智联][投递] 消息已填入输入框")
                        await page.wait_for_timeout(500)
                        
                        # 点击发送按钮
                        submit_clicked = await page.evaluate("""
                            () => {
                                const btns = document.querySelectorAll('button, a, span');
                                for (const btn of btns) {
                                    const text = btn.textContent || '';
                                    if ((text.includes('发送') || text.includes('提交') || text.includes('确定')) && btn.offsetParent !== null) {
                                        btn.click();
                                        return text.trim();
                                    }
                                }
                                return null;
                            }
                        """)
                        await page.wait_for_timeout(2000)
                        t4_end = time.time()
                        logger.info("[智联][投递] 步骤4完成: 提交按钮={}, 耗时={:.2f}s", 
                                   submit_clicked or "未找到", t4_end - t4_start)
                    else:
                        t4_end = time.time()
                        logger.warning("[智联][投递] 步骤4未找到输入框, 耗时={:.2f}s", t4_end - t4_start)
                    
                    await browser.close()
                    logger.info("[智联][投递] === 投递成功 ===")
                    return {"success": True, "message": "沟通消息已发送"}
                else:
                    logger.warning("[智联][投递] 步骤3失败: 未找到沟通/投递按钮（可能已沟通过或页面结构变更）")
                    await browser.close()
                    return {"success": False, "message": "未找到沟通按钮，可能已沟通过或需要手动操作"}
                
        except Exception as e:
            logger.error("[智联][投递] === 投递异常 ===: type={}, msg={}", type(e).__name__, str(e))
            logger.error("[智联][投递] 堆栈: {}", traceback.format_exc())
            return {"success": False, "message": f"投递异常: {str(e)}"}