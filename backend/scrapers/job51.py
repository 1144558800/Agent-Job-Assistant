# -*- coding: utf-8 -*-
"""
前程无忧51Job爬虫 - 使用 we.51job.com 新平台 + DOM结构化提取
"""
import os
import time
import json
import traceback
from typing import List, Optional, Dict
from pathlib import Path
from loguru import logger
from playwright.async_api import async_playwright

from .base import BaseScraper, JobItem

# 设置 Playwright 浏览器路径
_browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(
    Path(__file__).resolve().parent.parent.parent / "playwright-browsers"
)
if os.path.isdir(_browser_path):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browser_path


class Job51Scraper(BaseScraper):
    """前程无忧51Job爬虫 - 使用 we.51job.com 新平台"""

    def __init__(self):
        super().__init__()
        self.platform = "前程无忧"
        self.search_url = "https://we.51job.com/pc/search"
        self.cookie_file = Path(__file__).resolve().parent / "job51_cookies.json"

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
            resp = session.get("https://i.51job.com/userset/my_51job.php", timeout=10, allow_redirects=True)
            final_url = resp.url
            if "login" in final_url.lower() or "passport" in final_url.lower():
                logger.warning("[前程无忧] Cookie验证失败：重定向到登录页 url={}", final_url)
                return False
            body = resp.text[:5000]
            if 'passport' in body.lower() or '扫码登录' in body or '统一登录' in body or '登录51job' in body:
                logger.warning("[前程无忧] Cookie验证失败：页面包含登录表单")
                return False
            logger.info("[前程无忧] Cookie验证通过 final_url={}", final_url)
            return True
        except Exception as e:
            logger.warning("[前程无忧] Cookie验证异常：{}", e)
            return False

    # ---- 手动登录 ----
    async def manual_login(self) -> tuple:
        """打开浏览器窗口让用户手动登录前程无忧，完成后保存Cookie"""
        logger.info("[前程无忧] 打开浏览器窗口，请在弹出的Chrome中手动登录...")
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
                logger.info("[前程无忧] 已打开登录页面，等待用户完成登录（最多5分钟）...")

                logged_in = False
                # 等待页面完全加载后再开始检测（避免首帧即误判）
                await page.wait_for_timeout(3000)
                logger.info("[前程无忧] 开始检测登录状态，请在弹出窗口中扫码或输入账号...")
                for i in range(300):
                    current_url = page.url
                    if "login" not in current_url.lower() and "passport" not in current_url.lower():
                        has_user = await page.evaluate("""
                            () => {
                                // 方式1: 检查页面是否有已登录专属文字
                                const bodyText = document.body.textContent || '';
                                const loginKeywords = ['退出登录', '我的简历', '我的收藏', '个人中心', '我的51job', '投递记录', '我的'];
                                if (loginKeywords.some(k => bodyText.includes(k))) {
                                    return true;
                                }
                                // 方式2: 检查DOM元素，排除"登录/注册"按钮
                                const userEls = document.querySelectorAll('[class*="user"], [class*="avatar"], [class*="account"], [class*="nickname"], [class*="personal"]');
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
                    logger.info("[前程无忧] 登录成功！Cookie已保存，共 {} 条。请关闭浏览器窗口...", len(cookies))
                    # 等待用户手动关闭浏览器窗口
                    try:
                        while True:
                            await page.wait_for_timeout(1000)
                    except Exception:
                        pass
                    return (True, [])
                else:
                    logger.warning("[前程无忧] 登录超时")
                    await context.close()
                    await browser.close()
                    return (False, [])
        except Exception as e:
            logger.error("[前程无忧] manual_login异常: {}", e)
            return (False, [])

    async def search(self, keyword: str, city: str = "", page: int = 1) -> List[JobItem]:
        """搜索岗位 - 从 we.51job.com DOM中提取结构化数据"""
        logger.info(f"[前程无忧] 搜索: keyword={keyword}, city={city}, page={page}")
        jobs = []

        try:
            t0 = time.time()
            logger.info("[前程无忧] 步骤1: 启动 Playwright 浏览器...")
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
                )
                t1 = time.time()
                logger.info("[前程无忧] 步骤1 完成: 浏览器启动耗时={:.2f}s", t1 - t0)

                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    viewport={"width": 1920, "height": 1080},
                )
                page_obj = await context.new_page()

                # 构建搜索URL
                params = f"keyword={keyword}&searchType=2"
                if city:
                    params += f"&jobArea={city}"
                url = f"{self.search_url}?{params}"

                logger.info("[前程无忧] 步骤2: 访问搜索页面 {}", url)
                await page_obj.goto(url, wait_until="networkidle", timeout=30000)
                await page_obj.wait_for_timeout(3000)
                t2 = time.time()
                logger.info("[前程无忧] 步骤2 完成: 页面加载耗时={:.2f}s", t2 - t1)

                # 检查是否有岗位列表
                has_jobs = await page_obj.evaluate(
                    "document.querySelectorAll('.joblist-item').length"
                )
                logger.info("[前程无忧] 步骤3: DOM检测, .joblist-item数量={}", has_jobs)

                if has_jobs == 0:
                    logger.warning("[前程无忧] 页面无岗位数据（DOM选择器可能已变更）")
                    await context.close()
                    await browser.close()
                    return []

                # 从DOM提取结构化数据
                logger.info("[前程无忧] 步骤4: 执行JS提取DOM数据...")
                jobs_data = await page_obj.evaluate("""
                    () => {
                        const results = [];
                        const cards = document.querySelectorAll('.joblist-item');

                        cards.forEach(card => {
                            try {
                                // 从 sensorsdata 属性提取结构化数据
                                const sensorEl = card.querySelector('[sensorsdata]');
                                let sensorData = {};
                                if (sensorEl) {
                                    try {
                                        sensorData = JSON.parse(sensorEl.getAttribute('sensorsdata'));
                                    } catch(e) {}
                                }

                                // 岗位名称
                                const nameEl = card.querySelector('.jname.text-cut');
                                const jobName = nameEl ? nameEl.textContent.trim()
                                    : (sensorData.jobTitle || '');

                                // 岗位链接
                                let jobUrl = '';
                                if (nameEl && nameEl.tagName === 'A') {
                                    jobUrl = nameEl.href;
                                } else if (nameEl) {
                                    const link = nameEl.closest('a');
                                    if (link) jobUrl = link.href;
                                }
                                if (!jobUrl && sensorData.jobId) {
                                    jobUrl = 'https://we.51job.com/job/' + sensorData.jobId + '.html';
                                }

                                // 公司名称 - 从整个卡片的所有文本中查找
                                let companyName = '';
                                const allEls = card.querySelectorAll('.joblist-item-right span, .joblist-item-right div, .joblist-item-right a, .joblist-item-right p');
                                // 优先找第一个包含公司关键词的元素的纯文本部分
                                for (const el of allEls) {
                                    const t = el.textContent.trim();
                                    if ((t.includes('有限公司') || t.includes('股份')
                                            || t.includes('集团') || t.includes('有限责任'))
                                        && !t.includes('http')) {
                                        // 只取公司名部分（第一个空格/换行前的文本，即纯公司名）
                                        const match = t.match(/^([\u4e00-\u9fa5（）()a-zA-Z0-9]+(?:有限公司|股份[^\\s]*|集团|有限责任公司?))/);
                                        companyName = match ? match[1] : t.split(/[\\s\\n]/)[0];
                                        break;
                                    }
                                }

                                // 薪资
                                let salary = sensorData.jobSalary || '';
                                if (!salary) {
                                    const text = card.textContent;
                                    const salaryMatch = text.match(/([0-9.]+\\s*-\\s*[0-9.]+\\s*(万|千|K|元))/);
                                    if (salaryMatch) salary = salaryMatch[1];
                                }

                                // 地点
                                const areaEl = card.querySelector('.area');
                                let location = areaEl ? areaEl.textContent.trim() : '';
                                if (!location) location = sensorData.jobArea || '';

                                // 学历要求
                                let degree = sensorData.jobDegree || '';
                                // 经验要求
                                let experience = sensorData.jobYear || '';

                                // 完整的描述文本
                                const fullText = card.textContent.replace(/\\s+/g, ' ').trim().substring(0, 500);

                                results.push({
                                    jobName: jobName,
                                    companyName: companyName,
                                    salary: salary,
                                    location: location,
                                    degree: degree,
                                    experience: experience,
                                    fullText: fullText,
                                    jobId: sensorData.jobId || '',
                                    jobUrl: jobUrl
                                });
                            } catch(e) {}
                        });
                        return results;
                    }
                """)

                logger.info("[前程无忧] 步骤4 完成: JS提取 {} 条原始数据", len(jobs_data))
                t3 = time.time()

                for item in jobs_data:
                    try:
                        job = JobItem(platform=self.platform)
                        job.job_name = item.get("jobName", "")
                        job.company_name = item.get("companyName", "")
                        job.salary = item.get("salary", "")
                        # 确保location字段包含搜索城市名（前程无忧location可能只有区名）
                        location_raw = item.get("location", "")
                        if city and location_raw and city not in location_raw:
                            location_raw = f"{city}-{location_raw}"
                        job.location = location_raw
                        job.job_url = item.get("jobUrl", "")
                        job.platform_job_id = str(item.get("jobId", ""))  # 从 sensorsdata 提取的岗位ID

                        # 构建岗位描述
                        desc_parts = []
                        if item.get("degree"):
                            desc_parts.append(f"学历要求: {item['degree']}")
                        if item.get("experience"):
                            desc_parts.append(f"经验要求: {item['experience']}")
                        if item.get("fullText"):
                            desc_parts.append(item["fullText"])
                        job.responsibilities = "\n".join(desc_parts)
                        job.requirements = job.responsibilities

                        jobs.append(job)
                    except Exception as e:
                        logger.warning(f"解析前程无忧岗位失败: {e}")
                        continue

                logger.info("[前程无忧] 解析完成: {} 个岗位, 解析耗时={:.2f}s, 总耗时={:.2f}s", 
                           len(jobs), time.time() - t3, time.time() - t0)
                await context.close()
                await browser.close()

        except Exception as e:
            logger.error("[前程无忧] 搜索异常: type={}, msg={}", type(e).__name__, str(e))
            logger.error("[前程无忧] 异常堆栈:\n{}", traceback.format_exc())

        logger.info("[前程无忧] 最终返回 {} 个岗位", len(jobs))
        return jobs

    async def parse_job_detail(self, url: str) -> Optional[JobItem]:
        """解析岗位详情"""
        return None

    async def send_greeting(self, job_url: str, greeting_message: str) -> Dict:
        """向前程无忧岗位发送打招呼/投递消息"""
        logger.info("[前程无忧][投递] === 开始投递 ===")
        logger.info("[前程无忧][投递] url={}, message_len={}", job_url[:80], len(greeting_message))
        logger.debug("[前程无忧][投递] 消息内容: {}", greeting_message[:100])
        
        if not job_url:
            logger.error("[前程无忧][投递] 岗位URL为空，终止")
            return {"success": False, "message": "岗位URL为空"}

        try:
            # 步骤1: 打开浏览器并加载Cookie
            logger.info("[前程无忧][投递] 步骤1/4: 启动 Playwright 浏览器并加载Cookie...")
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
                    logger.info("[前程无忧][投递] 已加载 {} 条Cookie", len(cookies))

                page = await context.new_page()
                t1_end = time.time()
                logger.info("[前程无忧][投递] 步骤1完成: 浏览器启动耗时={:.2f}s", t1_end - t1_start)

                # 步骤2: 访问岗位详情页
                logger.info("[前程无忧][投递] 步骤2/4: 访问岗位详情页...")
                t2_start = time.time()
                await page.goto(job_url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000)
                t2_end = time.time()

                # 检查是否登录
                current_url = page.url
                if "login" in current_url.lower() or "passport" in current_url.lower():
                    logger.warning("[前程无忧][投递] 步骤2失败: 未登录, 重定向到={}", current_url[:80])
                    await browser.close()
                    return {"success": False, "message": "前程无忧未登录，Cookie可能已过期，请重新登录"}
                logger.info("[前程无忧][投递] 步骤2完成: 页面加载正常, 耗时={:.2f}s", t2_end - t2_start)

                # 步骤3: 查找并点击投递按钮（原生DOM遍历）
                logger.info("[前程无忧][投递] 步骤3/4: 查找投递按钮(原生DOM遍历)...")
                t3_start = time.time()
                apply_clicked = await page.evaluate("""
                    () => {
                        // 原生DOM遍历，搜索投递关键词
                        const keywords = ['立即申请', '投递简历', '立即投递', '申请职位'];
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
                        const classSelectors = ['[class*="apply"]', '[class*="btn-apply"]', '[class*="btn-goto"]', '[class*="btn-apply"]'];
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
                    logger.info("[前程无忧][投递] 步骤3完成: 点击成功({}), 耗时={:.2f}s",
                               apply_clicked, t3_end - t3_start)
                    
                    # 步骤4: 填写留言并提交
                    logger.info("[前程无忧][投递] 步骤4/4: 填写留言文本...")
                    t4_start = time.time()
                    has_dialog = await page.evaluate("""
                        (msg) => {
                            const textareas = document.querySelectorAll('textarea');
                            for (const ta of textareas) {
                                if (ta.offsetParent !== null) {
                                    ta.value = msg;
                                    ta.dispatchEvent(new Event('input', { bubbles: true }));
                                    return true;
                                }
                            }
                            return false;
                        }
                    """, greeting_message)
                    
                    if has_dialog:
                        logger.info("[前程无忧][投递] 留言已填入文本框")
                        await page.wait_for_timeout(500)
                        
                        # 点击发送/提交按钮
                        submit_clicked = await page.evaluate("""
                            () => {
                                const btns = document.querySelectorAll('button, a');
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
                        logger.info("[前程无忧][投递] 步骤4完成: 提交按钮={}, 耗时={:.2f}s", 
                                   submit_clicked or "未找到", t4_end - t4_start)
                    else:
                        t4_end = time.time()
                        logger.warning("[前程无忧][投递] 步骤4未找到留言文本框, 耗时={:.2f}s", t4_end - t4_start)
                    
                    await browser.close()
                    logger.info("[前程无忧][投递] === 投递成功 ===")
                    return {"success": True, "message": "投递请求已发送"}
                else:
                    logger.warning("[前程无忧][投递] 步骤3失败: 未找到投递按钮（可能已投递过或页面结构变更）")
                    await browser.close()
                    return {"success": False, "message": "未找到投递按钮，可能已投递过或需要手动操作"}
                
        except Exception as e:
            logger.error("[前程无忧][投递] === 投递异常 ===: type={}, msg={}", type(e).__name__, str(e))
            logger.error("[前程无忧][投递] 堆栈: {}", traceback.format_exc())
            return {"success": False, "message": f"投递异常: {str(e)}"}