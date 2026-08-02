# -*- coding: utf-8 -*-
"""
桌面自动化控制器 - 通过截图 + OCR文字识别 + DeepSeek文本推理 + pyautogui 控制真实浏览器
完全避免反爬虫和反自动化检测，因为控制的用户自己正在使用的真实浏览器
"""
import os
import sys
import json
import time
import base64
import random
import asyncio
import threading
from io import BytesIO
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Callable
from loguru import logger

import pyautogui

# pyautogui 安全设置
pyautogui.FAILSAFE = True  # 鼠标移动到左上角时紧急停止
pyautogui.PAUSE = 0.1  # 每个操作后的默认暂停

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ScreenAction:
    """单次屏幕操作"""
    action_type: str  # "click" | "type" | "scroll" | "move" | "wait" | "done" | "error"
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = None
    reason: str = ""
    scroll_amount: int = 0


@dataclass
class JobProcessResult:
    """单个岗位处理结果"""
    title: str = ""
    company: str = ""
    salary: str = ""
    match_score: float = 0.0
    match_reason: str = ""
    status: str = ""  # "skipped_salary" | "skipped_match" | "communicated" | "failed" | "no_button"
    greeting_sent: str = ""  # 发送的招呼语（仅communicated时有值）


@dataclass
class PipelineState:
    """自动化流水线状态"""
    running: bool = False
    paused: bool = False
    total_jobs: int = 0
    processed: int = 0
    communicated: int = 0
    skipped: int = 0
    failed: int = 0
    current_job_title: str = ""
    current_job_company: str = ""
    start_time: Optional[datetime] = None
    logs: list = field(default_factory=list)
    job_results: list = field(default_factory=list)  # List[JobProcessResult]
    stop_event: object = None  # threading.Event，用于Ctrl+C停止

    def elapsed(self) -> float:
        if self.start_time:
            return (datetime.now() - self.start_time).total_seconds()
        return 0

    def add_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        self.logs.append(entry)
        logger.info("[DesktopAgent] {}", msg)

    def record_job(self, title: str, company: str, salary: str,
                   status: str, match_score: float = 0.0,
                   match_reason: str = "", greeting: str = ""):
        """记录单个岗位的处理结果"""
        result = JobProcessResult(
            title=title, company=company, salary=salary,
            status=status, match_score=match_score,
            match_reason=match_reason, greeting_sent=greeting,
        )
        self.job_results.append(result)

    def get_report(self) -> str:
        """生成自动化操作日志报告"""
        lines = []
        lines.append("=" * 55)
        lines.append("  桌面自动化操作报告")
        lines.append("=" * 55)
        lines.append(f"  运行时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S') if self.start_time else '未知'}")
        lines.append(f"  总耗时: {int(self.elapsed())} 秒")
        lines.append(f"  已处理: {self.processed} | 已沟通: {self.communicated} | 跳过: {self.skipped} | 失败: {self.failed}")
        lines.append("-" * 55)

        if not self.job_results:
            lines.append("  (无岗位记录)")
        else:
            for i, r in enumerate(self.job_results, 1):
                status_icon = {"communicated": "已沟通", "skipped_match": "匹配不够",
                               "skipped_salary": "薪资不符", "no_button": "无沟通按钮",
                               "failed": "失败"}.get(r.status, r.status)
                lines.append(f"\n  [{i}] {r.title}")
                lines.append(f"      公司: {r.company or '未知'}")
                lines.append(f"      薪资: {r.salary or '未知'}")
                lines.append(f"      匹配度: {int(r.match_score*100)}% - {r.match_reason}" if r.match_reason else f"      匹配度: {int(r.match_score*100)}%")
                lines.append(f"      结果: {status_icon}")
                if r.greeting_sent:
                    lines.append(f"      招呼语: {r.greeting_sent[:60]}...")

        lines.append("\n" + "=" * 55)
        return "\n".join(lines)

    def summary(self) -> str:
        return (
            f"已处理: {self.processed}/{self.total_jobs} | "
            f"已沟通: {self.communicated} | 跳过: {self.skipped} | 失败: {self.failed} | "
            f"用时: {self.elapsed():.0f}秒"
        )


# ============================================================
# 核心控制器
# ============================================================

class DesktopController:
    """通过截图 + OCR + AI文本推理 + pyautogui 控制真实浏览器"""

    def __init__(self, client, model: str):
        self.client = client
        self.model = model
        self._screen_width, self._screen_height = pyautogui.size()
        logger.info("[DesktopController] 初始化: 屏幕={}x{}", self._screen_width, self._screen_height)

    # ---- 截图 ----
    def capture_screen(self, region=None):
        """截取屏幕并返回 PIL Image 对象"""
        if region:
            img = pyautogui.screenshot(region=region)
        else:
            img = pyautogui.screenshot()
        return img

    def _capture_and_ocr(self):
        """
        截图并进行OCR文字识别（使用PaddleOCR），返回识别到的文字及其屏幕坐标。
        
        返回:
            (ocr_text, text_items)
            ocr_text: 完整OCR文字内容（含坐标）
            text_items: [(text, x, y, w, h), ...] 每个识别项包含文字和位置
        """
        import numpy as np
        img = self.capture_screen()
        try:
            from paddleocr import PaddleOCR
            # PaddleOCR 单例，避免重复初始化
            if not hasattr(self, "_ocr"):
                self._ocr = PaddleOCR(lang="ch")
            result = self._ocr.ocr(np.array(img))
            
            items = []
            lines = []
            if result and result[0]:
                for line in result[0]:
                    bbox = line[0]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                    text = line[1][0]  # 文字
                    conf = line[1][1]  # 置信度
                    
                    if text and conf > 0.5:
                        x = int(bbox[0][0])
                        y = int(bbox[0][1])
                        w = int(bbox[2][0] - bbox[0][0])
                        h = int(bbox[2][1] - bbox[0][1])
                        items.append((text, x, y, w, h))
                        lines.append(f"  [{text}] @ ({x},{y}) 大小={w}x{h} 置信度={conf:.2f}")
            
            ocr_text = "\n".join(lines)
            logger.debug("[DesktopController] PaddleOCR识别到 {} 个文字块", len(items))
            return ocr_text, items
        except ImportError:
            logger.warning("[DesktopController] PaddleOCR未安装")
            return "OCR未安装", []
        except Exception as e:
            logger.error("[DesktopController] OCR失败: {}", e)
            return f"OCR错误: {e}", []

    # ---- 屏幕分析（OCR + DeepSeek文本推理） ----
    async def analyze_screen(self, task: str, context: str = "") -> ScreenAction:
        """
        截图 -> OCR提取文字及坐标 -> DeepSeek文本推理 -> 返回操作指令。
        
        参数:
            task: 当前任务描述（如"点击第3个岗位的'立即沟通'按钮"）
            context: 操作历史上下文
        """
        ocr_text, text_items = self._capture_and_ocr()

        # 构建给AI的提示词（包含OCR识别到的所有文字及其屏幕坐标）
        prompt = f"""你是一个桌面自动化助手。以下是当前屏幕截图通过OCR识别到的文字及其屏幕坐标(像素)。

你的任务: {task}

{context}

屏幕尺寸: {self._screen_width}x{self._screen_height}

当前屏幕上识别到的文字及坐标:
{ocr_text}

请根据这些文字和坐标，输出一个 JSON 格式的操作指令。必须严格使用以下 JSON 格式，不要输出其他内容：

{{
  "action": "click|type|scroll|move|wait|done|error",
  "x": 数字(仅 click/move 时需要),
  "y": 数字(仅 click/move 时需要),
  "text": "字符串(仅 type 时需要)",
  "scroll_amount": 数字(仅 scroll 时需要，正=向下，负=向上),
  "reason": "对这个操作的简短解释"
}}

操作说明:
- click: 点击(x, y)坐标处。用于点击按钮、链接等。
  - 坐标应该是目标文字的中心位置: x + w/2, y + h/2
- type: 在当前位置输入文字。用于填写搜索框、输入消息等。输入前需要先 click 搜索框。
- scroll: 滚动页面。scroll_amount>0 向下，<0 向上。用于浏览更多内容。
- move: 移动鼠标到(x, y)但不点击。用于悬停或定位。
- wait: 等待页面加载。不需要坐标，当页面可能正在加载时使用。
- done: 任务已完成。不需要坐标。
- error: 无法完成任务。在 reason 中说明原因。

重要规则:
- 坐标必须是相对于整个屏幕的像素值(左上角为0,0)
- 如果找到了目标文字，用该文字的坐标计算出点击中心位置
- 如果当前屏幕上没有找到目标文字，尝试 scroll 向下查看更多内容
- 如果有弹窗或对话框，优先处理它们（点击关闭或确认）
- 如果找不到目标，使用 error 并说明原因
- 文字输入使用中文
- 如果目标文字不在屏幕上，先用scroll查看更多"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.1,
            )
            content = response.choices[0].message.content.strip()
            # 处理空响应的情况
            if not content:
                logger.warning("[DesktopController] AI返回空内容")
                return ScreenAction(action_type="error", reason="AI返回空内容，可能是模型繁忙")

            logger.debug("[DesktopController] AI原始回复: {}", content[:300])

            # 提取 JSON（可能被 markdown code block 包裹）
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            data = json.loads(content)
            return ScreenAction(
                action_type=data.get("action", "error"),
                x=data.get("x"),
                y=data.get("y"),
                text=data.get("text"),
                reason=data.get("reason", ""),
                scroll_amount=data.get("scroll_amount", 0),
            )
        except json.JSONDecodeError as e:
            logger.warning("[DesktopController] AI返回非JSON: {} - 原始: {}", e, content[:200] if content else "空")
            return ScreenAction(action_type="error", reason=f"AI返回无法解析: {content[:100] if content else '空'}")
        except Exception as e:
            logger.error("[DesktopController] 分析失败: {}", e)
            return ScreenAction(action_type="error", reason=str(e))

    # ---- 鼠标键盘操作 ----
    def execute_action(self, action: ScreenAction):
        """执行单个屏幕操作"""
        logger.info("[DesktopController] 执行: action={}, x={}, y={}, text={}, reason={}",
                    action.action_type, action.x, action.y, action.text, action.reason)

        if action.action_type == "click":
            if action.x is not None and action.y is not None:
                # 模拟人类移动轨迹
                self._human_move(action.x, action.y)
                time.sleep(random.uniform(0.1, 0.3))
                pyautogui.click()
                logger.info("[DesktopController] 点击 ({}, {})", action.x, action.y)
            else:
                logger.warning("[DesktopController] click 缺少坐标")

        elif action.action_type == "move":
            if action.x is not None and action.y is not None:
                pyautogui.moveTo(action.x, action.y, duration=random.uniform(0.2, 0.5))
                logger.info("[DesktopController] 移动到 ({}, {})", action.x, action.y)

        elif action.action_type == "type":
            if action.text:
                import pyperclip
                pyperclip.copy(action.text)
                time.sleep(0.1)
                pyautogui.hotkey("ctrl", "v")
                logger.info("[DesktopController] 输入(粘贴): {}", action.text[:60])
            else:
                logger.warning("[DesktopController] type 缺少文本")

        elif action.action_type == "scroll":
            pyautogui.scroll(action.scroll_amount or 300)
            logger.info("[DesktopController] 滚动: {}", action.scroll_amount)

        elif action.action_type == "wait":
            wait_time = random.uniform(2.0, 4.0)
            logger.info("[DesktopController] 等待 {:.1f} 秒", wait_time)
            time.sleep(wait_time)

        elif action.action_type == "done":
            logger.info("[DesktopController] 任务完成")

        elif action.action_type == "error":
            logger.error("[DesktopController] 操作失败: {}", action.reason)

    def _human_move(self, target_x: int, target_y: int):
        """模拟人类鼠标移动（bezier曲线 + 随机偏移 + 降级处理）"""
        try:
            from pytweening import easeInOutQuad
            start_x, start_y = pyautogui.position()
            distance = ((target_x - start_x) ** 2 + (target_y - start_y) ** 2) ** 0.5
            steps = max(10, int(distance / 30))
            
            for i in range(1, steps + 1):
                t = easeInOutQuad(i / steps)
                jitter_x = random.uniform(-2, 2) if i < steps else 0
                jitter_y = random.uniform(-2, 2) if i < steps else 0
                x = int(start_x + (target_x - start_x) * t + jitter_x)
                y = int(start_y + (target_y - start_y) * t + jitter_y)
                pyautogui.moveTo(x, y, duration=0)
        except ImportError:
            # 降级为直线移动
            pyautogui.moveTo(target_x, target_y, duration=random.uniform(0.3, 0.7))

    # ---- 高级操作 ----
    def find_browser_window(self):
        """
        查找并激活浏览器窗口。
        支持通过窗口标题和进程名双重检测，兼容搜狗、Chrome、Edge、Firefox、360等浏览器。
        """
        import win32gui
        import win32process
        import psutil

        # 已知浏览器进程名（不区分大小写）
        BROWSER_PROCESSES = {
            "sogouexplorer.exe", "chrome.exe", "msedge.exe", "firefox.exe",
            "360chrome.exe", "360se.exe", "iexplore.exe", "opera.exe",
            "brave.exe", "chromium.exe", "qqbrowser.exe", "maxthon.exe",
        }
        # 窗口标题可能包含的关键词（作为备选）
        TITLE_KEYWORDS = ["Chrome", "Edge", "Firefox", "搜狗", "360", "Microsoft Edge",
                          "Google Chrome", "Mozilla Firefox"]

        browsers = []
        seen_hwnds = set()

        def enum_callback(hwnd, _):
            if hwnd in seen_hwnds:
                return
            try:
                title = win32gui.GetWindowText(hwnd)
                rect = win32gui.GetWindowRect(hwnd)
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                visible = win32gui.IsWindowVisible(hwnd)
                _, pid = win32process.GetWindowThreadProcessId(hwnd)

                try:
                    proc_name = psutil.Process(pid).name().lower()
                except Exception:
                    proc_name = ""

                # 通过进程名或窗口标题检测浏览器
                is_browser = proc_name in BROWSER_PROCESSES
                is_browser_title = any(kw in title for kw in TITLE_KEYWORDS)

                if (is_browser or is_browser_title) and w > 100:
                    seen_hwnds.add(hwnd)
                    browsers.append({
                        "hwnd": hwnd, "title": title, "width": w, "height": h,
                        "visible": visible, "proc": proc_name, "pid": pid,
                    })
                    logger.debug("[DesktopController] 检测到浏览器: [{}x{}] 可见={} proc={} | {}",
                               w, h, visible, proc_name, title[:80])
            except Exception:
                pass

        win32gui.EnumWindows(enum_callback, None)
        logger.info("[DesktopController] 浏览器检测: 找到 {} 个候选窗口", len(browsers))

        if not browsers:
            logger.warning("[DesktopController] 未找到浏览器窗口")
            return None

        # 优先选择: 可见 > 宽度大 > 非最小化
        browsers.sort(key=lambda b: (
            not b["visible"],
            -b["width"],
        ))

        for b in browsers:
            if b["visible"] and b["width"] > 200:
                logger.info("[DesktopController] 激活窗口: [{}x{}] proc={} | {}",
                          b["width"], b["height"], b["proc"], b["title"][:60])
                try:
                    import pygetwindow as gw
                    for w in gw.getAllWindows():
                        if w._hWnd == b["hwnd"]:
                            w.activate()
                            time.sleep(0.5)
                            return w
                except Exception:
                    # 降级：用 win32gui 激活
                    try:
                        win32gui.SetForegroundWindow(b["hwnd"])
                        time.sleep(0.5)
                    except Exception:
                        pass
                    # 返回一个简单对象
                    class SimpleWindow:
                        def __init__(self, title, left, top, width, height):
                            self.title = title
                            self.left = left
                            self.top = top
                            self.width = width
                            self.height = height
                    rect = win32gui.GetWindowRect(b["hwnd"])
                    return SimpleWindow(b["title"], rect[0], rect[1],
                                       rect[2]-rect[0], rect[3]-rect[1])

        logger.warning("[DesktopController] 未找到合适的浏览器窗口（所有候选窗口都不可见或太小）")
        return None


# ============================================================
# 搜索匹配自动化流水线（新版：在网站上搜索→AI匹配→沟通）
# ============================================================

class JobSearchMatchPipeline:
    """
    岗位搜索匹配自动化流水线
    工作流程:
    1. 导航到招聘平台搜索页面
    2. 在搜索框中输入关键词和城市
    3. 点击搜索，等待结果加载
    4. 对每个搜索结果：打开详情 → OCR读取岗位描述 → AI匹配简历 → 匹配度>=阈值则沟通
    5. 不支持直接导航到某个URL，始终在网站上搜索
    """

    # 各平台的搜索页URL
    PLATFORM_SEARCH_URLS = {
        "51job": "https://we.51job.com/pc/search",
        "boss": "https://www.zhipin.com/web/geek/job",
        "liepin": "https://www.liepin.com/zhaopin/",
        "zhaopin": "https://sou.zhaopin.com/",
    }

    # BOSS直聘城市中文名 → 数字编码映射
    BOSS_CITY_CODES = {
        "北京": "101010100", "上海": "101020100", "广州": "101280100",
        "深圳": "101280600", "杭州": "101210100", "南京": "10019001",
        "成都": "101270100", "武汉": "101200100", "西安": "101110100",
        "长沙": "101250100", "重庆": "100040000", "苏州": "101190400",
        "东莞": "101281600", "合肥": "101220100", "郑州": "101180100",
        "济南": "101120100", "青岛": "101120200", "厦门": "101110200",
        "福州": "101110300", "大连": "101070200", "沈阳": "101070100",
        "天津": "101030100", "昆明": "101290100", "贵阳": "101260100",
        "南宁": "101300100", "海口": "101310100", "石家庄": "101090100",
        "太原": "101100100", "南昌": "101240100", "哈尔滨": "101050100",
        "长春": "101060100", "兰州": "101160100", "珠海": "101280700",
        "佛山": "101280800", "无锡": "101190200", "常州": "101191000",
    }

    def __init__(self, controller: DesktopController, state: PipelineState,
                 on_update: Optional[Callable] = None):
        self.ctrl = controller
        self.state = state
        self.on_update = on_update

    def _start_keyboard_monitor(self):
        """启动键盘监听线程，检测Ctrl+C停止信号"""
        import msvcrt

        def _monitor():
            while self.state.running and not self.state.stop_event.is_set():
                try:
                    if msvcrt.kbhit():
                        ch = msvcrt.getch()
                        if ch == b'\x03':  # Ctrl+C
                            self.state.stop_event.set()
                            self.state.running = False
                            self.state.add_log("收到 Ctrl+C，正在停止...")
                            logger.warning("[DesktopAgent] 收到 Ctrl+C 停止信号")
                            break
                except Exception:
                    pass
                time.sleep(0.2)

        self.state.stop_event = threading.Event()
        monitor_thread = threading.Thread(target=_monitor, daemon=True)
        monitor_thread.start()
        self.state.add_log("键盘监听已启动 (Ctrl+C 可停止)")

    def run(self, keyword: str, city: str, salary_min: int = 0,
            platform: str = "51job", max_jobs: int = 5,
            duration_minutes: int = 30, match_threshold: float = 0.8,
            greeting_template: str = "", resume_text: str = ""):
        """
        启动搜索匹配自动化流水线

        参数:
            keyword: 搜索关键词，如 "AI开发工程师"
            city: 城市，如 "苏州"
            salary_min: 最低月薪要求（单位千），如 15 表示15K
            platform: 目标平台，默认 "51job"（前程无忧）
            max_jobs: 最多处理的岗位数
            duration_minutes: 最长运行时间
            match_threshold: 匹配度阈值，默认0.8即80%
            greeting_template: 招呼语模板
            resume_text: 简历文本，用于AI匹配
        """
        self.state.running = True
        self.state.total_jobs = max_jobs
        self.state.start_time = datetime.now()
        self.state.job_results = []  # 清空上次结果
        self.state.add_log(f"=== 搜索匹配自动化启动 ===")
        self.state.add_log(f"关键词: {keyword}, 城市: {city}, 月薪>= {salary_min}K, 匹配阈值: {int(match_threshold*100)}%")
        self.state.add_log(f"平台: {platform}, 最多处理: {max_jobs} 个岗位, 最长: {duration_minutes}分钟")
        if resume_text:
            self.state.add_log(f"简历已加载: {len(resume_text)} 字符")
        else:
            self.state.add_log(f"警告: 未加载简历，AI匹配功能不可用，将跳过所有岗位")

        # 启动键盘监听
        self._start_keyboard_monitor()

        end_time = datetime.now().timestamp() + duration_minutes * 60

        try:
            # ===== 步骤1: 导航到搜索结果页（URL带参，猎聘除外） =====
            self.state.add_log("[步骤1] 导航到搜索结果页...")
            self._navigate_to_search_page(platform, keyword, city)

            # ===== 步骤1.5: 猎聘需AI选择城市筛选 =====
            if platform == "liepin" and city:
                self.state.add_log(f"[步骤1.5] AI选择城市: {city}...")
                self._select_city_on_page(city, platform)

            # ===== 步骤2: 逐个处理搜索结果 =====
            for job_idx in range(max_jobs):
                if datetime.now().timestamp() > end_time:
                    self.state.add_log("达到时间限制，停止")
                    break
                if not self.state.running:
                    self.state.add_log("用户停止")
                    break

                # 每次循环开始前确保浏览器窗口在前台
                browser_win = self.ctrl.find_browser_window()
                if not browser_win:
                    self.state.add_log("找不到浏览器窗口，等待10秒后重试...")
                    time.sleep(10)
                    browser_win = self.ctrl.find_browser_window()
                    if not browser_win:
                        self.state.add_log("致命: 浏览器窗口丢失，停止流水线")
                        break

                self.state.processed += 1
                self.state.add_log(f"\n--- [{self.state.processed}/{self.state.total_jobs}] ---")

                try:
                    # 4a. 截图并识别当前搜索结果页
                    self.state.add_log(f"识别第 {job_idx + 1} 个岗位...")
                    job_info = self._read_job_card_from_list(job_idx, platform)

                    if not job_info:
                        self.state.add_log("没有更多岗位了")
                        self.state.skipped += 1
                        continue

                    title = job_info.get("title", "未知")
                    company = job_info.get("company", "未知")
                    salary = job_info.get("salary", "未知")
                    self.state.current_job_title = title
                    self.state.current_job_company = company
                    self.state.add_log(f"岗位: {title} @ {company}")
                    self.state.add_log(f"薪资: {salary}")

                    # 4a.5 薪资预过滤（不满足最低薪资则跳过，不打开详情）
                    if salary_min > 0:
                        salary_text = job_info.get("salary", "")
                        parsed_salary = self._parse_salary(salary_text)
                        if parsed_salary > 0 and parsed_salary < salary_min:
                            self.state.add_log(f"薪资{parsed_salary}K < {salary_min}K，跳过")
                            self.state.skipped += 1
                            self.state.record_job(title, company, salary, "skipped_salary")
                            continue

                    # 4b. 打开岗位详情
                    self.state.add_log("打开岗位详情...")
                    self._open_job_detail(job_idx, platform)

                    # 4c. OCR读取岗位描述
                    self.state.add_log("读取岗位描述...")
                    job_desc = self._read_job_description(platform)
                    if not job_desc:
                        self.state.add_log("无法读取岗位描述，跳过")
                        self.state.skipped += 1
                        self.state.record_job(title, company, salary, "failed", match_reason="无法读取JD")
                        self._go_back_to_results(platform)
                        continue

                    # 4d. AI匹配简历
                    self.state.add_log("AI匹配中...")
                    match_score, match_reason = self._ai_match_resume(
                        resume_text, job_desc, job_info
                    )
                    self.state.add_log(f"匹配度: {int(match_score*100)}% - {match_reason[:50]}")

                    # 4e. 判断是否达到阈值
                    if match_score < match_threshold:
                        self.state.add_log(f"匹配度不到{int(match_threshold*100)}%，跳过")
                        self.state.skipped += 1
                        self.state.record_job(title, company, salary, "skipped_match",
                                              match_score=match_score, match_reason=match_reason)
                        self._go_back_to_results(platform)
                        continue

                    # 4f. 匹配度达标，点击沟通按钮并发送招呼语
                    self.state.add_log(f"匹配度达标！尝试沟通...")
                    success = self._click_communicate_button(platform)
                    if success:
                        # 等弹窗/聊天窗口加载
                        time.sleep(random.uniform(3, 5))
                        greeting = self._generate_greeting(job_info, greeting_template)
                        if greeting:
                            self.state.add_log(f"发送招呼语: {greeting[:50]}...")
                            self._find_input_and_send(greeting, platform)
                            self.state.communicated += 1
                            self.state.add_log("招呼语已发送！")
                            self.state.record_job(title, company, salary, "communicated",
                                                  match_score=match_score, match_reason=match_reason,
                                                  greeting=greeting)
                    else:
                        self.state.add_log("未找到沟通按钮")
                        self.state.skipped += 1
                        self.state.record_job(title, company, salary, "no_button",
                                              match_score=match_score, match_reason=match_reason)

                    # 4g. 返回搜索结果页
                    self._go_back_to_results(platform)

                except Exception as e:
                    self.state.failed += 1
                    self.state.add_log(f"处理失败: {e}")
                    self.state.record_job(
                        self.state.current_job_title or "未知",
                        self.state.current_job_company or "未知",
                        "", "failed", match_reason=f"异常: {str(e)[:60]}"
                    )
                    try:
                        self._go_back_to_results(platform)
                    except Exception:
                        pass

                if self.on_update:
                    self.on_update(self.state)

                # 岗位间冷却
                cooldown = random.uniform(3, 8)
                self.state.add_log(f"冷却 {cooldown:.0f} 秒...")
                time.sleep(cooldown)

        except Exception as e:
            self.state.failed += 1
            self.state.add_log(f"流水线异常: {e}")
            import traceback
            self.state.add_log(traceback.format_exc())

        self.state.running = False
        self.state.add_log(f"\n=== 流水线结束: {self.state.summary()} ===")

        # 输出完整日志报告
        report = self.state.get_report()
        self.state.add_log(report)
        logger.info("[DesktopAgent] 完整报告:\n{}", report)
        return report

    # ==================== 内部方法 ====================

    def _get_event_loop(self):
        """在线程中安全获取事件循环"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                return new_loop
            return loop
        except RuntimeError:
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            return new_loop

    def _navigate_to_search_page(self, platform: str, keyword: str = "", city: str = ""):
        """导航到平台的搜索页面，直接构造带参数的搜索URL。猎聘不支持URK传城市，需要AI去选"""
        import pyperclip
        from urllib.parse import quote

        if platform == "51job":
            url = f"https://we.51job.com/pc/search?keyword={quote(keyword)}&jobArea={quote(city)}"
        elif platform == "boss":
            # BOSS直聘城市用数字编码
            city_code = self.BOSS_CITY_CODES.get(city, "")
            if city_code:
                url = f"https://www.zhipin.com/web/geek/job?query={quote(keyword)}&city={city_code}"
            else:
                # 无编码时只传关键词，城市由用户手动选择或AI辅助
                url = f"https://www.zhipin.com/web/geek/job?query={quote(keyword)}"
                self.state.add_log(f"BOSS直聘: 城市'{city}'无编码映射，仅传关键词")
        elif platform == "liepin":
            # 猎聘URL不支持城市参数，只传关键词，城市通过AI界面操作选择
            url = f"https://www.liepin.com/zhaopin/?key={quote(keyword)}"
        elif platform == "zhaopin":
            url = f"https://sou.zhaopin.com/?kw={quote(keyword)}&jl={quote(city)}"
        else:
            url = self.PLATFORM_SEARCH_URLS.get(platform, "https://we.51job.com/pc/search")

        self.state.add_log(f"导航到: {url[:80]}...")
        self.ctrl.find_browser_window()
        time.sleep(0.5)

        # Ctrl+T 打开新标签页（避免覆盖当前聊天页面）
        pyautogui.hotkey("ctrl", "t")
        time.sleep(0.5)

        # Ctrl+L 聚焦地址栏
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.3)
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)

        # 粘贴搜索URL
        pyperclip.copy(url)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)
        pyautogui.press("enter")
        time.sleep(random.uniform(5, 8))  # 等搜索结果加载

    def _select_city_on_page(self, city: str, platform: str):
        """在搜索页面直接点击城市筛选标签（猎聘城市是横向标签列表，不是下拉面板）"""
        self.state.add_log(f"选择城市: {city}")

        # 先滚到页面顶部确保筛选栏可见
        pyautogui.hotkey("ctrl", "home")
        time.sleep(0.8)

        # 用PaddleOCR获取带坐标的文字块
        ocr_text, text_items = self.ctrl._capture_and_ocr()

        if not text_items:
            self.state.add_log("OCR无结果，跳过城市选择")
            return

        # 步骤1: 在所有文字块中找目标城市
        for text, x, y, w, h in text_items:
            if text.strip() == city or text.strip() == city + "市":
                cx, cy = x + w // 2, y + h // 2
                self.state.add_log(f"找到城市标签: '{text}' at ({cx},{cy})")
                pyautogui.moveTo(cx, cy, duration=random.uniform(0.3, 0.6))
                pyautogui.click()
                time.sleep(random.uniform(3, 5))
                return

        # 步骤2: 城市可能被合并成了一个长文本块，手动解析位置
        for text, x, y, w, h in text_items:
            # 找包含多个城市名的合并文本（如"东上海天津重庆...南京..."）
            if city in text and len(text) > 6:
                # 找到目标城市在合并文本中的位置
                pos = text.find(city)
                # 计算它在整个文本块中的相对位置
                ratio = pos / len(text)
                cx = x + int(w * ratio) + 20  # +20补偿文字宽度
                cy = y + h // 2
                self.state.add_log(f"从合并文本定位'{city}': pos={pos}/{len(text)}, ratio={ratio:.2f}, click=({cx},{cy})")
                pyautogui.moveTo(cx, cy, duration=random.uniform(0.3, 0.6))
                pyautogui.click()
                time.sleep(random.uniform(3, 5))
                return

        # 步骤3: 都没找到，用AI兜底
        loop = self._get_event_loop()
        task = (
            f"在页面顶部的城市筛选标签栏中，直接找到并点击'{city}'标签。"
            f"城市标签是横向排列的，不需要打开任何下拉面板。"
            f"只需找到'{city}'文字并点击它。"
        )
        action = loop.run_until_complete(
            self.ctrl.analyze_screen(task, f"{platform}页面顶部，需要点击城市标签: {city}")
        )
        if action.action_type == "click":
            self.ctrl.execute_action(action)
        else:
            self.state.add_log(f"AI也未找到城市标签: {action.action_type}")
            # 最后兜底：硬坐标（南京大概在第7个标签位，每个约54px，起始约x=430）
            # 不同城市在标签列表中的索引不同，这里简单估算
            pyautogui.moveTo(800, 165, duration=random.uniform(0.3, 0.5))
            pyautogui.click()
            time.sleep(2)

        # 等页面刷新
        time.sleep(random.uniform(3, 5))

    def _fill_search_form(self, keyword: str, city: str, salary_min: int, platform: str):
        """通过OCR+AI找到搜索框并填入搜索条件"""
        loop = self._get_event_loop()

        task = (
            f"找到搜索条件输入区域。需要做以下操作：\n"
            f"1. 找到搜索关键词输入框，点击它\n"
            f"2. 找到城市/地区选择，如果城市已设置为'{city}'则保持不变"
        )

        action = loop.run_until_complete(
            self.ctrl.analyze_screen(task, f"在{platform}搜索页面，当前需要输入: 关键词={keyword}, 城市={city}")
        )

        if action.action_type == "click":
            self.ctrl.execute_action(action)
            time.sleep(0.5)
            # 输入关键词
            import pyperclip
            pyperclip.copy(keyword)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.3)
            pyautogui.press("enter")
            time.sleep(random.uniform(3, 5))
        else:
            # 降级方案: Ctrl+F 在搜索框上
            self.state.add_log("OCR未定位搜索框，使用降级方案...")
            # 尝试Tab键导航到搜索框（通常搜索框是页面第一个输入框）
            pyautogui.hotkey("ctrl", "l")
            time.sleep(0.3)
            pyautogui.press("tab", presses=3)
            time.sleep(0.5)
            import pyperclip
            pyperclip.copy(f"{keyword} {city}")
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.3)
            pyautogui.press("enter")
            time.sleep(random.uniform(3, 5))

    def _read_job_card_from_list(self, index: int, platform: str) -> Optional[dict]:
        """从搜索结果列表中读取第N个岗位卡片信息。
        由于 _go_back_to_results 已经确保页面回到顶部，这里用增量滚动逐张卡片下移。"""
        loop = self._get_event_loop()

        # 确保浏览器窗口在前台
        self.ctrl.find_browser_window()
        time.sleep(0.3)

        # 每个平台的每张卡片大概高度（像素）
        scroll_per_card = {
            "51job": -350, "boss": -400, "liepin": -350, "zhaopin": -320
        }.get(platform, -350)

        # 如果 index > 0，需要滚动过前面的岗位
        if index > 0:
            self.state.add_log(f"滚动到第{index+1}个岗位...")
            # 非BOSS平台：先回到顶部再滚动（因为 _go_back_to_results 做了 Ctrl+Home）
            # BOSS平台：关标签页后滚动位置保留，不需要回顶部，直接从当前位继续滚
            if platform != "boss":
                pyautogui.hotkey("ctrl", "home")
                time.sleep(0.5)

            # 增量滚动：每次滚一张卡片，直到AI确认看到目标
            cards_to_skip = index
            found = False
            for card in range(cards_to_skip):
                # 滚过一张卡片
                pyautogui.scroll(scroll_per_card)
                time.sleep(0.6)

                # 每滚过几张卡片就验证一下
                if card >= max(0, cards_to_skip - 2):
                    # 最后2张卡片时，让AI确认是否看到目标了
                    check_task = (
                        f"当前屏幕上是否能看到第{index+1}个岗位的标题？"
                        f"注意：搜索结果列表的第1个岗位是最顶部那个。"
                    )
                    check_action = loop.run_until_complete(
                        self.ctrl.analyze_screen(check_task, f"{platform}搜索结果页，验证是否看到第{index+1}个岗位")
                    )
                    # AI如果返回done/click说明找到了
                    if check_action and check_action.action_type not in ("error", "scroll"):
                        found = True
                        self.state.add_log(f"已定位第{index+1}个岗位")
                        break

            # 如果滚完预设数量还没看到，再多滚几次
            if not found:
                for extra in range(8):
                    pyautogui.scroll(scroll_per_card)
                    time.sleep(0.5)
                    check_task = f"当前屏幕是否能看到第{index+1}个岗位的标题？"
                    check_action = loop.run_until_complete(
                        self.ctrl.analyze_screen(check_task, f"{platform}搜索结果页，额外滚动第{extra+1}次")
                    )
                    if check_action and check_action.action_type not in ("error", "scroll"):
                        found = True
                        self.state.add_log(f"额外滚动{extra+1}次后定位第{index+1}个岗位")
                        break

                if not found:
                    self.state.add_log(f"滚动多次仍未找到第{index+1}个岗位，可能没有更多岗位了")
                    return None

        # 让 AI 读取岗位信息
        task = (
            f"查看当前屏幕上可见的第{index+1}个岗位（搜索结果列表中的第{index+1}个，"
            f"即从上往下数第{index+1}张卡片）。"
            f"只识别该岗位的: 岗位名称、公司名称、薪资范围、工作地点。"
            f"只需要识别，不要点击。"
        )

        action = loop.run_until_complete(
            self.ctrl.analyze_screen(task, f"{platform}搜索结果页，识别第{index+1}个岗位卡片信息")
        )

        if action.action_type == "done":
            # 从reason中提取岗位信息
            reason = action.reason or ""
            self.state.add_log(f"OCR识别结果: {reason[:100]}")

            # 简单解析 - 让AI把岗位信息整理成语义描述
            job_info = {
                "title": "",
                "company": "",
                "salary": "",
                "location": "",
            }
            # 用正则解析常见格式（兼容"薪资：X"、"薪资范围X"、"薪资X-X万"等多种格式）
            import re
            title_match = re.search(r'岗位名(?:称|为)?[：:]\s*(.+?)(?:，|。|\s|$)', reason)
            if not title_match:
                # 备选："岗位名称为XXX，"
                title_match = re.search(r'岗位名称[为是]?\s*(.{2,30}?)(?:，|。|,|$)', reason)
            company_match = re.search(r'公司名(?:称|为)?[：:]\s*(.+?)(?:，|。|\s|$)', reason)
            if not company_match:
                company_match = re.search(r'公司名(?:称|为)?[为是]?\s*(.{2,30}?)(?:，|。|,|$)', reason)
            # 宽匹配薪资：薪资范围、薪资：、薪资、月薪 等后面跟数字
            salary_match = re.search(r'(?:薪资|月薪|工资)(?:范围|范畴)?[：:为]?\s*([\d.]+[-\s~至]*[\d.]*\s*[kK万w千]?)', reason)
            location_match = re.search(r'(?:地点|地区|工作地点|位置)[：:为]?\s*(.+?)(?:，|。|\s|$)', reason)

            if title_match:
                job_info["title"] = title_match.group(1).strip()
            if company_match:
                job_info["company"] = company_match.group(1).strip()
            if salary_match:
                job_info["salary"] = salary_match.group(1).strip()
            if location_match:
                job_info["location"] = location_match.group(1).strip()

            if not job_info["title"]:
                # 如果没解析出标题，直接取reason的前几个词
                first_line = reason.split("\n")[0].strip() if reason else ""
                if first_line:
                    job_info["title"] = first_line[:30]

            return job_info if job_info["title"] else None

        return None

    def _open_job_detail(self, index: int, platform: str):
        """点击岗位卡片打开详情页。BOSS直聘会在新标签页打开，需要切换过去。"""
        loop = self._get_event_loop()

        task = (
            f"找到搜索结果列表中第{index+1}个岗位的标题链接或整个卡片，"
            f"将鼠标移动到它的中心位置并点击它，打开岗位详情页。"
            f"注意：不要点击'沟通'或者'投递'按钮，只点击岗位名称标题区域。"
        )

        action = loop.run_until_complete(
            self.ctrl.analyze_screen(task, f"{platform}搜索结果列表页，需要点击第{index+1}个岗位")
        )

        if action.action_type == "click":
            self.ctrl.execute_action(action)
        else:
            self.ctrl.execute_action(action)

        time.sleep(random.uniform(2, 4))

        # BOSS直聘：详情在新标签页打开，需要切换过去
        if platform == "boss":
            self._switch_to_detail_tab(platform)

    def _switch_to_detail_tab(self, platform: str):
        """BOSS直聘专用：检测并切换到详情标签页"""
        loop = self._get_event_loop()

        # 检测当前页面：是否已经是详情页（有"立即沟通"或岗位描述等特征）
        check_task = "当前页面是岗位详情页还是搜索结果列表页？如果是详情页回复done，如果是列表页回复error。"
        check_action = loop.run_until_complete(
            self.ctrl.analyze_screen(check_task, f"{platform}页面类型检测")
        )

        if check_action.action_type == "done":
            self.state.add_log("已在岗位详情页")
            return

        # 不在详情页，说明详情在新标签页打开，切换过去
        self.state.add_log("检测到新标签页，切换...")
        pyautogui.hotkey("ctrl", "tab")
        time.sleep(random.uniform(1.5, 3))

        # 再次确认切换成功
        check_action2 = loop.run_until_complete(
            self.ctrl.analyze_screen(check_task, f"{platform}切换后页面类型检测")
        )
        if check_action2.action_type == "error":
            # 可能切过头了，或者浏览器只有1个标签页（详情在当前页打开）
            self.state.add_log("未检测到详情页，可能是在当前页打开的")
            # 切回去
            pyautogui.hotkey("ctrl", "shift", "tab")
            time.sleep(1)
            return

        self.state.add_log("已切换到岗位详情标签页")

    def _read_job_description(self, platform: str) -> str:
        """OCR读取岗位详情描述，使用AI提取完整JD文本用于简历匹配。
        多轮滚动+智能去重，确保尽可能读到完整的岗位描述。"""
        loop = self._get_event_loop()

        # 步骤0: 先尝试找"展开全部"/"查看更多"等按钮（猎聘等平台JD可能被折叠）
        self._try_expand_jd(platform)

        # 步骤1: 滚动到详情页顶部，从头开始读
        pyautogui.hotkey("ctrl", "home")
        time.sleep(0.8)

        # 先往上滚一点，确保页面头部内容加载
        for _ in range(2):
            pyautogui.scroll(-300)
            time.sleep(0.6)

        full_desc = ""
        prev_round_text = ""  # 上一轮的内容，用于检测是否已读完
        consecutive_no_new = 0  # 连续无新内容的轮数

        for attempt in range(8):  # 最多8轮
            # 判断是否应该结束
            if consecutive_no_new >= 2:
                self.state.add_log(f"JD读取: 连续{consecutive_no_new}轮无新内容，认为已读完")
                break

            # 构建提示词 - 区分"继续滚动"和"已读完"
            task = (
                f"你正在分段读取一个岗位详情页。这是第{attempt+1}轮。\n\n"
                f"请将当前屏幕上可见的岗位描述原文内容，尽可能完整地复制出来。\n"
                f"包括：岗位职责、任职要求、技能要求、公司介绍、福利待遇等所有文字。\n\n"
                f"操作要求：\n"
                f"- 如果屏幕上还有更多未读取的JD内容，回复 scroll 向下滚动继续读取\n"
                f"- 如果当前屏幕内容与之前重复、或已到达页面底部没有新内容了，回复 done\n"
                f"- 把当前屏幕上看到的新内容放在 reason 字段中"
            )

            action = loop.run_until_complete(
                self.ctrl.analyze_screen(task, f"{platform}岗位详情页，第{attempt+1}轮JD读取")
            )

            if action.action_type == "done":
                desc = (action.reason or "").strip()
                if desc:
                    # 检查是否与上一轮内容高度重复（去重）
                    new_content = self._dedup_text(desc, prev_round_text)
                    if len(new_content) < 20:
                        consecutive_no_new += 1
                        self.state.add_log(f"JD读取第{attempt+1}轮: 新内容仅{len(new_content)}字符，可能已到底")
                    else:
                        consecutive_no_new = 0
                        full_desc += new_content + "\n"
                        self.state.add_log(f"JD读取第{attempt+1}轮: +{len(new_content)}字符 (累计{len(full_desc)})")

                    prev_round_text = desc
                else:
                    consecutive_no_new += 1

                # 检查是否AI认为已经读完（reason为空且是done）
                if consecutive_no_new >= 2:
                    break

                # 向下滚动看更多
                pyautogui.scroll(-500)
                time.sleep(0.8)
                continue

            elif action.action_type == "scroll":
                # AI明确让继续滚动
                consecutive_no_new = 0
                self.ctrl.execute_action(action)
                time.sleep(0.8)
                continue

            else:
                # click/move/error等，可能AI找不到内容了
                self.state.add_log(f"JD读取第{attempt+1}轮: AI返回{action.action_type}，停止读取")
                break

        result = full_desc.strip()
        self.state.add_log(f"JD读取完成: 共{len(result)}字符")
        return result if result else ""

    def _try_expand_jd(self, platform: str):
        """尝试点击详情页中'展开全部'/'查看更多'按钮，展开被折叠的JD内容"""
        loop = self._get_event_loop()
        task = (
            "查找页面上是否有'展开全部'、'查看更多'、'查看全部'、'展开'等按钮或链接。"
            "如果有，点击它来展开被隐藏的内容。如果没有，回复done。"
        )
        action = loop.run_until_complete(
            self.ctrl.analyze_screen(task, f"{platform}岗位详情页，尝试展开折叠内容")
        )
        if action.action_type == "click":
            self.ctrl.execute_action(action)
            time.sleep(random.uniform(1.5, 3))
            self.state.add_log("已点击展开按钮")
        else:
            self.state.add_log("未找到展开按钮")

    @staticmethod
    def _dedup_text(new_text: str, prev_text: str) -> str:
        """简单去重：移除新文本中与上一轮重复的部分，返回净新增内容"""
        if not prev_text:
            return new_text
        # 找最大公共前缀
        min_len = min(len(new_text), len(prev_text))
        common = 0
        for i in range(min_len):
            if new_text[i] == prev_text[i]:
                common = i + 1
            else:
                break
        if common > len(new_text) * 0.7:
            # 超过70%重复，几乎全是重复内容
            return new_text[common:].strip()
        return new_text

    def _ai_match_resume(self, resume_text: str, job_desc: str, job_info: dict) -> tuple:
        """使用AI匹配简历与岗位描述，返回(匹配度0-1, 匹配原因)"""
        if not resume_text:
            return 0, "无简历文本"

        try:
            from openai import OpenAI
            from config import AI_API_KEY, AI_API_BASE

            client = OpenAI(api_key=AI_API_KEY, base_url=AI_API_BASE)

            prompt = f"""你是一个简历匹配专家。请分析以下简历与岗位的匹配度。

【岗位信息】
岗位名称: {job_info.get('title', '未知')}
公司: {job_info.get('company', '未知')}
薪资: {job_info.get('salary', '未知')}
工作地点: {job_info.get('location', '未知')}

【岗位描述】
{job_desc[:2000]}

【候选人简历】
{resume_text[:1500]}

请从以下几个方面分析匹配度（每项0-25分）：
1. 技能匹配：要求的技术栈候选人是否具备
2. 经验匹配：工作经验年限和方向是否对得上
3. 学历匹配：学历要求是否满足
4. 综合匹配：整体契合程度

请以JSON格式返回结果，不要有任何其他文字：
{{"score": 0.0-1.0, "reason": "简短原因(50字以内)", "detail": {{"skill": 0-25, "exp": 0-25, "edu": 0-25, "overall": 0-25}}}}"""

            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=300,
            )
            content = resp.choices[0].message.content or "{}"
            # 清理可能的markdown代码块
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            data = json.loads(content.strip())
            return float(data.get("score", 0)), data.get("reason", "")
        except Exception as e:
            logger.warning(f"AI匹配失败: {e}")
            return 0.5, f"AI匹配异常: {str(e)[:30]}"

    def _go_back_to_results(self, platform: str):
        """返回搜索结果列表页面。BOSS直聘用关标签页，其他平台用浏览器后退。"""
        # 确保浏览器窗口在前台
        self.ctrl.find_browser_window()
        time.sleep(0.3)

        if platform == "boss":
            # BOSS直聘：详情在新标签页，关闭当前标签页即可回到搜索结果
            self.state.add_log("关闭详情标签页，返回搜索结果...")
            pyautogui.hotkey("ctrl", "w")
            time.sleep(random.uniform(2, 4))
            # 搜索结果页的滚动位置保留，不需要回顶部
            self.state.add_log("已返回搜索结果页(BOSS)")
        else:
            # 其他平台：浏览器后退
            pyautogui.hotkey("alt", "left")
            time.sleep(random.uniform(3, 5))

            # 关键：滚动到页面顶部，确保每次从一致的起点开始
            pyautogui.hotkey("ctrl", "home")
            time.sleep(random.uniform(1, 2))

            # 再稍等一下让结果列表重新渲染完成
            time.sleep(random.uniform(1, 2))

            self.state.add_log("已返回搜索结果页并滚动到顶部")

    def _click_communicate_button(self, platform: str) -> bool:
        """通过OCR+AI找到并点击沟通按钮"""
        loop = self._get_event_loop()

        button_keywords = {
            "51job": "['立即沟通','去聊聊','联系','投递','申请','沟通']",
            "boss": "['立即沟通','打招呼','联系TA']",
            "liepin": "['立即沟通','聊一聊','联系TA','投递简历']",
            "zhaopin": "['立即沟通','联系TA']",
        }
        keywords = button_keywords.get(platform, "['立即沟通','沟通','联系','投递']")

        task = f"找到页面中的沟通按钮。可能的关键词: {keywords}。找到后点击它。如果没有找到，向下滚动再找。"

        scroll_count = 0
        max_scrolls = 3  # 最多滚动3次，防止死循环

        for attempt in range(3):
            action = loop.run_until_complete(
                self.ctrl.analyze_screen(task, f"当前{platform}岗位详情页，第{attempt+1}次查找沟通按钮")
            )

            if action.action_type == "click":
                self.ctrl.execute_action(action)
                time.sleep(random.uniform(1.5, 3))
                return True
            elif action.action_type == "scroll":
                if scroll_count >= max_scrolls:
                    self.state.add_log(f"已滚动{max_scrolls}次，未找到沟通按钮，放弃")
                    return False
                scroll_count += 1
                self.ctrl.execute_action(action)
                time.sleep(random.uniform(1, 2))
                continue
            elif action.action_type in ("done", "error"):
                # 无法继续，返回失败
                return False
            else:
                self.ctrl.execute_action(action)
                time.sleep(1)
                continue

        return False

    def _generate_greeting(self, job: dict, template: str) -> str:
        """根据岗位和模板生成招呼语"""
        title = job.get("title", "")
        company = job.get("company", "")
        if template:
            try:
                return template.format(title=title, company=company)
            except (KeyError, ValueError):
                pass
        return f"您好，我对'{title}'这个岗位很感兴趣，我有相关的大模型和AI开发经验，方便沟通一下吗？"

    def _type_and_send(self, text: str):
        """输入文字并发送（粘贴方式，已废弃，请用_find_input_and_send）"""
        import pyperclip
        pyperclip.copy(text)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.5)
        pyautogui.press("enter")
        time.sleep(1.5)

    def _find_input_and_send(self, text: str, platform: str):
        """在聊天弹窗中找到输入框，输入招呼语并发送"""
        loop = self._get_event_loop()

        task = (
            "当前应该已经打开了聊天对话框。"
            "在对话框中找到消息输入框（通常是textarea或输入框），点击它使其获得焦点，"
            "然后回复done。不要输入任何文字，只需点击输入框。"
        )

        for attempt in range(2):
            action = loop.run_until_complete(
                self.ctrl.analyze_screen(task, f"{platform}聊天对话框，第{attempt+1}次找输入框")
            )
            if action.action_type == "click":
                self.ctrl.execute_action(action)
                time.sleep(0.5)
                break
            elif action.action_type == "done":
                break
            else:
                # 可能已经在输入框了
                break

        # 粘贴招呼语并发送
        import pyperclip
        pyperclip.copy(text)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(random.uniform(0.5, 1))
        pyautogui.press("enter")
        time.sleep(1.5)

    def _parse_salary(self, salary_text: str) -> int:
        """解析薪资文本，返回月薪K数（如15表示15K）。范围取最大值。无法解析返回0"""
        if not salary_text:
            return 0
        import re
        # 收集所有匹配到的数字
        values = []
        # 匹配 "15K"、"15k"
        for m in re.finditer(r'(\d+\.?\d*)\s*[kK]', salary_text):
            values.append(float(m.group(1)))
        # 匹配 "万" 格式
        for m in re.finditer(r'(\d+\.?\d*)\s*万', salary_text):
            values.append(float(m.group(1)) * 10)
        # 匹配纯数字（如 15000）
        if not values:
            for m in re.finditer(r'(\d{4,5})', salary_text):
                num = int(m.group(1))
                if num >= 1000:
                    values.append(num // 1000)
        # 返回最大值（范围如"1-1.5万"取1.5万=15K）
        if values:
            return int(max(values))
        return 0

    def stop(self):
        """停止流水线"""
        self.state.running = False
        self.state.add_log("收到停止指令")


# 保留旧类名的兼容别名
JobCommunicationPipeline = JobSearchMatchPipeline
