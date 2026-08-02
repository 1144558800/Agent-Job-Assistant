# -*- coding: utf-8 -*-
"""
上下文管理器 - 负责对话上下文持久化、Token 计数、自动裁剪和容量警告
"""
import os
import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from loguru import logger

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_DIR

# 对话持久化存储目录
CONTEXT_STORE_DIR = DATA_DIR / "conversations"
CONTEXT_STORE_DIR.mkdir(parents=True, exist_ok=True)

# DeepSeek-chat 上下文窗口上限（tokens）
DEEPSEEK_MAX_TOKENS = 128 * 1024  # 128K
# 上下文窗口使用率警告阈值
CONTEXT_WARNING_THRESHOLD = 0.80  # 80%
# 裁剪后保留的最小消息轮数（1轮 = user + assistant 消息对）
MIN_KEEP_ROUNDS = 3


# ---- Token 估算 ----
# DeepSeek 使用 BPE tokenizer，这里用字符级估算（1中文≈1.5token, 1英文词≈1.3token）
def estimate_tokens(text: str) -> int:
    """
    估算文本的 token 数量。
    中文约 1 字符 = 1.5 token，英文约 1 词 = 1.3 token，混合文本取两者加权。
    误差通常在 +-15% 以内，对于上下文管理足够。
    """
    if not text:
        return 0
    
    # 统计中文和非中文字符
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    non_chinese = len(text) - chinese_chars
    
    # 中文部分按 1.5 token/字，非中文按 4 字符 ≈ 3 token（近似英文词+标点）
    chinese_tokens = int(chinese_chars * 1.5)
    non_chinese_tokens = int(non_chinese * 0.75)  # ~4 chars = 1 word = ~3 tokens
    
    return chinese_tokens + non_chinese_tokens


def estimate_messages_tokens(messages: List[Dict]) -> int:
    """估算消息列表的总 token 数"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            # 多模态内容列表
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    total += estimate_tokens(part["text"])
        # 消息角色标签开销约 4 tokens
        total += 4
    return total


# ---- 对话持久化 ----

def get_conversation_file(thread_id: str) -> Path:
    """获取指定对话的持久化文件路径"""
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', thread_id)
    return CONTEXT_STORE_DIR / f"{safe_name}.json"


def persist_conversation(thread_id: str, messages: List[Dict], metadata: Optional[Dict] = None) -> bool:
    """
    持久化对话消息到 JSON 文件。
    
    参数:
        thread_id: 对话ID
        messages: 消息列表（LangChain message 格式的序列化）
        metadata: 可选的元数据（如标题、创建时间等）
    
    返回: 是否成功
    """
    try:
        file_path = get_conversation_file(thread_id)
        data = {
            "thread_id": thread_id,
            "messages": messages,
            "metadata": metadata or {},
            "message_count": len(messages),
            "estimated_tokens": estimate_messages_tokens(messages),
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug("[Context] 对话已持久化: {} ({} 条消息, ~{} tokens)",
                    thread_id, len(messages), data["estimated_tokens"])
        return True
    except Exception as e:
        logger.error("[Context] 持久化失败 {}: {}", thread_id, e)
        return False


def load_conversation(thread_id: str) -> Optional[Dict]:
    """
    从 JSON 文件加载对话。
    
    返回: 包含 messages 和 metadata 的字典，如果文件不存在返回 None
    """
    file_path = get_conversation_file(thread_id)
    if not file_path.exists():
        return None
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info("[Context] 对话已加载: {} ({} 条消息, ~{} tokens)",
                    thread_id, len(data.get("messages", [])), data.get("estimated_tokens", 0))
        return data
    except Exception as e:
        logger.error("[Context] 加载失败 {}: {}", thread_id, e)
        return None


def list_saved_conversations() -> List[Dict]:
    """列出所有持久化的对话（用于前端对话列表）"""
    conversations = []
    if not CONTEXT_STORE_DIR.exists():
        return conversations
    
    for f in sorted(CONTEXT_STORE_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            conversations.append({
                "id": data.get("thread_id", f.stem),
                "title": (data.get("metadata", {}) or {}).get("title", f.stem),
                "message_count": data.get("message_count", 0),
                "estimated_tokens": data.get("estimated_tokens", 0),
                "saved_at": f.stat().st_mtime,
            })
        except Exception:
            continue
    
    return conversations


def delete_conversation(thread_id: str) -> bool:
    """删除持久化的对话"""
    file_path = get_conversation_file(thread_id)
    if file_path.exists():
        try:
            file_path.unlink()
            logger.info("[Context] 对话已删除: {}", thread_id)
            return True
        except Exception as e:
            logger.error("[Context] 删除失败 {}: {}", thread_id, e)
    return False


# ---- 上下文容量检测与裁剪 ----

def check_context_usage(messages: List[Dict], system_prompt: str = "") -> Tuple[float, int, bool]:
    """
    检查当前上下文使用率。
    
    参数:
        messages: 当前消息列表
        system_prompt: 系统提示词
    
    返回: (使用率, 估算总tokens, 是否超过80%)
    """
    total_tokens = estimate_tokens(system_prompt) + estimate_messages_tokens(messages)
    usage = total_tokens / DEEPSEEK_MAX_TOKENS
    is_over_threshold = usage >= CONTEXT_WARNING_THRESHOLD
    return usage, total_tokens, is_over_threshold


def _get_turns(messages: List[Dict]) -> List[List[Dict]]:
    """
    将消息列表按「轮次」分组。
    每轮 = HumanMessage + [AIMessage(带tool_calls)] + [ToolMessage(s)] + [AIMessage(文本)]
    确保裁剪时不会破坏 tool_calls ↔ tool 的对应关系。
    """
    turns = []
    current_turn = []
    
    for msg in messages:
        msg_type = msg.get("type", "")
        # HumanMessage 标志新轮次开始
        if msg_type == "HumanMessage" and current_turn:
            turns.append(current_turn)
            current_turn = []
        current_turn.append(msg)
    
    if current_turn:
        turns.append(current_turn)
    
    return turns


def trim_messages(messages: List[Dict], system_prompt: str = "", 
                  min_keep_rounds: int = MIN_KEEP_ROUNDS) -> Tuple[List[Dict], int]:
    """
    裁剪消息列表，按「轮次」丢弃最早的消息，直到低于 80% 阈值。
    保留最近的 min_keep_rounds 轮对话。
    
    参数:
        messages: 消息列表
        system_prompt: 系统提示词（不计入裁剪）
        min_keep_rounds: 最少保留的对话轮数
    
    返回: (裁剪后的消息列表, 被裁剪的消息数)
    """
    if not messages:
        return messages, 0
    
    usage, _, is_over = check_context_usage(messages, system_prompt)
    
    if not is_over:
        return messages, 0
    
    logger.warning("[Context] 上下文超80%, 开始裁剪... 当前使用率={:.1%}, 消息数={}",
                  usage, len(messages))
    
    # 按轮次分组
    turns = _get_turns(messages)
    total_turns = len(turns)
    
    # 保留最近 min_keep_rounds 轮
    keep_turns = min(min_keep_rounds, total_turns)
    
    # 从最早的轮次开始丢弃，直到低于阈值或只剩保留轮数
    total_trimmed = 0
    while len(turns) > keep_turns:
        usage, _, is_over = check_context_usage(
            [msg for turn in turns for msg in turn], 
            system_prompt
        )
        if not is_over:
            break
        
        # 丢弃最早的一整轮
        removed_turn = turns.pop(0)
        total_trimmed += len(removed_turn)
    
    # 展平剩余的轮次
    trimmed = [msg for turn in turns for msg in turn]
    
    final_usage, final_tokens, _ = check_context_usage(trimmed, system_prompt)
    logger.warning("[Context] 裁剪完成: 丢弃{}条消息(共{}轮), 剩余{}条({}轮), 使用率={:.1%}, ~{}tokens",
                  total_trimmed, total_turns - len(turns), len(trimmed), len(turns), final_usage, final_tokens)
    
    return trimmed, total_trimmed


# ---- 消息完整性校验 ----

def validate_messages(messages: list) -> list:
    """
    校验消息列表的完整性，双向清理：
    1. 移除没有对应 AIMessage tool_calls 的孤儿 ToolMessage
    2. 移除 AIMessage 中没有对应 ToolMessage 的孤儿 tool_calls
    
    DeepSeek API 要求每条 tool_calls <-> ToolMessage 必须成对出现。
    
    返回: 清理后的消息列表
    """
    from langchain_core.messages import AIMessage, ToolMessage
    
    if not messages:
        return messages
    
    # 第一轮：收集所有 ToolMessage 的 tool_call_id（用于反向检测孤儿 tool_calls）
    tool_message_ids = set()
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tc_id = msg.tool_call_id if hasattr(msg, "tool_call_id") else ""
            if tc_id:
                tool_message_ids.add(tc_id)
    
    # 第二轮：清理消息
    cleaned = []
    removed_tool_calls = 0
    removed_tool_messages = 0
    total_orphan_tc = 0
    
    for msg in messages:
        if isinstance(msg, AIMessage):
            # 必须通过 additional_kwargs 操作，因为 AIMessage.tool_calls 是 property
            raw_tcs = msg.additional_kwargs.get("tool_calls", []) if msg.additional_kwargs else []
            if raw_tcs:
                # 检查 tool_calls 是否有对应的 ToolMessage
                orphan_ids = []
                valid_tcs = []
                for tc in raw_tcs:
                    tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                    if tc_id and tc_id not in tool_message_ids:
                        orphan_ids.append(tc_id)
                    else:
                        valid_tcs.append(tc)
                
                if orphan_ids:
                    total_orphan_tc += len(orphan_ids)
                    if valid_tcs:
                        # 保留有效的 tool_calls（直接修改 additional_kwargs）
                        msg.additional_kwargs["tool_calls"] = valid_tcs
                        logger.warning("[Context] AIMessage 清理: {} 个孤儿 tool_calls 已移除 (保留 {} 个有效)",
                                     len(orphan_ids), len(valid_tcs))
                    else:
                        # 所有 tool_calls 都是孤儿，清空 additional_kwargs
                        msg.additional_kwargs["tool_calls"] = []
                        removed_tool_calls += 1
                        logger.warning("[Context] AIMessage 清理: 整条消息的 {} 个 tool_calls 均为孤儿, 已清空",
                                     len(orphan_ids))
            cleaned.append(msg)
        elif isinstance(msg, ToolMessage):
            tc_id = msg.tool_call_id if hasattr(msg, "tool_call_id") else ""
            # 检查对应的 AIMessage tool_calls 是否存在（通过扫描已清理的 cleaned 中的 AIMessage）
            valid_ids = set()
            for cm in cleaned:
                if isinstance(cm, AIMessage):
                    raw_tcs = cm.additional_kwargs.get("tool_calls", []) if cm.additional_kwargs else []
                    for tc in raw_tcs:
                        tid = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                        if tid:
                            valid_ids.add(tid)
            if tc_id and tc_id not in valid_ids:
                removed_tool_messages += 1
                logger.warning("[Context] 孤儿 ToolMessage (tool_call_id={}), 已移除", tc_id)
                continue
            cleaned.append(msg)
        else:
            cleaned.append(msg)
    
    if total_orphan_tc > 0 or removed_tool_messages > 0:
        logger.warning("[Context] 消息校验完成: 孤儿 tool_calls={}, 孤儿 ToolMessage={}, 剩余 {} 条",
                      total_orphan_tc, removed_tool_messages, len(cleaned))
    
    return cleaned


# ---- 消息序列化辅助 ----

def serialize_langchain_message(msg: Any) -> Dict:
    """
    将 LangChain 消息对象序列化为可 JSON 存储的字典。
    支持 HumanMessage, AIMessage, ToolMessage, SystemMessage。
    """
    msg_type = type(msg).__name__
    result = {
        "type": msg_type,
        "content": msg.content if hasattr(msg, "content") else str(msg),
    }
    
    if hasattr(msg, "additional_kwargs"):
        ak = msg.additional_kwargs
        if ak and "tool_calls" in ak:
            result["tool_calls"] = ak["tool_calls"]
    
    if hasattr(msg, "tool_call_id") and msg.tool_call_id:
        result["tool_call_id"] = msg.tool_call_id
    
    if hasattr(msg, "name") and msg.name:
        result["name"] = msg.name
    
    return result


def deserialize_langchain_message(data: Dict) -> Any:
    """
    将字典反序列化为 LangChain 消息对象。
    """
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
    
    msg_type = data.get("type", "")
    content = data.get("content", "")
    
    if msg_type == "HumanMessage":
        return HumanMessage(content=content)
    elif msg_type == "AIMessage":
        additional_kwargs = {}
        if "tool_calls" in data:
            additional_kwargs["tool_calls"] = data["tool_calls"]
        return AIMessage(content=content, additional_kwargs=additional_kwargs)
    elif msg_type == "ToolMessage":
        return ToolMessage(
            content=content,
            tool_call_id=data.get("tool_call_id", ""),
            name=data.get("name", ""),
        )
    elif msg_type == "SystemMessage":
        return SystemMessage(content=content)
    else:
        # 默认当作 HumanMessage 处理
        return HumanMessage(content=content)


def extract_messages_from_state(state: Any) -> List[Dict]:
    """
    从 LangGraph 状态中提取消息并用序列化格式返回。
    同时返回原始消息对象列表用于恢复。
    """
    messages = state.get("messages", [])
    if not messages:
        return []
    return [serialize_langchain_message(m) for m in messages]
