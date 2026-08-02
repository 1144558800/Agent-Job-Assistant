# -*- coding: utf-8 -*-
"""
桌面自动化控制器 - 模拟真人操作招聘平台
核心能力：截图 + OCR + AI 推理 + pyautogui 操作
用于深普招聘平台爬虫和自动投递
"""
import os
import json
import time
import base64
from pathlib import Path
from typing import Optional, Dict, Any, List
from loguru import logger

import config

# 截图保存目录
SCREENSHOT_DIR = config.BASE_DIR / "data" / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


class DesktopController:
    """桌面自动化控制器"""

    def __init__(self):
        self.screenshot_dir = SCREENSHOT_DIR

    def take_screenshot(self, name: str = "") -> Optional[str]:
        """截图并保存"""
        try:
            import pyautogui
            if not name:
                name = f"screenshot_{int(time.time())}"
            path = self.screenshot_dir / f"{name}.png"
            screenshot = pyautogui.screenshot()
            screenshot.save(str(path))
            logger.info("[Desktop] 截图已保存: {}", path)
            return str(path)
        except ImportError:
            logger.warning("[Desktop] pyautogui 未安装")
            return None
        except Exception as e:
            logger.error("[Desktop] 截图失败: {}", e)
            return None

    def screenshot_to_base64(self) -> Optional[str]:
        """截图并返回 base64 编码"""
        path = self.take_screenshot()
        if not path:
            return None
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.error("[Desktop] 截图转 base64 失败: {}", e)
            return None

    def ocr_screenshot(self, image_path: str = "") -> Optional[str]:
        """对截图进行 OCR 识别"""
        try:
            if not image_path:
                image_path = self.take_screenshot()
            if not image_path:
                return None

            try:
                import pytesseract
                from PIL import Image
                image = Image.open(image_path)
                text = pytesseract.image_to_string(image, lang="chi_sim+eng")
                logger.info("[Desktop] OCR 结果长度: {} 字符", len(text))
                return text
            except ImportError:
                logger.warning("[Desktop] pytesseract 未安装，恢复使用 AI Vision")
                return self._ai_ocr(image_path)
        except Exception as e:
            logger.error("[Desktop] OCR 失败: {}", e)
            return None

    def _ai_ocr(self, image_path: str) -> Optional[str]:
        """使用 AI Vision 识别截图中的文字"""
        try:
            with open(image_path, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("utf-8")

            from openai import OpenAI
            client = OpenAI(api_key=config.AI_API_KEY, base_url=config.AI_API_BASE)

            response = client.chat.completions.create(
                model=config.AI_MODEL,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请识别并提取这张截图中的所有文字内容。只返回文字，不要添加任何解释。"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
                    ]
                }],
                max_tokens=2000,
            )
            text = response.choices[0].message.content
            logger.info("[Desktop] AI OCR 结果长度: {} 字符", len(text) if text else 0)
            return text
        except Exception as e:
            logger.error("[Desktop] AI OCR 失败: {}", e)
            return None

    def analyze_screen(self, task_description: str) -> Optional[str]:
        """AI 分析当前屏幕内容"""
        image_b64 = self.screenshot_to_base64()
        if not image_b64:
            return None

        try:
            from openai import OpenAI
            client = OpenAI(api_key=config.AI_API_KEY, base_url=config.AI_API_BASE)

            response = client.chat.completions.create(
                model=config.AI_MODEL,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"请分析这张截图。任务：{task_description}"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
                    ]
                }],
                max_tokens=2000,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("[Desktop] AI 分析失败: {}", e)
            return None

    def click(self, x: int, y: int):
        """点击指定坐标"""
        try:
            import pyautogui
            pyautogui.click(x, y)
            logger.info("[Desktop] 点击: ({}, {})", x, y)
            time.sleep(0.5)
        except ImportError:
            logger.warning("[Desktop] pyautogui 未安装")

    def type_text(self, text: str, interval: float = 0.05):
        """模拟键盘输入"""
        try:
            import pyautogui
            pyautogui.write(text, interval=interval)
            logger.info("[Desktop] 输入文本: {}...", text[:30])
        except ImportError:
            logger.warning("[Desktop] pyautogui 未安装")

    def press_key(self, key: str):
        """按下按键"""
        try:
            import pyautogui
            pyautogui.press(key)
            logger.info("[Desktop] 按键: {}", key)
        except ImportError:
            logger.warning("[Desktop] pyautogui 未安装")

    def get_screen_size(self) -> tuple:
        """获取屏幕尺寸"""
        try:
            import pyautogui
            return pyautogui.size()
        except ImportError:
            return (1920, 1080)


# 全局单例
_desktop_controller = None


def get_desktop_controller() -> DesktopController:
    global _desktop_controller
    if _desktop_controller is None:
        _desktop_controller = DesktopController()
    return _desktop_controller


# ============================================================
# 深普公司招聘爬虫
# ============================================================

class JobSearchMatchPipeline:
    """深普招聘平台搜索匹配流水线"""

    def __init__(self):
        self.controller = get_desktop_controller()

    def search_deepseek_jobs(self) -> Optional[str]:
        """在桌面打开浏览器搜索 DeepSeek 招聘"""
        logger.info("[Pipeline] 搜索深普招聘")
        screenshot = self.controller.take_screenshot("deepseek_search_step1")

        try:
            import pyautogui
            # 打开浏览器
            pyautogui.hotkey("win", "r")
            time.sleep(0.5)
            self.controller.type_text("https://www.deepseek.com/")
            time.sleep(0.5)
            pyautogui.press("enter")
            time.sleep(3)
            screenshot = self.controller.take_screenshot("deepseek_search_step2")
        except ImportError:
            pass

        return self.controller.analyze_screen("这是深普公司的官网页面，请分析页面上是否有招聘/职位/加入我们等相关入口")

    def search_ai_company_jobs(self, company_name: str) -> Optional[str]:
        """搜索指定 AI 公司的招聘信息"""
        logger.info("[Pipeline] 搜索 {} 招聘", company_name)
        return self.controller.analyze_screen(f"请在浏览器中打开 {company_name} 的招聘页面，分析当前的职位信息")
