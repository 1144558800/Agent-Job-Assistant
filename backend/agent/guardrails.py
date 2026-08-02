# -*- coding: utf-8 -*-
"""
Guardrails 约束模块 - Agent 安全防护

四层约束：
1. 频率熔断：单日投递上限、连续失败熔断、同平台最小间隔
2. 内容审核：招呼语合规检查（禁止联系方式、侮辱、虚假内容）
3. 操作确认：高风险操作超过阈值时要求确认
4. 审计日志：所有高风险操作写入独立审计日志
"""
import os
import sys
import json
import time
import re
from pathlib import Path
from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass, field, asdict
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 约束状态持久化路径
GUARDRAILS_DIR = Path(__file__).resolve().parent.parent / "data" / "guardrails"
RATE_LIMIT_STATE_FILE = GUARDRAILS_DIR / "rate_limit_state.json"
AUDIT_LOG_FILE = GUARDRAILS_DIR / "audit.log"


# ========== 配置（从 config.py 导入，提供默认值） ==========

def _get_config():
    """延迟导入配置，避免循环引用"""
    try:
        from config import (
            GUARDRAILS_ENABLED,
            GUARDRAILS_DAILY_APPLY_LIMIT,
            GUARDRAILS_CONSECUTIVE_FAIL_LIMIT,
            GUARDRAILS_FAIL_COOLDOWN_MINUTES,
            GUARDRAILS_SAME_PLATFORM_INTERVAL_SEC,
            GUARDRAILS_CONFIRM_THRESHOLD,
            GUARDRAILS_CONTENT_BLOCK_PATTERNS,
        )
        return {
            "enabled": GUARDRAILS_ENABLED,
            "daily_apply_limit": GUARDRAILS_DAILY_APPLY_LIMIT,
            "consecutive_fail_limit": GUARDRAILS_CONSECUTIVE_FAIL_LIMIT,
            "fail_cooldown_minutes": GUARDRAILS_FAIL_COOLDOWN_MINUTES,
            "same_platform_interval_sec": GUARDRAILS_SAME_PLATFORM_INTERVAL_SEC,
            "confirm_threshold": GUARDRAILS_CONFIRM_THRESHOLD,
            "content_block_patterns": GUARDRAILS_CONTENT_BLOCK_PATTERNS,
        }
    except ImportError:
        return {
            "enabled": True,
            "daily_apply_limit": 30,
            "consecutive_fail_limit": 5,
            "fail_cooldown_minutes": 60,
            "same_platform_interval_sec": 90,
            "confirm_threshold": 10,
            "content_block_patterns": [],
        }


# ========== 审计日志 ==========

class AuditLogger:
    """独立审计日志，记录所有高风险操作"""

    def __init__(self):
        self._log_file = AUDIT_LOG_FILE

    def _ensure_dir(self):
        GUARDRAILS_DIR.mkdir(parents=True, exist_ok=True)

    def log(self, action: str, result: str, detail: Dict = None, passed: bool = True):
        """写入审计日志"""
        self._ensure_dir()
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "result": result,
            "passed": passed,
            "detail": detail or {},
        }
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("[Guardrails] 审计日志写入失败: {}", e)

    def get_recent_logs(self, count: int = 50) -> List[Dict]:
        """获取最近的审计日志"""
        self._ensure_dir()
        if not self._log_file.exists():
            return []
        try:
            with open(self._log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            logs = []
            for line in lines[-count:]:
                line = line.strip()
                if line:
                    logs.append(json.loads(line))
            return logs
        except Exception as e:
            logger.error("[Guardrails] 审计日志读取失败: {}", e)
            return []


# ========== 第1层：频率熔断 ==========

@dataclass
class RateLimitState:
    """频率限制状态"""
    today_apply_count: int = 0
    today_date: str = ""
    consecutive_failures: int = 0
    last_failure_time: str = ""
    cooldown_until: str = ""
    last_apply_time_by_platform: Dict[str, str] = field(default_factory=dict)


class RateLimiter:
    """频率熔断控制器"""

    def __init__(self):
        self._state = RateLimitState()
        self._load_state()

    def _load_state(self):
        """从磁盘加载状态"""
        if RATE_LIMIT_STATE_FILE.exists():
            try:
                with open(RATE_LIMIT_STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._state = RateLimitState(**data)
                logger.debug("[Guardrails] 频率状态已加载: today_apply={}, failures={}",
                           self._state.today_apply_count, self._state.consecutive_failures)
            except Exception as e:
                logger.warning("[Guardrails] 频率状态加载失败: {}", e)

    def _save_state(self):
        """持久化状态"""
        GUARDRAILS_DIR.mkdir(parents=True, exist_ok=True)
        with open(RATE_LIMIT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(asdict(self._state), f, ensure_ascii=False, indent=2)
        logger.debug("[Guardrails] 频率状态已保存: today_apply={}, failures={}, cooldown={}",
                    self._state.today_apply_count, self._state.consecutive_failures,
                    self._state.cooldown_until or "无")

    def _check_today_reset(self):
        """检查是否需要重置每日计数"""
        today = time.strftime("%Y-%m-%d")
        if self._state.today_date != today:
            old_count = self._state.today_apply_count
            self._state.today_date = today
            self._state.today_apply_count = 0
            self._save_state()
            logger.info("[Guardrails] 每日计数重置: {} -> {}（旧值={}）", self._state.today_date, today, old_count)

    def _is_in_cooldown(self) -> bool:
        """检查是否处于冷却期"""
        if not self._state.cooldown_until:
            return False
        try:
            cooldown_end = time.mktime(time.strptime(self._state.cooldown_until, "%Y-%m-%d %H:%M:%S"))
            return time.time() < cooldown_end
        except:
            return False

    def check_daily_limit(self) -> Tuple[bool, str]:
        """检查每日投递上限"""
        config = _get_config()
        if not config["enabled"]:
            return True, ""

        self._check_today_reset()
        limit = config["daily_apply_limit"]

        if self._state.today_apply_count >= limit:
            msg = f"已达到今日投递上限（{limit} 个），请明天再试。"
            logger.warning("[Guardrails] 每日上限: {}/{}", self._state.today_apply_count, limit)
            return False, msg

        logger.debug("[Guardrails] 每日上限检查通过: {}/{}", self._state.today_apply_count, limit)
        return True, ""

    def check_consecutive_failures(self) -> Tuple[bool, str]:
        """检查连续失败熔断"""
        config = _get_config()
        if not config["enabled"]:
            return True, ""

        if self._is_in_cooldown():
            remaining = ""
            try:
                end = time.mktime(time.strptime(self._state.cooldown_until, "%Y-%m-%d %H:%M:%S"))
                remaining_min = max(0, int((end - time.time()) / 60))
                remaining = f" 剩余冷却 {remaining_min} 分钟"
            except:
                pass
            msg = f"连续失败过多，已触发熔断保护{remaining}。"
            logger.warning("[Guardrails] 熔断状态: 冷却至 {}", self._state.cooldown_until)
            return False, msg

        logger.debug("[Guardrails] 熔断检查通过: 连续失败={}/{}", 
                    self._state.consecutive_failures, config["consecutive_fail_limit"])
        return True, ""

    def check_platform_interval(self, platform: str) -> Tuple[bool, str]:
        """检查同平台最小投递间隔"""
        config = _get_config()
        if not config["enabled"]:
            return True, ""

        min_interval = config["same_platform_interval_sec"]
        last_time_str = self._state.last_apply_time_by_platform.get(platform, "")

        if last_time_str:
            try:
                last_time = time.mktime(time.strptime(last_time_str, "%Y-%m-%d %H:%M:%S"))
                elapsed = time.time() - last_time
                if elapsed < min_interval:
                    wait_sec = min_interval - elapsed
                    msg = f"{platform} 投递间隔不足（需等待 {int(wait_sec)} 秒）"
                    logger.warning("[Guardrails] 平台间隔: {} 距上次 {:.0f}s, 需>= {}s",
                                 platform, elapsed, min_interval)
                    return False, msg
            except Exception as e:
                logger.warning("[Guardrails] 平台间隔检查异常: {}", e)

        logger.debug("[Guardrails] 平台间隔检查通过: platform={}, min_interval={}s", platform, min_interval)
        return True, ""

    def record_success(self, platform: str = ""):
        """记录一次成功操作"""
        self._check_today_reset()
        self._state.today_apply_count += 1
        self._state.consecutive_failures = 0  # 成功后重置连续失败计数
        if platform:
            self._state.last_apply_time_by_platform[platform] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._save_state()
        logger.info("[Guardrails] 记录成功: today={}/{}, failures_reset",
                   self._state.today_apply_count, _get_config()["daily_apply_limit"])

    def record_failure(self, platform: str = ""):
        """记录一次失败操作"""
        config = _get_config()
        self._state.consecutive_failures += 1
        self._state.last_failure_time = time.strftime("%Y-%m-%d %H:%M:%S")

        logger.info("[Guardrails] 记录失败: platform={}, 连续失败={}/{}",
                   platform, self._state.consecutive_failures, config["consecutive_fail_limit"])

        # 连续失败达到阈值，触发熔断
        if self._state.consecutive_failures >= config["consecutive_fail_limit"]:
            cooldown_sec = config["fail_cooldown_minutes"] * 60
            self._state.cooldown_until = time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(time.time() + cooldown_sec)
            )
            logger.warning("[Guardrails] 熔断触发! 连续失败={}, 冷却至 {}",
                         self._state.consecutive_failures, self._state.cooldown_until)

        self._save_state()

    def get_status(self) -> Dict:
        """获取当前频率限制状态"""
        self._check_today_reset()
        config = _get_config()
        status = {
            "today_apply_count": self._state.today_apply_count,
            "daily_limit": config["daily_apply_limit"],
            "consecutive_failures": self._state.consecutive_failures,
            "fail_limit": config["consecutive_fail_limit"],
            "in_cooldown": self._is_in_cooldown(),
            "cooldown_until": self._state.cooldown_until if self._is_in_cooldown() else "",
        }
        logger.debug("[Guardrails] 查询频率状态: today={}/{}, failures={}/{}, cooldown={}",
                    status["today_apply_count"], status["daily_limit"],
                    status["consecutive_failures"], status["fail_limit"],
                    status["in_cooldown"])
        return status


# ========== 第2层：内容审核 ==========

class ContentValidator:
    """招呼语内容审核器"""

    # 内置敏感模式（始终生效，不依赖配置）
    _BUILTIN_PATTERNS = [
        # 联系方式（会导致平台封号）
        (r"1[3-9]\d{9}", "包含手机号"),
        (r"\d{3,4}[-]?\d{7,8}", "包含座机号"),
        (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "包含邮箱"),
        (r"(微信|WeChat|wx|QQ)\s*[:：]?\s*\d{5,}", "包含微信号/QQ号"),
        # 攻击性/不适当内容
        (r"(傻[逼比屄]|脑残|弱智|智障)", "包含攻击性词汇"),
        (r"(骗子|诈骗|皮包公司|黑[心企])", "包含贬损性词汇"),
        # 虚假承诺（避免给平台投诉留证据）
        (r"(保证.*入职|包过|100%.*通过|必.*录取)", "包含过度承诺"),
    ]

    def validate(self, greeting: str) -> Tuple[bool, str]:
        """审核招呼语内容

        返回: (是否通过, 拒绝原因)
        """
        if not greeting or not greeting.strip():
            logger.warning("[Guardrails][内容审核] 拦截: 招呼语为空")
            return False, "招呼语为空"

        # 长度检查
        if len(greeting) > 500:
            logger.warning("[Guardrails][内容审核] 拦截: 招呼语过长（{}字符）", len(greeting))
            return False, f"招呼语过长（{len(greeting)}字符，上限500）"

        # 内置敏感模式检查
        for pattern, reason in self._BUILTIN_PATTERNS:
            match = re.search(pattern, greeting)
            if match:
                matched_text = match.group(0)
                logger.warning("[Guardrails][内容审核] 拦截: reason={}, matched='{}'", reason, matched_text)
                return False, f"招呼语{reason}，已自动拦截"

        # 自定义敏感模式检查（来自配置）
        config = _get_config()
        custom_patterns = config.get("content_block_patterns", [])
        for entry in custom_patterns:
            pattern = entry.get("pattern", "")
            reason = entry.get("reason", "匹配自定义敏感词")
            if pattern and re.search(pattern, greeting):
                logger.warning("[Guardrails][内容审核] 自定义拦截: reason={}, pattern={}", reason, pattern)
                return False, f"招呼语{reason}，已自动拦截"

        logger.debug("[Guardrails][内容审核] 审核通过: length={}", len(greeting))
        return True, ""


# ========== 第4层：操作确认判断 ==========

class ConfirmGate:
    """高风险操作确认闸门"""

    def should_confirm(self, apply_count: int) -> Tuple[bool, str]:
        """判断是否需要用户确认

        返回: (是否需要确认, 原因说明)
        """
        config = _get_config()
        threshold = config["confirm_threshold"]

        if apply_count > threshold:
            msg = f"一次性投递 {apply_count} 个岗位（超过确认阈值 {threshold} 个），建议分批操作以降低风控风险"
            logger.info("[Guardrails] 确认闸门触发: count={}, threshold={}", apply_count, threshold)
            return True, msg

        logger.debug("[Guardrails] 确认闸门: count={} <= threshold={}, 无需确认", apply_count, threshold)
        return False, ""


# ========== 统一管理器 ==========

class GuardrailManager:
    """Guardrails 统一管理器"""

    def __init__(self):
        self.rate_limiter = RateLimiter()
        self.content_validator = ContentValidator()
        self.audit_logger = AuditLogger()
        self.confirm_gate = ConfirmGate()

    def pre_apply_check(self, platform: str = "", apply_count: int = 1) -> Tuple[bool, str]:
        """投递前检查（综合频率熔断）

        返回: (是否允许, 拒绝原因)
        """
        config = _get_config()
        if not config["enabled"]:
            logger.debug("[Guardrails] 已禁用，跳过所有检查")
            return True, ""

        # 第1层：连续失败熔断（最高优先级）
        ok, msg = self.rate_limiter.check_consecutive_failures()
        if not ok:
            self.audit_logger.log("apply", "blocked_by_cooldown", {"reason": msg}, passed=False)
            logger.warning("[Guardrails] 投递被拦截: {}", msg)
            return False, msg

        # 第1层：每日上限
        ok, msg = self.rate_limiter.check_daily_limit()
        if not ok:
            self.audit_logger.log("apply", "blocked_by_daily_limit", {"reason": msg}, passed=False)
            logger.warning("[Guardrails] 投递被拦截: {}", msg)
            return False, msg

        # 第1层：平台间隔
        if platform:
            ok, msg = self.rate_limiter.check_platform_interval(platform)
            if not ok:
                self.audit_logger.log("apply", "blocked_by_interval", {"platform": platform, "reason": msg}, passed=False)
                logger.warning("[Guardrails] 投递被拦截: {}", msg)
                return False, msg

        # 第3层：确认闸门
        need_confirm, confirm_msg = self.confirm_gate.should_confirm(apply_count)
        if need_confirm:
            logger.info("[Guardrails] 投递超过确认阈值: count={}, threshold={}",
                       apply_count, _get_config()["confirm_threshold"])
            # 只是警告，不阻断（确认由 Agent 的 System Prompt 负责）
            pass

        self.audit_logger.log("apply", "pre_check_passed",
                             {"platform": platform, "count": apply_count}, passed=True)
        logger.info("[Guardrails] 投递前检查通过: platform={}, count={}", platform, apply_count)
        return True, ""

    def post_apply_record(self, success: bool, platform: str = ""):
        """投递后记录结果到频率限制"""
        if success:
            self.rate_limiter.record_success(platform)
        else:
            self.rate_limiter.record_failure(platform)

        self.audit_logger.log(
            "apply_result",
            "success" if success else "failure",
            {"platform": platform},
            passed=success,
        )

    def validate_greeting(self, greeting: str) -> Tuple[bool, str]:
        """审核招呼语内容

        返回: (是否通过, 拒绝原因)
        """
        ok, reason = self.content_validator.validate(greeting)
        if not ok:
            self.audit_logger.log(
                "greeting_blocked",
                reason,
                {"greeting_preview": greeting[:100]},
                passed=False,
            )
        return ok, reason

    def log_login_attempt(self, platform: str, success: bool):
        """记录登录尝试"""
        self.audit_logger.log(
            "login_attempt",
            "success" if success else "failure",
            {"platform": platform},
            passed=success,
        )

    def log_schedule_operation(self, action: str, detail: Dict):
        """记录定时任务操作"""
        self.audit_logger.log(
            f"schedule_{action}",
            "executed",
            detail,
            passed=True,
        )

    def get_rate_limit_status(self) -> Dict:
        """获取频率限制状态"""
        return self.rate_limiter.get_status()

    def get_audit_logs(self, count: int = 50) -> List[Dict]:
        """获取审计日志"""
        return self.audit_logger.get_recent_logs(count)


# ========== 全局单例 ==========

_guardrail_manager: Optional[GuardrailManager] = None


def get_guardrail_manager() -> GuardrailManager:
    """获取 GuardrailManager 全局单例"""
    global _guardrail_manager
    if _guardrail_manager is None:
        _guardrail_manager = GuardrailManager()
    return _guardrail_manager
