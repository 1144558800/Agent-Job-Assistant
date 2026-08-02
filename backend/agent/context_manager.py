# -*- coding: utf-8 -*-
"""
对话上下文管理器 - 持久化存储、Token估算、自动裁剪
"""
import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from loguru import logger

import config

# 对话存储目录
CONTEXT_DIR = config.BASE_DIR / "data" / "contexts"
CONTEXT_DIR.mkdir(parents=True, exist_ok=True)

# Token 估算参数（中文大约 1 字符 = 1.2 token，英文约 1 字符 = 0.3 token）
CHINESE_TOKEN_RATIO = 1.2
ENGLISH_TOKEN_RATIO = 0.3
MAX_CONTEXT_TOKENS = 120000  # DeepSeek 128K 上限，保留约 8K 缓冲区
TRIM_KEEP_RECENT = 30  # 裁剪时保留最近 30 条消息


class ContextManager:
    """对话上下文管理器"""

    def __init__(self):
        self._cache: Dict[str, List[dict]] = {}
        self._message_counts: Dict[str, int] = {}

    def _get_context_file(self, thread_id: str) -> Path:
        """获取对话文件路径"""
        return CONTEXT_DIR / f"{thread_id}.json"

    def load_history(self, thread_id: str) -> List[dict]:
        """加载对话历史"""
        if thread_id in self._cache:
            return self._cache[thread_id]

        file_path = self._get_context_file(thread_id)
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                messages = data.get("messages", [])
                # 验证消息完整性
                messages = [m for m in messages if isinstance(m, dict) and "role" in m and "content" in m]
                self._cache[thread_id] = messages
                self._message_counts[thread_id] = len(messages)
                logger.info("[Context] 加载对话历史: thread={}, messages={}", thread_id, len(messages))
                return messages
            except Exception as e:
                logger.error("[Context] 加载对话历史失败: {} - {}", thread_id, e)

        self._cache[thread_id] = []
        self._message_counts[thread_id] = 0
        return []

    def save_history(self, thread_id: str, messages: List[dict]):
        """保存对话历史"""
        file_path = self._get_context_file(thread_id)
        try:
            data = {
                "thread_id": thread_id,
                "messages": messages,
                "updated_at": datetime.now().isoformat(),
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._cache[thread_id] = messages
            self._message_counts[thread_id] = len(messages)
            logger.info("[Context] 保存对话历史: thread={}, messages={}", thread_id, len(messages))
        except Exception as e:
            logger.error("[Context] 保存对话历史失败: {} - {}", thread_id, e)

    def add_message(self, thread_id: str, role: str, content: str):
        """添加一条消息"""
        messages = self.load_history(thread_id)
        messages.append({"role": role, "content": content})
        self._message_counts[thread_id] = len(messages)
        self.save_history(thread_id, messages)

    def get_history(self, thread_id: str, crop: bool = True) -> List[dict]:
        """
        获取对话历史，如果上下文过长则自动裁剪
        crop: 是否自动裁剪历史消息
        """
        messages = self.load_history(thread_id)
        if not crop or not messages:
            return messages

        # 估算 token 数
        estimated_tokens = self._estimate_tokens(messages)
        if estimated_tokens > MAX_CONTEXT_TOKENS:
            logger.warning(
                "[Context] 上下文过长，触发自动裁剪: thread={}, tokens_est={}, limit={}",
                thread_id, estimated_tokens, MAX_CONTEXT_TOKENS
            )
            # 保留最近 N 条消息
            keep_count = min(TRIM_KEEP_RECENT, len(messages))
            cropped = messages[-keep_count:]
            self.save_history(thread_id, cropped)
            logger.info("[Context] 已裁剪: thread={}, original={}, cropped={}", thread_id, len(messages), len(cropped))
            return cropped

        return messages

    def get_message_count(self, thread_id: str) -> int:
        """获取消息数量"""
        return self._message_counts.get(thread_id, 0)

    def get_usage(self, thread_id: str) -> Optional[int]:
        """
        获取上下文使用率（百分比 0-100）
        返回 None 表示无法计算
        """
        messages = self.load_history(thread_id)
        if not messages:
            return 0
        estimated = self._estimate_tokens(messages)
        pct = int(estimated / MAX_CONTEXT_TOKENS * 100)
        return min(pct, 100)

    def _estimate_tokens(self, messages: List[dict]) -> int:
        """估算消息列表的总 token 数"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            total += self._estimate_text_tokens(content)
        return total

    def _estimate_text_tokens(self, text: str) -> int:
        """估算文本的 token 数"""
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * CHINESE_TOKEN_RATIO + other_chars * ENGLISH_TOKEN_RATIO)

    def clear_history(self, thread_id: str):
        """清空对话历史"""
        file_path = self._get_context_file(thread_id)
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass
        self._cache.pop(thread_id, None)
        self._message_counts.pop(thread_id, None)
        logger.info("[Context] 已清空对话历史: thread={}", thread_id)

    def delete_all_contexts(self):
        """删除所有对话历史（危险操作）"""
        for f in CONTEXT_DIR.glob("*.json"):
            try:
                f.unlink()
            except Exception:
                pass
        self._cache.clear()
        self._message_counts.clear()
        logger.warning("[Context] 已删除所有对话历史")


# 全局单例
_context_manager = None


def get_context_manager() -> ContextManager:
    global _context_manager
    if _context_manager is None:
        _context_manager = ContextManager()
    return _context_manager
