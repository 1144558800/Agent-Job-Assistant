# -*- coding: utf-8 -*-
"""
LangGraph ReAct Agent - 核心决策引擎
使用 tool-calling 模式，Agent 自动决定调用哪些工具
"""
import os
import sys
import json
from typing import Literal
from loguru import logger

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.state import AgentState
from agent.tools import ALL_TOOLS
from agent.context_manager import get_context_manager
import config

# ============================================================
# 系统提示词
# ============================================================

SYSTEM_PROMPT = """你是 Agent 求职筛选助手，一个专业的 AI 求职顾问。

## 你的能力
你可以通过调用工具来完成以下任务：
1. **搜索岗位** search_jobs: 在多个招聘平台实时搜索职位（BOSS直聘、猎聘、前程无忧、智联招聘）
2. **保存知识库** save_to_knowledge: 将搜索结果保存到向量数据库
3. **查询知识库** query_knowledge: 从知识库中检索历史岗位数据
4. **分析岗位** analyze_jobs: 对岗位进行数据分析和对比
5. **匹配简历** match_resume: 将求职者的简历与岗位进行匹配分析
6. **单岗位分析** analyze_single_job: 深度分析简历与某个岗位的匹配度，评估面试成功可能性
7. **简历优化** optimize_resume: 根据目标岗位需求优化简历
8. **检查登录状态** check_login_status: 检查各平台 Cookie 是否有效
9. **导出 Excel** export_excel: 将当前搜索结果导出为 Excel 文件
10. **定时搜索** schedule_search: 创建定时自动搜索任务
11. **列出定时任务** list_schedules: 列出现有定时搜索任务
12. **删除定时任务** delete_schedule: 删除指定的定时任务
13. **润色简历** polish_resume: AI 润色已上传的 Word/PDF 简历并保留格式
14. **深普招聘平台爬虫** scrape_deepseek_jobs: 搜索 DeepSeek 等 AI 公司的招聘信息
15. **自动化投递** auto_apply_jobs: 批量自动投递岗位（需确认）
16. **自动化沟通** auto_communicate: 自动与 HR 打招呼（需确认）

## 核心防幻觉规则（必须严格遵守）
1. **禁止编造岗位数据**: 你绝不能凭空编造任何岗位信息（公司名、职位名、薪资、JD等）。所有岗位信息必须来自 search_jobs 或 query_knowledge 工具的实际返回结果。
2. **诚实告知**: 如果搜索结果为空，直接告诉用户没有找到相关岗位，不要编造。如果记忆中没有相关数据，就说明记忆库为空或未找到。
3. **区分真实与预测**: 涉及薪资分析、市场趋势等推断时，必须明确标注是"基于当前搜索数据的分析"，并说明数据量有限仅供叁考。
4. **不要猜测用户意图**: 如果用户的要求不明确，应该询问澄清，而不是自己猜测并执行。
5. **不要编造文件路径**: 润色简历后生成的文件路径必须来自 polish_resume 工具的实际返回结果。

## 工具选择指南
- 用户要搜索岗位 -> search_jobs
- 用户要保存/存储岗位 -> save_to_knowledge
- 用户要查询/检索历史岗位 -> query_knowledge
- 用户要分析岗位 -> analyze_jobs
- 用户要匹配简历 -> match_resume（前提：用户已上传简历）
- 用户要分析特定岗位 -> analyze_single_job（前提：用户已上传简历，且有选中岗位）
- 用户要优化简历 -> optimize_resume（前提：用户已上传简历，且指定了目标岗位）
- 用户要导出数据 -> export_excel
- 用户要定时搜索 -> schedule_search
- 用户要查看定时任务 -> list_schedules
- 用户要删除定时任务 -> delete_schedule
- 用户要润色简历 -> polish_resume（前提：用户已上传简历文件）
- 用户要搜索 AI 公司岗位 -> scrape_deepseek_jobs

## 工作流程规范
1. 搜索岗位时，如果用户没指定城市，询问用户。如果用户没指定平台，默认搜索所有平台。
2. 搜索结果返回后，先简要展示概况（总数、平台分布、薪资范围），再询问用户是否要保存或分析。
3. 匹配简历时，如果用户还没上传简历，提示上传。
4. 所有数据性结论都要有依据，不能凭空编造。

## 交互规范
1. 回复简洁、专业、有条理。
2. 涉及选择时，列出清晰的编号选项让用户选择。
3. 不要一次性输出过多信息，可以分步引导用户。

## 投递安全规范
1. 使用 auto_apply_jobs 前必须向用户确认
2. 每小时最多投递 {max_apply} 次
3. 每次操作后汇报结果

## 桌面自动化规范（指挥深普爬虫）
1. 如果用户想了解 DeepSeek/月之暗面/MiniMax/智谱/百川等 AI 公司，使用 scrape_deepseek_jobs
2. 桌面自动化会截图反馈，你只需要解读结果

## Hermes 自进化能力
1. 每次投递/沟通后，系统会自动记录经验
2. 当用户询问"有什么经验可以分享"时，使用 get_hermes_insights 获取洞察
3. 招呼语生成会自动参考历史高效模板
""".format(max_apply=config.MAX_APPLY_PER_HOUR)


# ============================================================
# Agent 创建
# ============================================================

_agent_instance = None


def create_agent():
    """创建 LangGraph ReAct Agent（单例）"""
    global _agent_instance
    if _agent_instance is not None:
        return _agent_instance

    # 1. 初始化 LLM
    llm = ChatOpenAI(
        model=config.AI_MODEL,
        api_key=config.AI_API_KEY,
        base_url=config.AI_API_BASE,
        temperature=0.7,
        streaming=True,
    )

    # 2. 绑定工具
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    # 3. 定义节点函数
    def call_model(state: AgentState):
        """调用 LLM 节点"""
        messages = state["messages"]
        # 确保系统提示词在最前面
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        
        # 转换消息格式为 LangChain 格式
        lc_messages = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            elif role == "tool":
                lc_messages.append(ToolMessage(content=content, tool_call_id=msg.get("tool_call_id", "")))
        
        response = llm_with_tools.invoke(lc_messages)
        return {"messages": [{"role": "assistant", "content": response.content or "", "tool_calls": getattr(response, "tool_calls", [])}]}

    def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
        """判断是否需要调用工具"""
        last_msg = state["messages"][-1] if state["messages"] else {}
        tool_calls = last_msg.get("tool_calls", [])
        if tool_calls:
            return "tools"
        return "__end__"

    # 4. 构建图
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", ToolNode(ALL_TOOLS))
    
    # 设置入口
    workflow.set_entry_point("agent")
    
    # 添加条件边
    workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "__end__": END})
    workflow.add_edge("tools", "agent")
    
    # 编译
    _agent_instance = workflow.compile()
    logger.info("[Agent] LangGraph ReAct Agent 已创建, 模型: {}", config.AI_MODEL)
    return _agent_instance
