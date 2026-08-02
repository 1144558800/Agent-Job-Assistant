# -*- coding: utf-8 -*-
"""
Guardrails 安全约束层
四层约束：频率熔断、内容审核、操作确认、审计日志
"""
import time
import json
import os
from pathlib import Path
from datetime import datetime
from enum import Enum
from typing import Optional, Dict
from loguru import logger

import config

# ---- 审计日志目录 ----
AUDIT_DIR = config.BASE_DIR / "data" / "audit"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# ---- 频率熔断统计 ----
_apply_timestamps: list = []
_communicate_timestamps: list = []


class OutputVerificationResult(Enum):
    """输出校验结果"""
    valid = "通过"
    too_long = "超出最大长度限制"
    empty = "未生成有效回复"


# ============ 第一层：频率熔断 ============

def check_rate_limit(operation: str) -> bool:
    """
    检查操作是否超过频率限制
    operation: "apply" 或 "communicate"
    返回: True=允许, False=熔断
    """
    now = time.time()
    max_count = config.MAX_APPLY_PER_HOUR
    window = config.SAFETY_WINDOW

    if operation == "apply":
        timestamps = _apply_timestamps
    elif operation == "communicate":
        timestamps = _communicate_timestamps
    else:
        return True

    # 清理窗口外的记录
    timestamps[:] = [t for t in timestamps if now - t < window]

    if len(timestamps) >= max_count:
        logger.warning(f"[Guardrails][频率熔断] {operation} 操作已超过限制 ({len(timestamps)}/{max_count})")
        return False

    timestamps.append(now)
    logger.info(f"[Guardrails][频率统计] {operation}: {len(timestamps)}/{max_count}")
    return True


# ============ 第二层：内容审核 ============

def audit_content(text: str) -> bool:
    """
    审核内容是否安全
    返回: True=通过, False=包含敏感内容
    """
    if not text:
        return True

    # 敏感词黑名单
    blocked_words = [
        "违法", "诈骗", "传销", "刷单", "代写",
        "赌博", "色情", "暴力", "枪支", "毒品",
    ]

    text_lower = text.lower()
    for word in blocked_words:
        if word in text_lower or word in text:
            logger.warning(f"[Guardrails][内容审核] 检测到敏感词: {word}")
            return False

    return True


# ============ 第三层：操作确认 ============

def check_operation_required(tool_name: str) -> bool:
    """
    检查操作是否需要用户确认
    返回: True=需要确认, False=直接执行
    """
    confirm_tools = ["auto_apply_jobs", "auto_communicate"]
    return tool_name in confirm_tools


# ============ 第四层：审计日志 ============

def log_audit(operation: str, details: dict, success: bool, thread_id: str = ""):
    """
    记录操作审计日志
    """
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "operation": operation,
        "thread_id": thread_id,
        "success": success,
        "details": details,
    }

    try:
        # 按日期分文件
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = AUDIT_DIR / f"audit_{date_str}.jsonl"

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        logger.info(f"[Guardrails][审计] {operation} | success={success} | thread={thread_id}")
    except Exception as e:
        logger.error(f"[Guardrails][审计] 写入失败: {e}")


# ============ 输出校验 ============

def validate_output(text: str) -> OutputVerificationResult:
    """
    校验 Agent 输出是否合法
    """
    if not text or len(text.strip()) == 0:
        return OutputVerificationResult.empty

    if len(text) > config.OUTPUT_MAX_LENGTH:
        logger.warning(f"[Guardrails][输出校验] 输出过长: {len(text)} > {config.OUTPUT_MAX_LENGTH}")
        return OutputVerificationResult.too_long

    return OutputVerificationResult.valid


# ============ 招呼语安全审查 ============

def sanitize_greeting(greeting: str) -> str:
    """
    招呼语安全审查：检测并移除敏感表达
    """
    # 移除可能的恶意链接
    import re
    greeting = re.sub(r'https?://\S+', '[链接已移除]', greeting)

    # 移除个人联系方式泄露
    greeting = re.sub(r'1[3-9]\d{9}', '[手机号已隐藏]', greeting)
    greeting = re.sub(r'[\w.-]+@[\w.-]+\.\w+', '[邮箱已隐藏]', greeting)

    return greeting
