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
                    if (!cards.length) {
                        // 终极兜底：寻找所有看起来像岗位卡片的元素
                        const allElements = document.querySelectorAll('li, .card-item, .list-item');
                        cards = [];
                        allElements.forEach(el => {
                            const text = el.textContent || '';
                            if (text.includes('\u804c\u4f4d') || text.includes('\u85aa\u8d44') || text.includes('k') || text.includes('\u4e07')) {
                                cards.push(el);
                            }
                        });
                        if (cards.length) cards = Array.from(cards);
                        else cards = [];
                    }
                    const results = [];
                    cards.forEach(card => {
                        try {
                            // 1. 提取岗位名称 - 从 ellipsis-1 的文本内容获取（不含"招聘"前缀）
                            const nameEl = card.querySelector('[data-nick="job-detail-job-info"] .ellipsis-1');
                            const jobName = nameEl ? nameEl.textContent.trim() : '';

                            // 2. 提取地点 - 【】中的 ellipsis-1 元素
                            let location = '';
                            const brackets = card.querySelectorAll('[class*="AoLGr"]');
                            brackets.forEach(b => {
                                if (b.textContent.trim() === '\u3010') {
                                    const nextSpan = b.nextElementSibling;
                                    if (nextSpan && nextSpan.classList.contains('ellipsis-1')) {
                                        location = nextSpan.textContent.trim();
                                    }
                                }
                            });
                            // 备用: 如果上面没找到，搜索【】之间的文本
                            if (!location) {
                                const allText = card.textContent.replace(/\\s+/g, ' ').trim();
                                const locMatch = allText.match(/\u3010(.+?)\u3011/);
                                if (locMatch) location = locMatch[1];
                            }

                            // 3. 提取薪资 - 找包含 k/K 或 '薪' 的 span
                            let salary = '';
                            const allSpans = card.querySelectorAll('span');
                            allSpans.forEach(sp => {
                                const t = sp.textContent.trim();
                                if (/\\d+\\s*[-~]\\s*\\d+\\s*[kK\u4e07\u85aa]/.test(t)) {
                                    salary = t;
                                }
                            });

                            // 4. 提取公司名 - data-nick="job-detail-company-info" 下的 ellipsis-1
                            let companyName = '';
                            const companyInfo = card.querySelector('[data-nick="job-detail-company-info"]');
                            if (companyInfo) {
                                const companyEl = companyInfo.querySelector('.ellipsis-1');
                                if (companyEl) {
                                    companyName = companyEl.textContent.trim();
                                }
                            }

                            // 5. 提取工作年限和学历
                            let experience = '';
                            let education = '';
                            const detailBox = card.querySelector('.job-detail-box');
                            if (detailBox) {
                                const spans = detailBox.querySelectorAll('[class*="hJbMl"]');
                                if (spans.length >= 1) experience = spans[0].textContent.trim();
                                if (spans.length >= 2) education = spans[1].textContent.trim();
                            }

                            // 6. 提取岗位链接
                            let jobUrl = '';
                            const link = card.querySelector('[data-nick="job-detail-job-info"]');
                            if (link) {
                                const href = link.getAttribute('href') || '';
                                jobUrl = href.startsWith('http') ? href : 'https://www.liepin.com' + href;
                            }

                            results.push({
                                jobName: jobName,
                                location: location,
                                salary: salary,
                                companyName: companyName,
                                experience: experience,
                                education: education,
                                url: jobUrl
                            });
                        } catch(e) {
                            // 单卡片解析失败跳过
                        }
                    });
                    return results;
                }
                """)

                for card_data in cards_data:
                    try:
                        job = JobItem(platform=self.platform)
                        job.job_name = card_data.get("jobName", "")
                        job.company_name = card_data.get("companyName", "")
                        job.salary = card_data.get("salary", "")
                        job.location = card_data.get("location", "")
                        job.job_url = card_data.get("url", "")
                        # 从URL中提取岗位ID
                        job_id = ""
                        if job.job_url:
                            import re
                            m = re.search(r'/job/(\d+)', job.job_url)
                            if m:
                                job_id = m.group(1)
                        job.platform_job_id = job_id

                        # 拼接岗位要求描述
                        exp = card_data.get("experience", "")
                        edu = card_data.get("education", "")
                        details = []
                        if exp:
                            details.append(exp)
                        if edu:
                            details.append(edu)
                        if details:
                            job.responsibilities = " ".join(details)

                        if job.job_name:
                            jobs.append(job)
                    except Exception as e:
                        logger.warning(f"解析猎聘卡片数据失败: {e}")
                        continue

                logger.info(f"猎聘解析完成: {len(jobs)} 个岗位")
                await context.close()
                await browser.close()

        except Exception as e:
            logger.error("[猎聘] 搜索异常: type={}, msg={}", type(e).__name__, str(e))
            logger.error("[猎聘] 异常堆栈:\n{}", traceback.format_exc())

        return jobs

    async def parse_job_detail(self, url: str) -> Optional[JobItem]:
        return None

    async def send_greeting(self, job_url: str, greeting_message: str) -> Dict:
        """向猎聘岗位发送打招呼消息"""
        logger.info("[猎聘][投递] === 开始投递 ===")
        logger.info("[猎聘][投递] url={}, message_len={}", job_url[:80], len(greeting_message))
        logger.debug("[猎聘][投递] 消息内容: {}", greeting_message[:100])

        if not job_url:
            logger.error("[猎聘][投递] 岗位URL为空，终止")
            return {"success": False, "message": "岗位URL为空"}

        try:
            # 步骤1: 打开浏览器并加载Cookie
            logger.info("[猎聘][投递] 步骤1/4: 启动 Playwright 浏览器并加载Cookie...")
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
                    logger.info("[猎聘][投递] 已加载 {} 条Cookie", len(cookies))

                page = await context.new_page()
                t1_end = time.time()
                logger.info("[猎聘][投递] 步骤1完成: 浏览器启动耗时={:.2f}s", t1_end - t1_start)

                # 步骤2: 访问岗位详情页
                logger.info("[猎聘][投递] 步骤2/4: 访问岗位详情页...")
                t2_start = time.time()
                await page.goto(job_url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000)
                t2_end = time.time()

                # 检查是否登录
                current_url = page.url
                page_title = await page.title()
                if "login" in current_url.lower() or "passport" in current_url.lower():
                    logger.warning("[猎聘][投递] 步骤2失败: 未登录, 重定向到={}", current_url[:80])
                    await browser.close()
                    return {"success": False, "message": "猎聘未登录，Cookie可能已过期，请重新登录"}
                logger.info("[猎聘][投递] 步骤2完成: 页面加载正常 title={}, 耗时={:.2f}s", page_title, t2_end - t2_start)

                # 步骤3: 查找并点击沟通按钮（用原生DOM遍历，不用Playwright伪类）
                logger.info("[猎聘][投递] 步骤3/4: 查找沟通按钮(原生DOM遍历)...")
                t3_start = time.time()

                apply_clicked = await page.evaluate("""
                    () => {
                        // 原生DOM遍历，搜索"立即沟通"文本，不依赖Playwright专有选择器
                        const keywords = ['立即沟通', '立即投递', '沟通', '聊一聊', '投递简历'];

                        // 策略1: 遍历所有button和a标签
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

                        // 策略2: 遍历所有div/spans，有些按钮用div实现
                        const allDivs = document.querySelectorAll('div');
                        for (const div of allDivs) {
                            const childText = (div.textContent || '').trim();
                            if (childText === '立即沟通' && div.offsetParent !== null) {
                                div.click();
                                return 'clicked: div.立即沟通';
                            }
                        }

                        return null;
                    }
                """)

                if apply_clicked:
                    await page.wait_for_timeout(3000)
                    t3_end = time.time()
                    logger.info("[猎聘][投递] 步骤3完成: 点击成功({}), 耗时={:.2f}s",
                               apply_clicked, t3_end - t3_start)

                    # 步骤4: 输入消息并发送
                    logger.info("[猎聘][投递] 步骤4/4: 输入消息文本...")
                    t4_start = time.time()
                    has_input = await page.evaluate("""
                        (msg) => {
                            // 等对话框出现后找所有可见的textarea/input
                            const inputs = document.querySelectorAll('textarea, input[type="text"], [contenteditable="true"]');
                            for (const inp of inputs) {
                                if (inp.offsetParent !== null) {
                                    if (inp.getAttribute('contenteditable') === 'true') {
                                        inp.textContent = msg;
                                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                                    } else {
                                        inp.value = msg;
                                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                                    }
                                    return true;
                                }
                            }
                            // 兜底：找聊天对话框区域的输入框
                            const allInputs = document.querySelectorAll('textarea, input');
                            for (const inp of allInputs) {
                                const rect = inp.getBoundingClientRect();
                                if (rect.width > 0 && rect.height > 0 && window.getComputedStyle(inp).display !== 'none') {
                                    inp.value = msg;
                                    inp.dispatchEvent(new Event('input', { bubbles: true }));
                                    return true;
                                }
                            }
                            return false;
                        }
                    """, greeting_message)

                    if has_input:
                        logger.info("[猎聘][投递] 消息已填入输入框")
                        await page.wait_for_timeout(1000)

                        # 点击发送按钮
                        submit_clicked = await page.evaluate("""
                            () => {
                                const keywords = ['发送', '提交'];
                                const elements = document.querySelectorAll('button, a, span, div');
                                for (const el of elements) {
                                    const text = (el.textContent || '').trim();
                                    for (const kw of keywords) {
                                        if (text === kw) {
                                            if (el.offsetParent !== null) {
                                                el.click();
                                                return text;
                                            }
                                        }
                                    }
                                }
                                // 按enter发送
                                const enterEvt = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true });
                                const activeEl = document.activeElement;
                                if (activeEl && (activeEl.tagName === 'TEXTAREA' || activeEl.tagName === 'INPUT')) {
                                    activeEl.dispatchEvent(enterEvt);
                                    return 'pressed Enter';
                                }
                                return null;
                            }
                        """)
                        await page.wait_for_timeout(2000)
                        t4_end = time.time()
                        logger.info("[猎聘][投递] 步骤4完成: 提交方式={}, 耗时={:.2f}s",
                                   submit_clicked or "未找到", t4_end - t4_start)
                    else:
                        t4_end = time.time()
                        logger.warning("[猎聘][投递] 步骤4未找到输入框, 耗时={:.2f}s", t4_end - t4_start)

                    await browser.close()
                    logger.info("[猎聘][投递] === 投递成功 ===")
                    return {"success": True, "message": "打招呼消息已发送"}
                else:
                    logger.warning("[猎聘][投递] 步骤3失败: 未找到沟通按钮（可能已沟通过或页面结构变更）")
                    await browser.close()
                    return {"success": False, "message": "未找到沟通按钮，可能已沟通过或需要手动操作"}

        except Exception as e:
            logger.error("[猎聘][投递] === 投递异常 ===: type={}, msg={}", type(e).__name__, str(e))
            logger.error("[猎聘][投递] 堆栈: {}", traceback.format_exc())
            return {"success": False, "message": f"投递异常: {str(e)}"}
