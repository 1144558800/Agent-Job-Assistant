# -*- coding: utf-8 -*-
"""
QA 问答引擎 - 集成 AI 进行问答
"""
from typing import List, Optional
from loguru import logger
import json

class QAEngine:
    """问答引擎"""
    
    def __init__(self, provider: str = "openai"):
        self.provider = provider
        self.client = None
    
    def _init_client(self):
        """初始化 AI 客户端"""
        if self.client is not None:
            return
        
        if self.provider == "openai":
            from openai import OpenAI
            import config as cfg
            self.client = OpenAI(
                api_key=cfg.AI_API_KEY,
                base_url=cfg.AI_API_BASE
            )
            self.model = cfg.AI_MODEL
            logger.info(f"初始化 OpenAI 客户端, 模型: {self.model}")
        elif self.provider == "ollama":
            from openai import OpenAI
            import config as cfg
            self.client = OpenAI(
                api_key="ollama",
                base_url=f"{cfg.OLLAMA_BASE_URL}/v1"
            )
            self.model = cfg.OLLAMA_MODEL
            logger.info(f"初始化 Ollama 客户端, 模型: {self.model}")
    
    def get_answer(self, question: str, context: List[dict]) -> str:
        """基于上下文获取答案，并支持联网搜索补充"""
        self._init_client()
        
        # 构建上下文文本
        context_text = self._format_context(context)
        
        # 构建提示词
        system_prompt = """你是智能求职助手，专门帮助求职者分析招聘信息。
你有两个信息源：
1. 岗位信息库（已搜索到的岗位数据）：优先使用
2. 实时联网搜索（当用户询问公司背景、行业细节等岗位信息库未覆盖的内容时）：你可以主动联网搜索补充

回答规则：
- 如果岗位信息库中有相关内容，优先使用并注明信息来源
- 如果用户问到公司详细介绍、行业趋势等岗位信息库没有的内容，请主动联网搜索补充
- 回答要简洁明了，重点突出"""
        
        user_prompt = f"""以下是已保存的岗位信息（搜索到的招聘数据）：

{context_text}

求职者问题: {question}

请回答求职者的问题。如果需要补充公司背景、行业信息等，可以联网搜索。"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=2000,
                extra_body={"enable_search": True}  # 启用联网搜索
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"AI 回答生成失败: {e}")
            return f"抱歉，AI 回答生成失败: {str(e)}"
    
    def analyze_jobs(self, jobs: List[dict]) -> str:
        """分析岗位信息，给出建议"""
        self._init_client()
        
        job_summary = json.dumps(jobs, ensure_ascii=False, indent=2)
        
        system_prompt = """你是专业的求职分析师，请帮助求职者分析以下岗位信息。
提供以下分析:
1. 薪资水平分析
2. 技能要求总结
3. 各岗位优劣势对比
4. 综合建议"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"请分析以下岗位信息:\n{job_summary}"}
                ],
                temperature=0.7,
                max_tokens=2000,
                extra_body={"enable_search": True}
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"岗位分析失败: {e}")
            return f"抱歉，岗位分析失败: {str(e)}"
    
    def _format_context(self, context: List[dict]) -> str:
        """格式化上下文"""
        lines = []
        for i, item in enumerate(context, 1):
            doc = item.get("document", {})
            content = doc.get("content", "")
            metadata = doc.get("metadata", {})
            
            lines.append(f"--- 岗位 {i} ---")
            lines.append(f"平台: {metadata.get('platform', '未知')}")
            lines.append(f"岗位: {metadata.get('job_name', '未知')}")
            lines.append(f"公司: {metadata.get('company_name', '未知')}")
            lines.append(f"薪资: {metadata.get('salary', '未知')}")
            lines.append(f"地点: {metadata.get('location', '未知')}")
            lines.append(f"详情: {content}")
            lines.append("")
        
        return "\n".join(lines)
