# -*- coding: utf-8 -*-
"""
Agent 状态定义 - LangGraph State
"""
from typing import TypedDict, Annotated, List, Any, Optional
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """Agent 全局状态"""
    # 对话消息历史（自动追加）
    messages: Annotated[List[BaseMessage], add_messages]

    # 当前搜索的岗位数据
    search_results: Optional[List[dict]]

    # 已上传的简历文件路径
    resume_path: Optional[str]

    # 已上传的简历解析结果
    resume_data: Optional[dict]

    # 最后一次操作结果摘要（用于 Agent 上下文传递）
    last_action_result: Optional[str]

    # 当前正在处理的用户意图
    intent: Optional[str]

    # 是否正在流式输出
    streaming: bool

    # Hermes 自进化：当前活跃的策略洞察文本（注入 System Prompt）
    hermes_insights: Optional[str]

    # Hermes 自进化：最近经验统计摘要
    experience_summary: Optional[str]
