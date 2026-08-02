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
            logger.error(f