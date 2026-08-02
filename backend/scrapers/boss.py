# -*- coding: utf-8 -*-
"""
BOSS直聘爬虫 - 使用持久化浏览器配置文件登录，搜索时注入 Cookie
"""
import os
import json
import random
import re
import time
import asyncio
import traceback
from typing import List, Optional, Dict
from urllib.parse import urlencode
from pathlib import Path
from loguru import logger
from patchright.async_api import async_playwright

from .base import BaseScraper, JobItem

# 设置 Playwright 浏览器路径
_browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(
    Path(__file__).resolve().parent.parent.parent / "playwright-browsers"
)
if os.path.isdir(_browser_path):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browser_path

# 持久化浏览器配置文件目录（仅用于手动登录）
BOSS_PROFILE_DIR = str(Path(__file__).resolve().parent / "boss_profile")


class BossScraper(BaseScraper):
    """BOSS直聘爬虫"""

    def __init__(self):
        super().__init__()
        self.platform = "BOSS直聘"
        self.base_url = "https://www.zhipin.com"
        self.search_url = "https://www.zhipin.com/web/geek/job"
        # BOSS直聘可能的API端点
        self.api_urls = [
            "https://www.zhipin.com/wapi/zpgeek/search/joblist.json",
            "https://www.zhipin.com/wapi/zprelation/geek/search/joblist",
            "https://www.zhipin.com/wapi/zpgeek/v2/search/joblist.json",
        ]
        # Cookie 文件路径（搜索时使用）
        self.cookie_file = Path(__file__).resolve().parent / "boss_cookies.json"
        self.profile_dir = BOSS_PROFILE_DIR
        self._use_visible_browser = True  # 投递时使用可见浏览器，防止被BOSS直聘检测无头模式

        # BOSS直聘城市代码映射（中文城市名 → 数字代码）
        self.city_codes = {
            "北京": "101010100",
            "上海": "101020100",
            "广州": "101280101",
            "深圳": "101280601",
            "杭州": "101210101",
            "南京": "101190100",
            "苏州": "101190401",
            "成都": "101270101",
            "武汉": "101200101",
            "西安": "101110101",
            "长沙": "101250101",
            "重庆": "101040100",
            "天津": "101030100",
            "郑州": "101180101",
            "合肥": "101220101",
            "宁波": "101210401",
            "青岛": "101120201",
            "厦门": "101230201",
            "大连": "101070201",
            "沈阳": "101070101",
            "济南": "101120101",
            "福州": "101230101",
            "哈尔滨": "101050101",
            "长春": "101060101",
            "石家庄": "101090101",
            "南昌": "101240101",
            "昆明": "101290101",
            "贵阳": "101260101",
            "南宁": "101300101",
            "海口": "101310101",
            "太原": "101100101",
            "兰州": "101160101",
            "乌鲁木齐": "101130101",
            "西宁": "101150101",
            "银川": "101170101",
            "呼和浩特": "101080101",
            "拉萨": "101140101",
            "珠海": "101280701",
            "佛山": "101280301",
            "东莞": "101281601",
            "无锡": "101190201",
            "常州": "101191101",
            "嘉兴": "101210301",
            "绍兴": "101210501",
            "南通": "101190501",
            "徐州": "101190801",
            "扬州": "101190601",
            "惠州": "101280301",
            "中山": "101281701",
            "淮安": "101190901",
            "镇江": "101190301",
            "盐城": "101190701",
            "泰州": "101191201",
            "沈阳": "101070101",
            "三亚": "101310201",
            "威海": "101171301",
            "潍坊": "101120601",
            "烟台": "101120501",
            "芜湖": "101220301",
            "洛阳": "101180901",
        }

    def has_cookies(self) -> bool:
        """检查是否有 Cookie 文件"""
        return self.cookie_file.exists()

    def verify_cookies(self) -> bool:
        """快速验证 Cookie 是否有效（使用 requests 通过 API 请求验证，耗时 <3秒）"""
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
                "Referer": "https://www.zhipin.com/",
            })
            url = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?city=101190100&query=&page=1"
            resp = session.get(url, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                code = data.get("code", -1)
                if code == 0:
                    logger.info("[BOSS] Cookie验证通过：API返回code=0")
                    return True
                else:
                    logger.warning("[BOSS] Cookie验证失败：API返回code={}，msg={}", code, data.get("message", ""))
                    return False
            else:
                    logger.warning("[BOSS] Cookie验证失败：HTTP状态码={}", resp.status_code)
                    return False
        except Exception as e:
            logger.warning("[BOSS] Cookie验证异常：{}", e)
            return False

    async def is_logged_in(self) -> bool:
        """验证 Cookie 是否有效（通过访问 BOSS 直聘页面检测登录状态）"""
        if not self.has_cookies():
            return False
        
        try:
            async with async_playwright() as p:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=self.profile_dir,
                    channel="chrome",
                    headless=True,
                    args=self._get_browser_launch_args(),
                    viewport={"width": 1280, "height": 800},
                    locale="zh-CN",
                )
                await context.add_init_script(script=self._get_stealth_script())
                page = context.pages[0] if context.pages else await context.new_page()
                
                await page.goto("https://www.zhipin.com/web/geek/job",
                                wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000)
                
                current_url = page.url
                
                if self._is_verify_page(current_url):
                    logger.warning("Cookie 访问触发安全验证，视为未登录")
                    await context.close()
                    return False
                
                is_logged_in = await page.evaluate("""
                    () => {
                        const selectors = [
                            '.user-avatar',
                            '[class*="avatar"]',
                            '[class*="user-info"]',
                            '.job-card-wrapper',
                            '[class*="job-card"]'
                        ];
                        for (const sel of selectors) {
                            if (document.querySelector(sel)) {
                                return true;
                            }
                        }
                        
                        const loginSelectors = [
                            '[class*="login"]',
                            '[class*="qrcode"]',
                            '[data-selector*="QR"]'
                        ];
                        for (const sel of loginSelectors) {
                            if (document.querySelector(sel)) {
                                return false;
                            }
                        }
                        
                        return true;
                    }
                """)
                
                await context.close()
                return is_logged_in
        except Exception as e:
            logger.error(f"验证登录状态失败: {e}")
            return False

    def save_cookies(self, cookies_str: str) -> bool:
        """保存用户提供的 Cookie 字符串到文件"""
        try:
            cookie_list = []
            for item in cookies_str.split(";"):
                item = item.strip()
                if not item:
                    continue
                if "=" in item:
                    name, value = item.split("=", 1)
                    cookie_list.append({
                        "name": name.strip(),
                        "value": value.strip(),
                        "domain": ".zhipin.com",
                        "path": "/"
                    })
            with open(self.cookie_file, "w", encoding="utf-8") as f:
                json.dump(cookie_list, f, ensure_ascii=False, indent=2)
            logger.info(f"BOSS 直聘 Cookie 已保存，共 {len(cookie_list)} 条")
            return True
        except Exception as e:
            logger.error(f"保存 BOSS 直聘 Cookie 失败: {e}")
            return False

    def get_cookies(self) -> list:
        """从文件加载 Cookie"""
        if not self.has_cookies():
            return []
        try:
            with open(self.cookie_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载 BOSS 直聘 Cookie 失败: {e}")
            return []

    async def _collect_cookies_from_profile(self) -> bool:
        """从持久化浏览器配置中提取 Cookie（无头模式，不弹出窗口）"""
        logger.info("从持久化浏览器配置提取 Cookie...")
        try:
            async with async_playwright() as p:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=self.profile_dir,
                    channel="chrome",
                    headless=True,
                    args=self._get_browser_launch_args(),
                    viewport={"width": 1280, "height": 800},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                )
                await context.add_init_script(script=self._get_stealth_script())
                page = context.pages[0] if context.pages else await context.new_page()

                # 访问 BOSS 直聘
                await page.goto("https://www.zhipin.com/web/geek/job",
                                wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(5000)

                # 检查是否已登录
                if "geek" in page.url:
                    cookies = await context.cookies()
                    boss_cookies = [c for c in cookies
                                    if "zhipin.com" in c.get("domain", "")]
                    if boss_cookies:
                        with open(self.cookie_file, "w", encoding="utf-8") as f:
                            json.dump(boss_cookies, f, ensure_ascii=False, indent=2)
                        logger.info(f"从持久化配置提取了 {len(boss_cookies)} 条 Cookie")
                        await context.close()
                        return True

                logger.warning("持久化配置中检测到未登录或无有效 Cookie")
                await context.close()
                return False
        except Exception as e:
            logger.error(f"提取 Cookie 失败: {e}")
            return False

    async def manual_login(self, keyword: str = "", city: str = "") -> tuple:
        """
        打开浏览器窗口让用户手动登录 BOSS 直聘
        如果提供了 keyword+city，登录后自动搜索目标城市的岗位
        会处理安全验证（用户手动完成）
        返回: (是否成功, 岗位列表)
        """
        logger.info("打开 BOSS 直聘浏览器窗口，请在弹出的 Chrome 中手动登录...")
        jobs = []
        try:
            async with async_playwright() as p:
                # 使用持久化配置打开浏览器（正常登录体验）
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=self.profile_dir,
                    channel="chrome",
                    headless=False,
                    args=self._get_browser_launch_args(),
                    viewport={"width": 1280, "height": 800},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    permissions=["geolocation", "notifications"],
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                )
                await context.add_init_script(script=self._get_stealth_script())
                page = context.pages[0] if context.pages else await context.new_page()

                # 先访问首页
                await page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)

                # 检测登录+安全验证状态（等待最多 5 分钟）
                logged_in = False
                verify_resolved = False
                login_page_seen = False
                wait_count = 0
                max_wait = 300  # 最多等待5分钟
                for _ in range(max_wait):
                    try:
                        current_url = page.url
                        # 仍在安全验证页面，等待用户完成
                        if self._is_verify_page(current_url):
                            if wait_count % 30 == 0:
                                logger.info("正在安全验证中，请在浏览器中完成滑块/拼图验证...")
                            verify_resolved = False
                            await page.wait_for_timeout(2000)
                            wait_count += 2
                            continue
                        else:
                            if not verify_resolved:
                                # 安全验证已通过，准备导航到搜索页
                                verify_resolved = True
                                logger.info("安全验证通过，准备导航到搜索页")
                                # 直接导航到搜索页（用目标城市，验证通过后不会立刻再触发验证）
                                if keyword:
                                    from urllib.parse import urlencode
                                    params = {"query": keyword}
                                    target_code = self.city_codes.get(city, "")
                                    if target_code:
                                        params["city"] = target_code
                                    search_url = f"{self.search_url}?{urlencode(params)}"
                                    logger.info(f"导航到搜索页: {search_url}")
                                    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                                    await page.wait_for_timeout(3000)
                                    # 检查是否再次触发验证
                                    if self._is_verify_page(page.url):
                                        logger.warning("搜索也触发了安全验证，请完成...")
                                        continue
                                else:
                                    await page.goto("https://www.zhipin.com/web/geek/job", wait_until="domcontentloaded", timeout=30000)
                                    await page.wait_for_timeout(3000)

                        # === 登录态检测 ===
                        # 使用更精确的检测逻辑，通过页面评估判断登录状态
                        login_state = await page.evaluate("""
                            () => {
                                // 检测已登录的标志：用户头像、用户名、退出按钮
                                const loggedInSelectors = [
                                    '.user-avatar',
                                    '[class*="avatar"]',
                                    '[class*="user-info"]',
                                    '[class*="user-name"]',
                                    '[class*="logout"]',
                                    '[class*="sign-out"]',
                                    '.job-card-wrapper',
                                    '[class*="job-card"]'
                                ];
                                for (const sel of loggedInSelectors) {
                                    if (document.querySelector(sel)) {
                                        // 如果是岗位卡片，需要确保不是空列表
                                        if (sel.includes('job-card')) {
                                            const cards = document.querySelectorAll(sel);
                                            if (cards.length > 0) return 'logged_in';
                                        } else {
                                            return 'logged_in';
                                        }
                                    }
                                }
                                
                                // 检测未登录的标志：登录按钮、二维码
                                const notLoggedInSelectors = [
                                    '[class*="login-btn"]',
                                    '[class*="login"]',
                                    '[data-selector*="QR"]',
                                    'img[src*="qrcode"]',
                                    '[class*="qrcode"]',
                                    '[class*="扫码登录"]',
                                    '[class*="手机登录"]',
                                    '[class*="账号密码登录"]'
                                ];
                                for (const sel of notLoggedInSelectors) {
                                    if (document.querySelector(sel)) {
                                        return 'not_logged_in';
                                    }
                                }
                                
                                // 无法确定状态
                                return 'unknown';
                            }
                        """)

                        if login_state == 'logged_in':
                            logger.info("检测到已登录状态")
                            logged_in = True
                            break
                        elif login_state == 'not_logged_in':
                            if not login_page_seen:
                                login_page_seen = True
                                logger.info("检测到登录页面，请在浏览器中完成登录...")
                        else:
                            if wait_count % 30 == 0:
                                logger.info("登录状态检测中，等待用户操作...")
                                
                    except Exception as e:
                        logger.debug(f"登录检测异常: {e}")
                    
                    await page.wait_for_timeout(1000)
                    wait_count += 1

                if logged_in:
                    logger.info("BOSS 直聘登录成功!")

                    # 提取 Cookie 保存
                    cookies = await context.cookies()
                    boss_cookies = [c for c in cookies if "zhipin.com" in c.get("domain", "")
                                    or ".zhipin.com" in c.get("domain", "")]
                    with open(self.cookie_file, "w", encoding="utf-8") as f:
                        json.dump(boss_cookies, f, ensure_ascii=False, indent=2)
                    logger.info(f"已提取并保存 {len(boss_cookies)} 条 Cookie")

                    # 如果有关键词，从当前页面提取岗位数据
                    # （页面已在登录检测循环中被导航到搜索URL）
                    if keyword:
                        logger.info(f"正在提取 {city} {keyword} 岗位数据...")
                        # 检查是否仍需要等待安全验证
                        current_url = page.url
                        if self._is_verify_page(current_url):
                            logger.warning("搜索页触发安全验证，请在浏览器中完成...")
                            for _ in range(180):
                                if not self._is_verify_page(page.url):
                                    logger.info("安全验证通过")
                                    await page.wait_for_timeout(3000)
                                    break
                                await page.wait_for_timeout(1000)

                        # 确认当前在搜索页（如不在则导航）
                        if "web/geek/job" not in page.url:
                            from urllib.parse import urlencode
                            params = {"query": keyword}
                            target_code = self.city_codes.get(city, "")
                            if target_code:
                                params["city"] = target_code
                            search_url = f"{self.search_url}?{urlencode(params)}"
                            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                            await page.wait_for_timeout(3000)
                            if self._is_verify_page(page.url):
                                logger.warning("再次触发安全验证，请完成...")
                                for _ in range(180):
                                    if not self._is_verify_page(page.url):
                                        logger.info("安全验证通过")
                                        await page.wait_for_timeout(3000)
                                        break
                                    await page.wait_for_timeout(1000)

                        # 等待岗位卡片出现
                        try:
                            await page.wait_for_selector(
                                ".job-card-wrapper, [class*='job-card'], [class*='job-list'], [class*='geek-list']",
                                timeout=15000
                            )
                        except Exception:
                            logger.warning("搜索页岗位卡片未出现")

                        # 等待数据加载，然后提取
                        await page.wait_for_timeout(3000)
                        await self._human_scroll(page, 3)
                        jobs = await self._extract_jobs_from_page(page)
                        logger.info(f"获取到 {len(jobs)} 个岗位")
                        if jobs:
                            print(f"\n{'='*60}")
                            print(f"  找到 {len(jobs)} 个 {city} {keyword} 岗位!")
                            print(f"{'='*60}")
                            for i, j in enumerate(jobs[:10], 1):
                                print(f"  {i}. {j.job_name} | {j.salary} | {j.company_name} | {j.location}")

                    # 保持浏览器打开，等待用户关闭
                    logger.info("搜索完成，请关闭浏览器窗口")
                    try:
                        await page.wait_for_event("close", timeout=600000)
                    except Exception:
                        pass
                    return True, jobs
                else:
                    logger.warning("BOSS 直聘登录超时")
                    return False, []

        except Exception as e:
            error_msg = str(e)
            if "closed" in error_msg or "Target" in error_msg:
                if self.has_cookies():
                    logger.info("浏览器窗口已关闭，Cookie 已保存")
                    return True, jobs
            logger.error(f"BOSS 直聘手动登录失败: {e}")
            return False, []

    async def _human_scroll(self, page, steps=3):
        """模拟人类滚动行为"""
        for _ in range(steps):
            scroll_amount = random.randint(300, 800)
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await page.wait_for_timeout(random.randint(800, 2000))
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(random.randint(500, 1000))

    async def _simulate_human_activity(self, page, duration_sec: float = 3.0):
        """模拟真实用户行为：鼠标移动、随机滚动、停顿，降低被检测为自动化的风险"""
        start_time = time.time()
        while time.time() - start_time < duration_sec:
            action = random.choice(["scroll", "hover", "move", "pause"])
            if action == "scroll":
                delta = random.randint(100, 400)
                await page.evaluate(f"window.scrollBy(0, {delta})")
                await page.wait_for_timeout(random.randint(300, 700))
            elif action == "hover":
                x = random.randint(200, 1200)
                y = random.randint(100, 600)
                await page.mouse.move(x, y, steps=random.randint(3, 8))
                await page.wait_for_timeout(random.randint(200, 500))
            elif action == "move":
                x = random.randint(200, 1200)
                y = random.randint(100, 600)
                await page.mouse.move(x, y, steps=random.randint(5, 15))
            elif action == "pause":
                await page.wait_for_timeout(random.randint(500, 1500))

    @staticmethod
    def _get_stealth_script() -> str:
        """返回反检测隐身脚本，隐藏 Playwright/自动化特征（最全面版本）"""
        return """
        // 隐藏 webdriver 标记
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        
        // 模拟 chrome 对象
        window.chrome = {
            runtime: { onConnect: { addListener: function() {} }, onMessage: { addListener: function() {} } },
            loadTimes: function() { return {}; },
            csi: function() { return {}; },
            app: { isInstalled: false, InstallState: {}, RunningState: {}, getDetails: function() {}, getIsInstalled: function() {}, installState: function() {} },
        };
        
        // 覆盖 permissions 查询
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        
        // 覆盖 plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => {
                var plugins = [];
                for (var i = 0; i < 5; i++) {
                    plugins.push({ name: 'PDF Viewer ' + i, filename: 'internal-pdf-viewer', description: 'Portable Document Format' });
                }
                plugins.item = function(i) { return this[i]; };
                plugins.namedItem = function(n) { return null; };
                plugins.refresh = function() {};
                return plugins;
            }
        });
        
        // 覆盖 languages
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
        
        // 覆盖硬件特征
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
        Object.defineProperty(navigator, 'productSub', { get: () => '20030107' });
        Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.' });
        
        // 覆盖 connection
        if (navigator.connection) {
            Object.defineProperty(navigator.connection, 'rtt', { get: () => 50 });
        }
        
        // 移除自动化痕迹
        delete window.callPhantom;
        delete window._phantom;
        delete window.__nightmare;
        if (window.__playwright__binding__) { delete window.__playwright__binding__; }
        
        // Canvas 指纹防护
        var getImageData_ = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {
            var context = this.getContext('2d');
            if (context) {
                var imageData = context.getImageData(0, 0, 1, 1);
                var data = imageData.data;
                data[0] = data[0] < 250 ? data[0] + 1 : data[0] - 1;
                context.putImageData(imageData, 0, 0);
            }
            return getImageData_.apply(this, arguments);
        };
        
        // 覆盖 userAgent
        Object.defineProperty(navigator, 'userAgent', {
            get: () => 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
        });
        
        // 防止窗口大小检测
        window.outerWidth = screen.width;
        window.outerHeight = screen.height;
        
        // 覆盖 getBattery
        if (navigator.getBattery) {
            navigator.getBattery = function() {
                return Promise.resolve({
                    charging: true, chargingTime: 0, dischargingTime: Infinity,
                    level: 1, onchargingchange: null, onchargingtimechange: null,
                    ondischargingtimechange: null, onlevelchange: null,
                    addEventListener: function() {}, removeEventListener: function() {}
                });
            };
        }
        """

    @staticmethod
    def _get_browser_launch_args() -> list:
        """返回隐身后动参数，降低被检测为自动化的概率"""
        return [
            "--no-sandbox",
            "--disable-infobars",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-web-security",
            "--disable-features=BlockInsecurePrivateNetworkRequests",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-component-extensions-with-background-pages",
            "--disable-client-side-phishing-detection",
            "--disable-sync",
            "--metrics-recording-only",
            "--disable-default-apps",
            "--mute-audio",
        ]

    async def _extract_jobs_from_page(self, page) -> List[JobItem]:
        """从 BOSS直聘页面提取岗位数据 - 使用文本行解析"""
        jobs = []
        try:
            cards_data = await page.evaluate("""
                (function() {
                    var results = [];
                    var selectors = [
                        '.job-card-wrapper',
                        '[class*="job-card"]',
                        '[class*="job-list"] > li',
                        '[class*="geek-list"] li',
                        '[class*="rec-job"]',
                        'li:has([class*="job-name"])'
                    ];
                    var cards = [];
                    for (var s = 0; s < selectors.length; s++) {
                        var found = document.querySelectorAll(selectors[s]);
                        if (found.length > 0) { cards = found; break; }
                    }
                    for (var c = 0; c < cards.length; c++) {
                        try {
                            var card = cards[c];
                            var jobNameEl = card.querySelector('.job-name');
                            var companyNameEl = card.querySelector('.company-name');
                            var salaryEl = card.querySelector('.salary');
                            var areaEl = card.querySelector('.job-area');

                            var jobName = jobNameEl ? jobNameEl.textContent.trim() : '';
                            var company = companyNameEl ? companyNameEl.textContent.trim() : '';
                            var salary = salaryEl ? salaryEl.textContent.trim() : '';
                            var area = areaEl ? areaEl.textContent.trim() : '';

                            var needParse = (!jobName || !company);
                            if (needParse) {
                                var text = card.innerText || card.textContent || '';
                                var lines = text.split('\\n').map(function(l) { return l.trim(); }).filter(function(l) { return l; });

                                if (lines.length >= 1) {
                                    var firstLine = lines[0];
                                    // 检查字符串是否包含PUA字符
                                    var hasPUAChars = function(str) {
                                        if (!str) return false;
                                        for (var pc = 0; pc < str.length; pc++) {
                                            if (str.charCodeAt(pc) >= 0xE000 && str.charCodeAt(pc) <= 0xF8FF) return true;
                                        }
                                        return false;
                                    };
                                    // 扫描所有行，找出PUA行（薪资行）
                                    var puaLineIdx = -1;
                                    for (var pi = 0; pi < lines.length; pi++) {
                                        if (hasPUAChars(lines[pi])) { puaLineIdx = pi; break; }
                                    }
                                    
                                    var isLocationLine = function(l) {
                                        if (!l) return false;
                                        var cities = ['\u4e0a\u6d77', '\u5317\u4eac', '\u5e7f\u5dde', '\u6df1\u5733'];
                                        for (var ci = 0; ci < cities.length; ci++) {
                                            var city = cities[ci];
                                            if (l === city) return true;
                                            if (l.indexOf(city + '\u00b7') === 0) return true;
                                        }
                                        return false;
                                    };
                                    // 检查是否为经验/学历等非公司名行
                                    var isMetaLine = function(l) {
                                        if (!l) return true;
                                        if (l.indexOf('\u5e74') >= 0 && (l.indexOf('\u7ecf\u9a8c') >= 0 || /\\d/.test(l))) return true;
                                        if (l === '\u7ecf\u9a8c\u4e0d\u9650' || l === '\u5b66\u5386\u4e0d\u9650') return true;
                                        if (l.indexOf('\u5927\u4e13') >= 0 || l.indexOf('\u672c\u79d1') >= 0 || l.indexOf('\u7855\u58eb') >= 0 || l.indexOf('\u535a\u58eb') >= 0) return true;
                                        return false;
                                    };
                                    // 从末尾向前搜索公司名（公司名通常在卡片底部）
                                    var findCompanyFromEnd = function(arr, excludeSet) {
                                        for (var ei = arr.length - 1; ei >= 0; ei--) {
                                            var el = arr[ei];
                                            if (!el) continue;
                                            if (excludeSet && excludeSet.indexOf(el) >= 0) continue;
                                            if (isLocationLine(el)) continue;
                                            if (isMetaLine(el)) continue;
                                            if (el.length > 1) return el;
                                        }
                                        return '';
                                    };
                                    // 从行中搜索地点
                                    var findLocation = function(arr, excludeSet) {
                                        for (var fi = 0; fi < arr.length; fi++) {
                                            var fel = arr[fi];
                                            if (!fel) continue;
                                            if (isLocationLine(fel)) return fel;
                                        }
                                        return '';
                                    };
                                    
                                    // 构建排除集（PUA/PUA行/已识别的jobName）
                                    var excludeLines = {};
                                    if (puaLineIdx >= 0) excludeLines[puaLineIdx] = true;
                                    
                                    // 如果PUA在firstLine中（岗位名+薪资在同一行）
                                    if (puaLineIdx === 0) {
                                        if (!jobName) {
                                            var salaryIdx = -1;
                                            for (var i = 0; i < firstLine.length; i++) {
                                                var code = firstLine.charCodeAt(i);
                                                if (code >= 0xE000 && code <= 0xF8FF) { salaryIdx = i; break; }
                                            }
                                            if (salaryIdx > 0) {
                                                jobName = firstLine.substring(0, salaryIdx).trim();
                                                salary = firstLine.substring(salaryIdx);
                                            } else {
                                                jobName = firstLine;
                                            }
                                        }
                                        if (!area) area = findLocation(lines);
                                        if (!company) {
                                            var excludeArr = [jobName];
                                            company = findCompanyFromEnd(lines, excludeArr);
                                        }
                                    } else {
                                        // PUA不在第一行：先提取PUA行作为薪资
                                        if (!salary && puaLineIdx >= 0) {
                                            salary = lines[puaLineIdx];
                                        }
                                        // 处理不同的字段缺失情况
                                        if (!jobName && !company) {
                                            if (isLocationLine(firstLine)) {
                                                area = firstLine;
                                                if (lines.length >= 2) company = lines[1];
                                            } else {
                                                jobName = firstLine;
                                            }
                                        } else if (!company && jobName) {
                                            if (!area) area = findLocation(lines);
                                            if (!company) {
                                                var excludeArr2 = [jobName];
                                                company = findCompanyFromEnd(lines, excludeArr2);
                                            }
                                        } else if (!jobName && company) {
                                            if (!isLocationLine(firstLine) && firstLine.length > 1) {
                                                jobName = firstLine;
                                            } else if (lines.length >= 2) {
                                                for (var i = 1; i < lines.length; i++) {
                                                    if (i === puaLineIdx) continue;
                                                    if (!isLocationLine(lines[i]) && lines[i].length > 1) {
                                                        jobName = lines[i]; break;
                                                    }
                                                }
                                            }
                                        } else {
                                            // jobName和company都有，可能还缺area
                                            if (!area) area = findLocation(lines);
                                        }
                                    }
                                }
                            }

                            if (jobName) {
                                results.push({
                                    jobName: jobName,
                                    companyName: company,
                                    salary: salary,
                                    location: area,
                                    salaryFont: salaryEl ? window.getComputedStyle(salaryEl).font : ''
                                });
                            }
                        } catch(e) {}
                    }
                    return results;
                })()
            """)

            # 合并同一个岗位的拆分数据
            if cards_data:
                logger.info(f"原始卡片数据: {len(cards_data)} 条, 第一条示例: {cards_data[0]}")
                
            merged = {}
            seen_keys = set()
            # 先收集所有有 location 的卡片，建立 location→companyName 的映射
            loc_company_map = {}
            for item in cards_data:
                loc = item.get("location", "").strip()
                cn = item.get("companyName", "").strip()
                if loc and cn:
                    loc_company_map[loc] = cn
            for idx, item in enumerate(cards_data):
                loc = item.get("location", "").strip()
                jn = item.get("jobName", "").strip()
                cn = item.get("companyName", "").strip()
                sr = item.get("salary", "").strip()
                sf = item.get("salaryFont", "")
                # 构建合并key：有location用location，否则尝试匹配已存在的company
                if loc:
                    key = loc
                elif cn and cn in loc_company_map.values():
                    # 通过company名反向查找location
                    rev_loc = None
                    for lk, lc in loc_company_map.items():
                        if lc == cn:
                            rev_loc = lk
                            break
                    key = rev_loc or jn
                else:
                    key = jn
                if not key:
                    continue
                if key not in merged:
                    merged[key] = {"jobName": "", "companyName": "", "salary": "", "salaryFont": "", "location": loc, "hasSalary": False}
                # 优先使用有薪资的卡片中的岗位名
                if jn:
                    has_salary = bool(sr)
                    if not merged[key]["jobName"] or (has_salary and not merged[key]["hasSalary"]):
                        merged[key]["jobName"] = jn
                        merged[key]["hasSalary"] = has_salary
                if cn and not merged[key]["companyName"]:
                    merged[key]["companyName"] = cn
                if sr and not merged[key]["salary"]:
                    merged[key]["salary"] = sr
                    merged[key]["salaryFont"] = sf

            for key, m in merged.items():
                job_name = m["jobName"]
                if not job_name:
                    continue
                # 过滤：公司信息卡（无薪资无地点，公司名被当作岗位名）
                if not m["salary"] and not m["location"]:
                    continue
                # 过滤：公司名与岗位名相同的无效条目
                company_name = m["companyName"]
                if company_name and job_name == company_name and not m["salary"]:
                    continue
                dup_key = f"{job_name}|{company_name}"
                if dup_key in seen_keys:
                    continue
                seen_keys.add(dup_key)

                job = JobItem(platform=self.platform)
                job.job_name = job_name
                job.company_name = company_name
                salary_raw = m["salary"]
                if salary_raw:
                    job.salary = await self._decode_salary_on_page(page, salary_raw, m["salaryFont"])
                job.location = m["location"]
                jobs.append(job)

            logger.info(f"页面DOM提取完成: {len(jobs)} 个岗位（合并去重后）")
        except Exception as e:
            logger.error(f"DOM提取失败: {e}")
        return jobs

    async def _decode_salary_on_page(self, page, salary_text: str, font_hint: str = "") -> str:
        """通过解析BOSS自定义字体文件cmap表解码PUA薪资"""
        if not salary_text:
            return ""
        
        # 检查是否有PUA字符
        has_pua = False
        for ch in salary_text:
            if 0xE000 <= ord(ch) <= 0xF8FF:
                has_pua = True
                break
        if not has_pua:
            return salary_text
        
        # 第一步：尝试从页面获取并解析字体文件
        try:
            mapping = await self._get_font_mapping_from_page(page)
            if mapping:
                result = ''
                for ch in salary_text:
                    cp = ord(ch)
                    if cp in mapping:
                        result += mapping[cp]
                    else:
                        result += ch
                # 验证解码结果是否合理（应包含数字）
                has_digit = False
                for rc in result:
                    if rc.isdigit():
                        has_digit = True
                        break
                if has_digit:
                    logger.debug(f"字体cmap解码成功: {salary_text} -> {result}")
                    return result
                logger.debug(f"字体cmap解码结果不合理，回退")
        except Exception as e:
            logger.debug(f"字体文件解析异常: {e}")
        
        # 第二步：回退到PUA偏移映射猜测
        # BOSS直聘常用0xE030+i映射到数字i，先尝试这个模式
        try:
            result = ''
            for ch in salary_text:
                cp = ord(ch)
                if 0xE030 <= cp <= 0xE039:
                    result += str(cp - 0xE030)
                elif 0xE000 <= cp <= 0xF8FF:
                    # 尝试其他常见偏移
                    for offset in [0xE000, 0xE020, 0xE040, 0xE0F0]:
                        if offset <= cp <= offset + 9:
                            result += str(cp - offset)
                            break
                    else:
                        result += ch
                else:
                    result += ch
            # 验证是否包含数字
            has_digit = False
            for rc in result:
                if rc.isdigit():
                    has_digit = True
                    break
            if has_digit:
                logger.debug(f"PUA偏移映射解码: {salary_text} -> {result}")
                return result
        except Exception as e:
            logger.debug(f"PUA偏移映射异常: {e}")
        
        # 最终回退：返回原始文本
        logger.debug(f"薪资解码失败，保留原始文本")
        return salary_text
    
    async def _get_font_mapping_from_page(self, page) -> Optional[dict]:
        """从页面提取BOSS自定义字体文件并解析cmap表，返回PUA codepoint→字符的映射"""
        try:
            # 在页面中查找@font-face规则，获取字体URL
            font_info = await page.evaluate("""
                (function() {
                    // 查找包含数字的@font-face字体
                    var fontSrc = null;
                    var fontFamily = null;
                    try {
                        for (var si = 0; si < document.styleSheets.length; si++) {
                            try {
                                var rules = document.styleSheets[si].cssRules || document.styleSheets[si].rules;
                                if (!rules) continue;
                                for (var ri = 0; ri < rules.length; ri++) {
                                    try {
                                        var rule = rules[ri];
                                        var isFontFace = (rule.type === 5) || 
                                            (rule.constructor && rule.constructor.name === 'CSSFontFaceRule');
                                        if (!isFontFace) continue;
                                        var src = rule.style && rule.style.src;
                                        if (src && (src.indexOf('.woff') >= 0 || src.indexOf('.ttf') >= 0)) {
                                            fontSrc = src;
                                            fontFamily = (rule.style && rule.style.fontFamily) || '';
                                            break;
                                        }
                                    } catch(e2) {}
                                }
                            } catch(e1) {}
                            if (fontSrc) break;
                        }
                    } catch(e) {}
                    
                    if (!fontSrc) return null;
                    
                    // 提取URL
                    var matches = fontSrc.match(/url\\(\\s*['"]?([^'")\\s]+)['"]?\\s*\\)/i);
                    if (!matches || !matches[1]) return null;
                    var url = matches[1];
                    
                    // 处理协议相对URL
                    if (url.indexOf('//') === 0) url = 'https:' + url;
                    
                    return {url: url, family: fontFamily};
                })()
            """)
            
            if not font_info or not font_info.get('url'):
                logger.debug("页面未找到@font-face规则")
                return None
            
            font_url = font_info['url']
            logger.debug(f"找到字体文件: {font_url}")
            
            # 尝试通过页面fetch获取字体文件（携带页面cookie，绕过跨域）
            font_b64 = await page.evaluate("""
                async (params) => {
                    try {
                        var resp = await fetch(params.url, {credentials: 'include'});
                        if (!resp.ok) return null;
                        var blob = await resp.blob();
                        // 转为base64
                        var reader = new FileReader();
                        return await new Promise(function(resolve, reject) {
                            reader.onloadend = function() { resolve(reader.result); };
                            reader.onerror = function() { resolve(null); };
                            reader.readAsDataURL(blob);
                        });
                    } catch(e) {
                        return null;
                    }
                }
            """, {"url": font_url})
            
            if not font_b64:
                logger.debug("无法通过fetch获取字体文件")
                return None
            
            import base64
            if ',' in font_b64:
                font_b64 = font_b64.split(',', 1)[1]
            
            font_bytes = base64.b64decode(font_b64)
            
            # 用fontTools解析cmap表
            from fontTools.ttLib import TTFont
            import io
            font = TTFont(io.BytesIO(font_bytes))
            cmap = font.getBestCmap()
            
            logger.debug(f"字体cmap表: {len(cmap)} 个映射")
            
            # 构建PUA→字符映射
            mapping = {}
            for cp, glyph_name in cmap.items():
                if 0xE000 <= cp <= 0xF8FF:
                    # 尝试从glyph name推断（如 uni0030、zero、one等）
                    glyph_name_lower = glyph_name.lower()
                    # 常见命名模式: uni0030 → '0', zero → '0'
                    if glyph_name_lower.startswith('uni') and len(glyph_name) == 7:
                        hex_part = glyph_name[3:]  # 取出'0030'
                        try:
                            mapped_cp = int(hex_part, 16)
                            if 0x30 <= mapped_cp <= 0x39:
                                mapping[cp] = chr(mapped_cp)
                                continue
                        except ValueError:
                            pass
                    # 数字英文名
                    digit_names = {'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
                                   'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9'}
                    if glyph_name_lower in digit_names:
                        mapping[cp] = digit_names[glyph_name_lower]
                        continue
                    # 直接用字符名里的数字后缀（如 gid1→1）
                    num_match = re.search(r'\d+$', glyph_name)
                    if num_match:
                        num_str = num_match.group()
                        if len(num_str) == 1 and '0' <= num_str <= '9':
                            mapping[cp] = num_str
                            continue
                    # 如果glyph名如 '1'、'2' 直接是数字
                    if len(glyph_name) == 1 and '0' <= glyph_name <= '9':
                        mapping[cp] = glyph_name
                        continue
                    # 保留未知映射
                    if chr(cp) not in mapping:
                        mapping[cp] = glyph_name
            
            font.close()
            
            if mapping:
                logger.debug(f"字体解析完成，PUA映射: {len(mapping)} 条")
                sample = {f'U+{cp:04X}': mapping[cp] for cp in sorted(mapping.keys())[:5]}
                logger.debug(f"映射样例: {sample}")
            return mapping
            
        except Exception as e:
            logger.error(f"字体解析失败: {e}")
            return None

    async def _search_via_inpage_api(self, page, keyword: str, city_code: str, page_num: int = 1, page_size: int = 100) -> Optional[dict]:
        """在已加载的BOSS页面上下文中直接调用API获取岗位数据，绕过页面导航级安全验证
        page_num: 页码，从1开始
        page_size: 每页条数，最大100
        """
        try:
            # 使用 fetch 从页面上下文调用 BOSS API（携带已有 Cookie/会话）
            result = await page.evaluate("""
                async (params) => {
                    const searchParams = new URLSearchParams({
                        query: params.keyword,
                        city: params.cityCode,
                        page: String(params.page),
                        pageSize: String(params.pageSize)
                    });
                    const url = 'https://www.zhipin.com/wapi/zpgeek/search/joblist.json?' + searchParams.toString();
                    try {
                        const resp = await fetch(url, {
                            credentials: 'include',
                            headers: {
                                'Accept': 'application/json, text/plain, */*',
                                'Referer': 'https://www.zhipin.com/web/geek/job',
                            }
                        });
                        const data = await resp.json();
                        return data;
                    } catch(e) {
                        return {error: e.toString()};
                    }
                }
            """, {"keyword": keyword, "cityCode": city_code, "page": page_num, "pageSize": page_size})

            if result and result.get("code") == 0:
                zp_data = result.get("zpData", {})
                job_list = zp_data.get("jobList", [])
                if job_list:
                    total = zp_data.get("total", 0) or zp_data.get("totalCount", 0) or len(job_list)
                    logger.info(f"In-page API 第{page_num}页调用成功，获取到 {len(job_list)} 个岗位，总数约 {total}")
                    return zp_data
                else:
                    logger.warning(f"In-page API 第{page_num}页返回空岗位列表")
                    return None
            elif result and result.get("code") == 32:
                logger.error(f"In-page API 第{page_num}页: 账户被封禁 (code=32) - {result.get('message', '')}")
                return None
            elif result and result.get("code") == 36:
                logger.error(f"In-page API 第{page_num}页: 触发安全验证 (code=36) - {result.get('message', '')}")
                return None
            else:
                logger.warning(f"In-page API 第{page_num}页调用未返回数据: code={result.get('code') if result else 'None'}, msg={result.get('message','') if result else ''}")
                return None
        except Exception as e:
            logger.error(f"In-page API 第{page_num}页调用失败: {e}")
            return None

    async def _search_all_via_api(self, page_obj, keyword: str, city_code: str) -> List[JobItem]:
        """通过In-page API获取所有页面岗位数据（顺序请求+随机间隔，防封禁）"""
        all_jobs = []
        
        # 先模拟人类行为，降低 API 调用被检测的风险
        await self._simulate_human_activity(page_obj, duration_sec=random.uniform(2.0, 4.0))
        
        # 获取第1页，了解总数
        await page_obj.wait_for_timeout(random.randint(800, 1500))  # 随机等待
        zp_data = await self._search_via_inpage_api(page_obj, keyword, city_code, page_num=1, page_size=100)
        if not zp_data:
            return all_jobs
        
        # 解析第1页
        page1_jobs = self._parse_job_list(zp_data.get("jobList", []))
        all_jobs.extend(page1_jobs)
        
        # 获取总岗位数，计算总页数
        total = zp_data.get("total", 0) or zp_data.get("totalCount", 0) or len(page1_jobs)
        page_size = 100
        total_pages = (total + page_size - 1) // page_size
        logger.info(f"岗位总数: {total}, 每页{page_size}条, 共{total_pages}页")
        
        # 如果只有1页，直接返回
        if total_pages <= 1:
            return all_jobs
        
        # 顺序获取后续页面，每页之间有随机间隔（防止并发被风控检测）
        max_pages = min(total_pages, 10)  # 最多10页，减少请求量
        for p in range(2, max_pages + 1):
            # 随机间隔 1.5~4 秒，模拟人类翻页行为
            delay = random.uniform(1.5, 4.0)
            logger.info(f"API第{p}/{max_pages}页，等待 {delay:.1f}s ...")
            await page_obj.wait_for_timeout(int(delay * 1000))
            
            # 偶尔模拟一下滚动（模拟浏览行为）
            if random.random() < 0.4:
                await self._human_scroll(page_obj, steps=random.randint(1, 2))
            
            result = await self._search_via_inpage_api(page_obj, keyword, city_code, page_num=p, page_size=page_size)
            if result and result.get("jobList"):
                jobs = self._parse_job_list(result.get("jobList", []))
                all_jobs.extend(jobs)
                logger.info(f"API第{p}页获取 {len(jobs)} 个岗位 (累计 {len(all_jobs)})")
            else:
                logger.warning(f"API第{p}页无数据，停止翻页")
                break  # 连续无数据则停止
        
        logger.info(f"API多页获取完成，共 {len(all_jobs)} 个岗位")
        return all_jobs

    async def _scrape_all_pages_dom(self, page_obj) -> List[JobItem]:
        """通过翻页从DOM提取所有页面岗位数据（API方式的回退方案）"""
        all_jobs = []
        max_pages = 15  # 最多翻15页
        
        for page_idx in range(max_pages):
            # 等待页面加载
            await page_obj.wait_for_timeout(2000)
            await self._human_scroll(page_obj, 3)
            
            # 提取当前页
            logger.info(f"DOM翻页提取第{page_idx + 1}页...")
            page_jobs = await self._extract_jobs_from_page(page_obj)
            if not page_jobs:
                page_jobs = await self._extract_jobs_by_text(page_obj)
            
            if page_jobs:
                # 去重合并
                existing_keys = set(f"{j.job_name}|{j.company_name}" for j in all_jobs)
                new_jobs = [j for j in page_jobs if f"{j.job_name}|{j.company_name}" not in existing_keys]
                all_jobs.extend(new_jobs)
                logger.info(f"DOM第{page_idx + 1}页提取 {len(page_jobs)} 个岗位，新增 {len(new_jobs)} 个")
            
            # 尝试点击"下一页"
            try:
                next_btn = await page_obj.query_selector('[class*="next"], [class*="pagination"] button:last-child, a:has-text("下一页")')
                if not next_btn:
                    logger.info("未找到下一页按钮，翻页结束")
                    break
                
                is_disabled = await next_btn.get_attribute("disabled") or await next_btn.get_attribute("aria-disabled")
                if is_disabled:
                    logger.info("下一页按钮已禁用，翻页结束")
                    break
                
                await next_btn.click()
                logger.info(f"点击下一页 -> 第{page_idx + 2}页")
                await page_obj.wait_for_timeout(3000)
            except Exception as e:
                logger.info(f"翻页结束: {e}")
                break
        
        return all_jobs

    async def _search_with_cookies_only(self, keyword: str, city: str) -> List[JobItem]:
        """仅使用Cookie文件进行搜索（无需持久化Profile），通过注入Cookie+In-page API方式"""
        logger.info(f"[Cookie模式] 搜索关键词={keyword}, 城市={city}")
        jobs = []
        city_code = self.city_codes.get(city, "")

        try:
            async with async_playwright() as p:
                # 启动普通无头浏览器
                browser = await p.chromium.launch(
                    headless=True,
                    args=self._get_browser_launch_args(),
                )
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                )

                # 注入Cookie
                with open(self.cookie_file, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                valid_cookies = [
                    c for c in cookies if "name" in c and "value" in c
                ]
                await context.add_cookies(valid_cookies)
                logger.info(f"[Cookie模式] 已注入 {len(valid_cookies)} 个Cookie")

                page = await context.new_page()

                # 先访问BOSS首页以激活Cookie会话
                await page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)

                # 检测是否触发了安全验证或账户封禁
                if self._is_verify_page(page.url):
                    if "code=32" in page.url or "403.html" in page.url:
                        logger.error("[Cookie模式] BOSS直聘账户已被封禁 (code=32)！")
                    else:
                        logger.warning("[Cookie模式] 触发安全验证，Cookie可能已过期，请重新登录")
                    await browser.close()
                    return jobs

                # 使用In-page API获取数据
                try:
                    all_jobs = await self._search_all_via_api(page, keyword, city_code)
                    jobs = all_jobs
                except Exception as e:
                    logger.error(f"[Cookie模式] API搜索失败: {e}")

                await browser.close()

        except Exception as e:
            logger.error("[Cookie模式] 搜索异常: type={}, msg={}", type(e).__name__, str(e))
            logger.error("[Cookie模式] 异常堆栈:\n{}", traceback.format_exc())

        logger.info(f"[Cookie模式] 搜索完成，获取到 {len(jobs)} 个岗位")
        return jobs

    def _is_verify_page(self, url: str) -> bool:
        """判断URL是否为BOSS安全验证页面或账户封禁页面"""
        verify_keywords = ["security_check", "captcha", "verify", "code=36", "code=32", "403.html"]
        return any(k in url for k in verify_keywords)

    async def search(self, keyword: str, city: str = "", page_num: int = 1) -> List[JobItem]:
        """搜索岗位 - 支持持久化Profile模式和Cookie注入模式"""
        logger.info(f"BOSS直聘搜索: {keyword}, 城市: {city}, 页码: {page_num}")

        # 检查可用的认证方式
        has_profile = os.path.isdir(self.profile_dir) and os.listdir(self.profile_dir)
        has_cookies = self.has_cookies()

        if not has_profile and not has_cookies:
            logger.warning("BOSS直聘未登录，请先点击「BOSS直聘登录」按钮完成登录")
            return []

        # Cookie模式：无持久化Profile但有Cookie文件时使用
        if not has_profile and has_cookies:
            logger.info("使用Cookie注入模式搜索（无持久化Profile）")
            return await self._search_with_cookies_only(keyword, city)
        
        # 以下为持久化Profile模式（原有逻辑）
        # 构建搜索URL（直接使用目标城市代码，触发安全验证后由用户手动完成）
        target_city_code = self.city_codes.get(city, "")
        search_params = {"query": keyword}
        if target_city_code:
            search_params["city"] = target_city_code
        search_url = f"{self.search_url}?{urlencode(search_params)}"
        logger.info(f"目标搜索URL: {search_url}")

        jobs = []

        try:
            async with async_playwright() as p:
                # 先使用无头模式尝试搜索（不弹出浏览器窗口）
                headless = True
                context = None
                page_obj = None
                
                try:
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir=self.profile_dir,
                        channel="chrome",
                        headless=headless,
                        args=self._get_browser_launch_args(),
                        viewport={"width": 1920, "height": 1080},
                        locale="zh-CN",
                        timezone_id="Asia/Shanghai",
                        permissions=["geolocation", "notifications"],
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/126.0.0.0 Safari/537.36"
                        ),
                    )
                    
                    # 注入反检测隐身脚本
                    await context.add_init_script(script=self._get_stealth_script())

                    page_obj = context.pages[0] if context.pages else await context.new_page()

                    # 导航到目标搜索页
                    logger.info(f"正在打开BOSS直聘搜索页...")
                    await page_obj.goto(search_url, wait_until="domcontentloaded", timeout=30000)

                    # 等待页面加载（安全验证通常在3-8秒后触发）
                    await page_obj.wait_for_timeout(5000)

                    # 检测安全验证/账户封禁
                    if self._is_verify_page(page_obj.url):
                        # 区分账户封禁(code=32)和普通安全验证
                        if "code=32" in page_obj.url or "403.html" in page_obj.url:
                            logger.error("=" * 60)
                            logger.error("BOSS直聘账户已被封禁 (code=32)！")
                            logger.error("您的账户因检测到自动化行为被暂时禁止使用。")
                            logger.error("请等待24小时后重试，或通过BOSS直聘App/网页手动登录解除限制。")
                            logger.error("=" * 60)
                            await context.close()
                            return []  # 账户被封禁，不切换到可见模式
                        
                        logger.warning("无头模式触发安全验证，切换到可见模式让用户完成验证...")
                        # 关闭当前无头上下文，重新以可见模式打开
                        await context.close()
                        context = None
                        raise Exception("需要安全验证，切换到可见模式")
                    
                    # 页面已正常加载，直接获取数据
                    current_url = page_obj.url
                    logger.info(f"当前页面URL: {current_url}")
                    logger.info(f"页面标题: {await page_obj.title()}")

                    # 优先使用 In-page API 获取所有页数据
                    logger.info("尝试通过 In-page API 获取岗位数据...")
                    api_jobs = await self._search_all_via_api(
                        page_obj, keyword, target_city_code
                    )
                    if api_jobs:
                        jobs = api_jobs
                        logger.info(f"API多页获取完成: {len(jobs)} 个岗位")
                    else:
                        # 从页面DOM提取数据并翻页
                        logger.info("API方式未获取到数据，转为DOM翻页提取...")
                        jobs = await self._scrape_all_pages_dom(page_obj)
                        logger.info(f"DOM翻页提取完成: {len(jobs)} 个岗位")

                    logger.info(f"BOSS直聘搜索完成: {len(jobs)} 个岗位")
                    await context.close()
                    
                    # 无头模式搜到 0 个岗位（Cookie可能过期），切换到可见模式重试
                    if len(jobs) == 0:
                        logger.warning("无头模式未获取到岗位数据，切换到可见模式（Cookie可能已过期）")
                        headless = False
                    else:
                        return jobs
                    
                except Exception as e:
                    if "需要安全验证" in str(e):
                        # 安全验证需要用户手动完成，使用可见模式重新打开
                        logger.info("使用可见浏览器窗口让用户完成安全验证...")
                        headless = False
                    else:
                        # 其他异常，关闭上下文并重新尝试可见模式
                        if context:
                            try:
                                await context.close()
                            except:
                                pass
                        logger.warning(f"无头模式搜索失败: {e}，切换到可见模式重试...")
                        headless = False

                # 可见模式：用户需要手动完成安全验证
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=self.profile_dir,
                    channel="chrome",
                    headless=headless,
                    args=self._get_browser_launch_args(),
                    viewport={"width": 1920, "height": 1080},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    permissions=["geolocation", "notifications"],
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                )

                # 注入反检测隐身脚本
                await context.add_init_script(script=self._get_stealth_script())

                page_obj = context.pages[0] if context.pages else await context.new_page()

                # 导航到目标搜索页
                logger.info(f"正在打开BOSS直聘搜索页（可见模式）...")
                await page_obj.goto(search_url, wait_until="domcontentloaded", timeout=30000)

                # 等待页面加载
                await page_obj.wait_for_timeout(5000)

                # 检测安全验证/账户封禁（循环检测，最多等3分钟让用户手动完成）
                verify_waited = False
                for wait_sec in range(180):
                    current_url = page_obj.url
                    if not self._is_verify_page(current_url):
                        if verify_waited:
                            logger.info("安全验证已通过!")
                            await page_obj.wait_for_timeout(3000)
                        break
                    else:
                        # 区分账户封禁(code=32)和普通安全验证
                        if "code=32" in current_url or "403.html" in current_url:
                            logger.error("=" * 60)
                            logger.error("BOSS直聘账户已被封禁 (code=32)！")
                            logger.error("您的账户因检测到自动化行为被暂时禁止使用。")
                            logger.error("请等待24小时后重试，或通过BOSS直聘App/网页手动登录解除限制。")
                            logger.error("=" * 60)
                            await context.close()
                            return jobs  # 账户被封禁，直接返回
                        
                        if not verify_waited:
                            verify_waited = True
                            logger.warning("=" * 60)
                            logger.warning("BOSS直聘触发了安全验证!")
                            logger.warning("请在弹出的浏览器窗口中手动完成验证（拖动拼图/滑块）")
                            logger.warning("验证完成后不要关闭浏览器，等待数据采集完成!")
                            logger.warning("将在3分钟后超时...")
                            logger.warning("=" * 60)
                    await page_obj.wait_for_timeout(1000)

                if verify_waited and self._is_verify_page(page_obj.url):
                    logger.error("安全验证超时，用户未完成验证")
                    await context.close()
                    return jobs

                # 页面已正常加载，获取数据
                current_url = page_obj.url
                logger.info(f"当前页面URL: {current_url}")
                logger.info(f"页面标题: {await page_obj.title()}")

                # 优先使用 In-page API 获取所有页数据
                logger.info("尝试通过 In-page API 获取岗位数据...")
                api_jobs = await self._search_all_via_api(
                    page_obj, keyword, target_city_code
                )
                if api_jobs:
                    jobs = api_jobs
                    logger.info(f"API多页获取完成: {len(jobs)} 个岗位")
                else:
                    # 从页面DOM提取数据并翻页
                    logger.info("API方式未获取到数据，转为DOM翻页提取...")
                    jobs = await self._scrape_all_pages_dom(page_obj)
                    logger.info(f"DOM翻页提取完成: {len(jobs)} 个岗位")

                logger.info(f"BOSS直聘搜索完成: {len(jobs)} 个岗位")
                await context.close()

        except Exception as e:
            logger.error(f"BOSS直聘搜索失败: {e}")

        return jobs

    async def _extract_jobs_by_text(self, page) -> List[JobItem]:
        """纯文本行解析 - 不依赖CSS类名，从页面可见文本中提取岗位数据"""
        jobs = []
        try:
            text_data = await page.evaluate("""
                (function() {
                    // 获取所有可见文本块，保留换行结构
                    var body = document.body;
                    if (!body) return '';
                    // 用 innerText 获取渲染后的可见文本（保留换行）
                    return body.innerText || body.textContent || '';
                })()
            """)
            if not text_data:
                return jobs

            lines = [l.strip() for l in text_data.split('\n') if l.strip()]
            logger.info(f"页面可见文本共 {len(lines)} 行")

            # 尝试按卡片区域分块：BOSS页面中岗位卡片之间通常有空行分隔
            # 或者按标记分块：找到 "推荐"、"最新" 等标题后的内容
            # 策略：扫描包含薪资关键字的行，向前取岗位名，向后取公司名/地点
            from .base import JobItem

            # 薪资正则（含PUA字符范围）
            salary_pattern = re.compile(r'[\u4e00-\u9fff\w\d\-~·]*[kK\u4e07\u85aa]', re.UNICODE)

            for i, line in enumerate(lines):
                # 查找包含PUA字符的行（BOSS用自定义字体编码薪资）
                has_pua = any(0xE000 <= ord(ch) <= 0xF8FF for ch in line)
                if not has_pua:
                    continue
                
                # 找到薪资行，向前取岗位名（一般隔1-2行）
                job_name = ''
                company_name = ''
                location = ''
                salary = line

                # 向前找前一行或两行（跳过空行/短行）
                for offset in range(1, 4):
                    idx = i - offset
                    if idx < 0:
                        break
                    prev = lines[idx]
                    if len(prev) < 2:
                        continue
                    # 判断是否是城市名（地点行）
                    known_cities = ['上海', '北京', '广州', '深圳', '杭州', '成都', '南京',
                                    '武汉', '苏州', '长沙', '重庆', '天津', '西安', '郑州',
                                    '合肥', '宁波', '青岛', '厦门', '大连', '沈阳', '济南',
                                    '福州', '哈尔滨', '长春', '珠海', '佛山', '东莞', '无锡',
                                    '常州', '嘉兴', '绍兴', '南通', '徐州', '昆明', '贵阳',
                                    '南宁', '海口', '太原', '兰州', '三亚']
                    is_city = any(prev.startswith(c) or prev == c for c in known_cities)
                    # 判断是否是公司名（包含有限公司/股份/集团等）
                    is_company = any(kw in prev for kw in ['有限公司', '股份', '集团', '有限责任'])
                    # 判断是否是经验/学历行
                    is_meta = any(kw in prev for kw in ['经验', '学历', '大专', '本科', '硕士', '博士', '届'])

                    if is_city and not location:
                        location = prev
                    elif is_company and not company_name:
                        company_name = prev
                    elif is_meta:
                        continue
                    elif not job_name and not is_city and not is_company:
                        # 可能是岗位名（较长且有中文）
                        if len(prev) >= 2 and not any(c.isdigit() for c in prev):
                            job_name = prev

                if job_name:
                    # 去重
                    dup_key = f"{job_name}|{company_name}"
                    if not any(j.job_name == job_name and j.company_name == company_name for j in jobs):
                        job = JobItem(platform=self.platform)
                        job.job_name = job_name
                        job.company_name = company_name
                        job.salary = salary
                        job.location = location
                        jobs.append(job)

            logger.info(f"文本行解析提取: {len(jobs)} 个岗位")
        except Exception as e:
            logger.error(f"文本行解析失败: {e}")
        return jobs

    async def send_greeting(self, job_id: str, greeting_message: str = "") -> Dict:
        """向BOSS直聘HR发送打招呼消息（增强反检测版本）"""
        logger.info("[BOSS直聘][投递] === 开始投递 ===")
        logger.info("[BOSS直聘][投递] job_id={}, message_len={}", job_id, len(greeting_message))
        logger.debug("[BOSS直聘][投递] 消息内容: {}", greeting_message[:100] if greeting_message else "(默认)")

        if not job_id:
            logger.error("[BOSS直聘][投递] 岗位ID为空，终止")
            return {"success": False, "message": "岗位ID为空"}

        # 检查可用认证方式
        has_profile = os.path.isdir(self.profile_dir) and os.path.exists(
            os.path.join(self.profile_dir, "Default", "Preferences"))
        has_cookies = self.has_cookies()

        if not has_profile and not has_cookies:
            logger.error("[BOSS直聘][投递] 无持久化Profile和Cookie，无法投递")
            return {"success": False, "message": "未登录BOSS直聘，请先登录"}

        try:
            if has_profile:
                # 模式A: 持久化Profile（最隐蔽，使用真实Chrome用户数据）
                logger.info("[BOSS直聘][投递] 使用持久化Profile模式（高隐蔽性）")
                return await self._send_greeting_with_profile(job_id, greeting_message)
            else:
                # 模式B: Cookie注入模式（增强反检测）
                logger.info("[BOSS直聘][投递] 使用Cookie注入模式（增强反检测）")
                return await self._send_greeting_with_cookies(job_id, greeting_message)

        except Exception as e:
            logger.error("[BOSS直聘][投递] === 投递异常 ===: type={}, msg={}", type(e).__name__, str(e))
            logger.error("[BOSS直聘][投递] 堆栈: {}", traceback.format_exc())
            return {"success": False, "message": f"发送异常: {str(e)}"}

    async def _send_greeting_with_profile(self, job_id: str, greeting_message: str) -> Dict:
        """使用持久化Profile模式发送打招呼消息（最隐蔽）"""
        t0 = time.time()
        use_visible = getattr(self, '_use_visible_browser', True)
        logger.info("[BOSS直聘][投递-Profile] 浏览器模式: {}", "可见窗口" if use_visible else "无头模式")
        
        try:
            async with async_playwright() as p:
                user_data_dir = self.profile_dir
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    channel="chrome",
                    headless=not use_visible,
                    args=self._get_browser_launch_args(),
                    viewport={"width": 1920, "height": 1080},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
                
                # 注入反检测JS
                await context.add_init_script(script=self._get_stealth_script())
                
                page = context.pages[0] if context.pages else await context.new_page()
                
                # 模拟人类：先访问首页
                logger.info("[BOSS直聘][投递-Profile] 访问首页（模拟真实用户）...")
                await page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=30000)
                await self._human_delay(page, 1.5, 3.0, "浏览首页")
                
                # 检查验证
                if self._is_verify_page(page.url):
                    logger.warning("[BOSS直聘][投递-Profile] 触发安全验证，请手动处理")
                    await context.close()
                    return {"success": False, "message": "BOSS直聘触发安全验证，请手动处理后重试"}
                
                # 模拟人类：随机滚动页面
                await self._simulate_scroll(page)
                await self._human_delay(page, 0.5, 1.5, "滚动浏览")
                
                # 步骤1: 调用聊天启动API
                logger.info("[BOSS直聘][投递-Profile] 调用聊天启动API...")
                start_result = await page.evaluate("""
                    async (params) => {
                        const resp = await fetch('https://www.zhipin.com/wapi/zpgeek/chat/start.json', {
                            method: 'POST',
                            credentials: 'include',
                            headers: {
                                'Content-Type': 'application/json',
                                'Accept': 'application/json',
                                'Referer': 'https://www.zhipin.com/web/geek/job',
                            },
                            body: JSON.stringify({ jid: params.jobId })
                        });
                        const data = await resp.json();
                        return { status: resp.status, data: data };
                    }
                """, {"jobId": job_id})
                
                if start_result.get("error"):
                    await context.close()
                    return {"success": False, "message": f"聊天启动失败: {start_result['error']}"}
                
                data = start_result.get("data", {})
                resp_code = data.get("code")
                
                if resp_code is not None and resp_code != 0:
                    error_msg = data.get("message", "") or data.get("resmessage", "") or "未知错误"
                    logger.warning("[BOSS直聘][投递-Profile] 启动API返回: code={}, msg={}", resp_code, error_msg)
                    
                    # 检查是否被风控
                    if resp_code == 36 or "异常" in error_msg or "禁止" in error_msg:
                        await context.close()
                        return {"success": False, "message": f"BOSS直聘风控拦截: {error_msg}"}
                    elif resp_code != 0:
                        await context.close()
                        return {"success": False, "message": f"聊天启动失败: {error_msg}"}
                
                # 模拟人类延迟
                await self._human_delay(page, 2.0, 4.0, "等待聊天窗口加载")
                
                # 步骤2: 发送消息
                if greeting_message:
                    logger.info("[BOSS直聘][投递-Profile] 发送打招呼消息...")
                    send_result = await page.evaluate("""
                        async (params) => {
                            const resp = await fetch('https://www.zhipin.com/wapi/zpgeek/chat/send.json', {
                                method: 'POST',
                                credentials: 'include',
                                headers: {
                                    'Content-Type': 'application/json',
                                    'Accept': 'application/json',
                                    'Referer': 'https://www.zhipin.com/web/geek/chat',
                                },
                                body: JSON.stringify({
                                    jid: params.jobId,
                                    type: 'text',
                                    text: params.message
                                })
                            });
                            const data = await resp.json();
                            return { status: resp.status, data: data };
                        }
                    """, {"jobId": job_id, "message": greeting_message})
                    
                    if send_result.get("error"):
                        await context.close()
                        return {"success": False, "message": f"消息发送失败: {send_result['error']}"}
                    
                    send_data = send_result.get("data", {})
                    send_code = send_data.get("code")
                    
                    if send_code is not None and send_code != 0:
                        error_msg = send_data.get("message", "") or "未知错误"
                        logger.error("[BOSS直聘][投递-Profile] 消息发送失败: code={}, msg={}", send_code, error_msg)
                        await context.close()
                        return {"success": False, "message": f"消息发送失败: {error_msg}"}
                
                await self._human_delay(page, 1.0, 2.0, "等待发送完成")
                await context.close()
                
                elapsed = time.time() - t0
                logger.info("[BOSS直聘][投递-Profile] === 投递成功: job_id={}, 耗时={:.2f}s ===", job_id, elapsed)
                return {"success": True, "message": "打招呼发送成功", "job_id": job_id}
                
        except Exception as e:
            logger.error("[BOSS直聘][投递-Profile] 异常: {}", e)
            return {"success": False, "message": f"发送异常: {str(e)}"}

    async def _send_greeting_with_cookies(self, job_id: str, greeting_message: str) -> Dict:
        """使用Cookie注入模式发送打招呼消息（增强反检测）"""
        t0 = time.time()
        try:
            if not os.path.exists(self.cookie_file):
                return {"success": False, "message": "未找到BOSS Cookie文件，请先登录"}
            
            with open(self.cookie_file, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            valid_cookies = [c for c in cookies if "name" in c and "value" in c]
            
            if not valid_cookies:
                return {"success": False, "message": "Cookie文件无效，请重新登录"}
            
            async with async_playwright() as p:
                # 随机视口（不同分辨率）
                viewports = [
                    {"width": 1920, "height": 1080},
                    {"width": 1600, "height": 900},
                    {"width": 1440, "height": 900},
                ]
                vp = random.choice(viewports)
                
                browser = await p.chromium.launch(
                    headless=True,
                    args=self._get_browser_launch_args(),
                )
                context = await browser.new_context(
                    viewport=vp,
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    user_agent=random.choice([
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                    ]),
                )
                
                # 注入反检测JS
                await context.add_init_script(script=self._get_stealth_script())
                await context.add_cookies(valid_cookies)
                
                page = await context.new_page()
                
                # 模拟人类：先访问首页
                await page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=30000)
                await self._human_delay(page, 1.5, 3.0, "浏览首页")
                
                # 检查验证
                if self._is_verify_page(page.url):
                    logger.warning("[BOSS直聘][投递-Cookie] 触发安全验证，Cookie已过期")
                    await browser.close()
                    return {"success": False, "message": "BOSS Cookie已过期或被风控，请重新登录"}
                
                # 模拟滚动
                await self._simulate_scroll(page)
                await self._human_delay(page, 1.0, 2.0, "浏览页面")
                
                # 调用聊天启动API
                logger.info("[BOSS直聘][投递-Cookie] 调用聊天启动API...")
                start_result = await page.evaluate("""
                    async (params) => {
                        const resp = await fetch('https://www.zhipin.com/wapi/zpgeek/chat/start.json', {
                            method: 'POST',
                            credentials: 'include',
                            headers: {
                                'Content-Type': 'application/json',
                                'Accept': 'application/json',
                                'Referer': 'https://www.zhipin.com/web/geek/job',
                            },
                            body: JSON.stringify({ jid: params.jobId })
                        });
                        const data = await resp.json();
                        return { status: resp.status, data: data };
                    }
                """, {"jobId": job_id})
                
                if start_result.get("error"):
                    await browser.close()
                    return {"success": False, "message": f"聊天启动失败: {start_result['error']}"}
                
                data = start_result.get("data", {})
                resp_code = data.get("code")
                
                if resp_code is not None and resp_code != 0:
                    error_msg = data.get("message", "") or data.get("resmessage", "") or "未知错误"
                    if resp_code == 36 or "异常" in error_msg or "禁止" in error_msg:
                        await browser.close()
                        return {"success": False, "message": f"BOSS直聘风控拦截: {error_msg}"}
                    elif resp_code != 0:
                        await browser.close()
                        return {"success": False, "message": f"聊天启动失败: {error_msg}"}
                
                # 模拟人类延迟
                await self._human_delay(page, 2.0, 5.0, "等待加载")
                
                # 发送消息
                if greeting_message:
                    logger.info("[BOSS直聘][投递-Cookie] 发送打招呼消息...")
                    send_result = await page.evaluate("""
                        async (params) => {
                            const resp = await fetch('https://www.zhipin.com/wapi/zpgeek/chat/send.json', {
                                method: 'POST',
                                credentials: 'include',
                                headers: {
                                    'Content-Type': 'application/json',
                                    'Accept': 'application/json',
                                    'Referer': 'https://www.zhipin.com/web/geek/chat',
                                },
                                body: JSON.stringify({
                                    jid: params.jobId,
                                    type: 'text',
                                    text: params.message
                                })
                            });
                            const data = await resp.json();
                            return { status: resp.status, data: data };
                        }
                    """, {"jobId": job_id, "message": greeting_message})
                    
                    if send_result.get("error"):
                        await browser.close()
                        return {"success": False, "message": f"消息发送失败: {send_result['error']}"}
                    
                    send_data = send_result.get("data", {})
                    send_code = send_data.get("code")
                    
                    if send_code is not None and send_code != 0:
                        error_msg = send_data.get("message", "") or "未知错误"
                        logger.error("[BOSS直聘][投递-Cookie] 消息发送失败: code={}, msg={}", send_code, error_msg)
                        await browser.close()
                        return {"success": False, "message": f"消息发送失败: {error_msg}"}
                
                await self._human_delay(page, 1.0, 2.0, "等待完成")
                await browser.close()
                
                elapsed = time.time() - t0
                logger.info("[BOSS直聘][投递-Cookie] === 投递成功: job_id={}, 耗时={:.2f}s ===", job_id, elapsed)
                return {"success": True, "message": "打招呼发送成功", "job_id": job_id}
                
        except Exception as e:
            logger.error("[BOSS直聘][投递-Cookie] 异常: {}", e)
            return {"success": False, "message": f"发送异常: {str(e)}"}

    async def _human_delay(self, page, min_sec: float, max_sec: float, label: str = ""):
        """模拟人类操作的随机延迟 + 微小鼠标移动"""
        delay = min_sec + random.random() * (max_sec - min_sec)
        logger.debug("[BOSS直聘][人类模拟] {}: 延迟 {:.2f}s", label, delay)
        await page.wait_for_timeout(int(delay * 1000))
        
        # 偶尔模拟鼠标微小移动
        if random.random() < 0.3:
            try:
                x = random.randint(200, 800)
                y = random.randint(100, 500)
                await page.mouse.move(x, y, steps=random.randint(3, 8))
            except Exception:
                pass

    async def _simulate_scroll(self, page):
        """模拟人类滚动页面"""
        try:
            scroll_amount = random.randint(200, 600)
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await page.wait_for_timeout(random.randint(500, 1500))
            await page.evaluate(f"window.scrollBy(0, {scroll_amount // 2})")
            await page.wait_for_timeout(random.randint(300, 800))
        except Exception:
            pass

    def _parse_job_list(self, job_list: list) -> List[JobItem]:
        """解析BOSS直聘API返回的岗位列表"""
        jobs = []
        for item in job_list:
            try:
                job = JobItem(platform=self.platform)
                if isinstance(item, dict):
                    job_data = item
                elif isinstance(item, list) and len(item) > 1:
                    job_data = item[1] if isinstance(item[1], dict) else item[0]
                else:
                    continue

                job.job_name = (
                    job_data.get("jobName") or
                    job_data.get("name") or
                    job_data.get("job_name") or
                    ""
                )
                # 存储平台岗位ID，用于投递/沟通
                job.platform_job_id = (
                    job_data.get("encryptId") or
                    job_data.get("encryptJobId") or
                    job_data.get("securityId") or
                    job_data.get("jobId") or
                    ""
                )
                company = job_data.get("brandName") or job_data.get("company") or {}
                if isinstance(company, dict):
                    job.company_name = company.get("name") or company.get("companyName", "")
                else:
                    job.company_name = str(company) if company else ""
                job.salary = job_data.get("salaryDesc") or job_data.get("salary", "")
                job.location = (
                    job_data.get("cityName") or
                    job_data.get("areaDistrict") or
                    job_data.get("location", "")
                )
                job.job_url = f"{self.base_url}/web/geek/job/{job_data.get('jobId', '')}"
                jobs.append(job)
            except Exception as e:
                logger.warning(f"解析BOSS直聘API数据项失败: {e}")
                continue
        return jobs

    async def parse_job_detail(self, url: str) -> Optional[JobItem]:
        """解析岗位详情"""
        try:
            jobs = await self.search("", "", 1)
            for j in jobs:
                if j.job_url == url:
                    return j
            return None
        except Exception as e:
            logger.error(f"解析BOSS直聘详情失败: {e}")
            return None
