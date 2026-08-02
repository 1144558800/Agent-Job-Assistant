# -*- coding: utf-8 -*-
"""
Agent 状态定义 - LangGraph 状态管理
"""
from typing import TypedDict, List, Dict, Any, Optional, Annotated
import operator


class AgentState(TypedDict):
    """Agent 状态"""
    messages: Annotated[List[Dict[str, Any]], operator.add]
    context: Dict[str, Any]
    search_results: List[Dict[str, Any]]
    analysis_results: Dict[str, Any]
    tool_calls: List[Dict[str, Any]]
