# -*- coding: utf-8 -*-
"""
简历-岗位匹配模块 - 使用 AI 分析简历与岗位的匹配度
"""
from typing import List, Optional
from loguru import logger
import json

from rag.qa_engine import QAEngine


class ResumeMatcher:
    """简历匹配引擎"""

    def __init__(self):
        self.qa_engine = QAEngine()
        self.qa_engine._init_client()

    def _parse_resume_with_ai(self, resume_text: str) -> dict:
        """让 AI 从简历原文中提取结构化信息"""
        system_prompt = """你是专业的简历解析助手。请从以下简历文本中提取关键信息，并以 JSON 格式返回。

请提取以下字段：
- name: 姓名（如未找到返回"未知"）
- education: 最高学历
- school: 毕业院校
- major: 专业
- skills: 掌握的技能列表（数组）
- work_experience: 工作经历简述
- years_of_experience: 工作年限（数字，如无法确定返回0）
- projects: 主要项目经验简述
- certificates: 证书列表（数组）
- target_positions: 求职目标岗位（数组，根据简历内容推测）

务必返回 JSON 格式，不要包含多余的解释文字。"""

        try:
            response = self.qa_engine.client.chat.completions.create(
                model=self.qa_engine.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"请解析以下简历内容：\n\n{resume_text}"}
                ],
                temperature=0.3,
                max_tokens=2000
            )
            content = response.choices[0].message.content.strip()
            # 清理可能的 markdown 代码块标记
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content
                if "```" in content:
                    content = content.rsplit("```", 1)[0]
            return json.loads(content)
        except Exception as e:
            logger.error(f"AI 简历解析失败: {e}")
            return {
                "name": "未知",
                "education": "未知",
                "skills": [],
                "work_experience": "",
                "years_of_experience": 0,
                "target_positions": []
            }

    def match_resume_with_jobs(self, resume_text: str, jobs: List[dict]) -> str:
        """让 AI 分析简历与岗位的匹配度，生成求职建议"""
        # 先用 AI 提取简历结构化信息
        parsed = self._parse_resume_with_ai(resume_text)

        system_prompt = """你是一位资深的职业规划师和求职顾问。请根据求职者的简历信息和岗位列表，进行详细的匹配分析。

请提供以下分析内容：

## 一、简历摘要
简要概括求职者的背景、技能和经验。

## 二、岗位匹配分析
对每个岗位逐一分析匹配度，包括：
- 岗位名称与公司
- 匹配度评分（百分制）
- 匹配理由（技能/经验匹配点）
- 差距分析（缺少哪些要求）

## 三、综合建议
1. 最适合的岗位推荐（Top 3）
2. 简历优化建议（针对目标岗位如何优化简历）
3. 技能提升建议（建议补充哪些技能）
4. 薪资谈判建议（基于匹配度和市场行情）

分析要具体、有针对性，基于岗位的实际要求给出建议。"""

        jobs_summary = json.dumps(jobs, ensure_ascii=False, indent=2)

        try:
            response = self.qa_engine.client.chat.completions.create(
                model=self.qa_engine.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"## 求职者简历信息\n{json.dumps(parsed, ensure_ascii=False, indent=2)}\n\n## 招聘岗位列表\n{jobs_summary}"}
                ],
                temperature=0.7,
                max_tokens=4000,
                extra_body={"enable_search": True}
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"匹配分析生成失败: {e}")
            return f"匹配分析生成失败: {str(e)}"

    def match_resume_with_platform_jobs(self, resume_text: str, platform: str, jobs: List[dict]) -> str:
        """针对特定平台的岗位进行匹配分析"""
        # 直接用 AI 提取简历信息和匹配
        parsed = self._parse_resume_with_ai(resume_text)
        jobs_summary = json.dumps(jobs, ensure_ascii=False, indent=2)

        system_prompt = f"""你是一位资深的职业规划师。求职者正在查看 {platform} 平台的岗位。
请分析简历与这些岗位的匹配情况，给出具体建议。

分析结构：
1. 简历核心能力摘要
2. 各岗位匹配度评分（百分制）及理由
3. 推荐投递的岗位（按匹配度排序）
4. 针对目标岗位的简历关键词优化建议"""

        try:
            response = self.qa_engine.client.chat.completions.create(
                model=self.qa_engine.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"## 简历信息\n{json.dumps(parsed, ensure_ascii=False, indent=2)}\n\n## {platform} 岗位列表\n{jobs_summary}"}
                ],
                temperature=0.7,
                max_tokens=4000,
                extra_body={"enable_search": True}
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"{platform} 匹配分析失败: {e}")
            return f"匹配分析失败: {str(e)}"

    def analyze_single_job(self, resume_text: str, job: dict) -> str:
        """深度分析简历与单个岗位的匹配度，给出面试成功可能性和技能差距"""
        parsed = self._parse_resume_with_ai(resume_text)

        system_prompt = """你是一位资深的招聘顾问和职业规划师。请根据求职者的简历和岗位详情，进行深度的单岗位匹配分析。

请提供以下分析内容（使用 Markdown 格式）：

## 一、简历核心画像
简要概括求职者的技术栈、经验背景和核心竞争力。

## 二、岗位核心要求
提炼该岗位的关键要求（技术栈、经验、学历等）。

## 三、匹配度评分
从以下维度分别评分（百分制），并计算总分：
1. 技术栈匹配度
2. 经验年限匹配度
3. 项目经历匹配度
4. 学历专业匹配度
5. 综合匹配度

## 四、面试成功可能性
- 总体评估（高/中/低）
- 理由说明

## 五、技能差距分析
- 已具备的核心技能（与岗位匹配的）
- 缺少的关键技能
- 可短期补齐的技能

## 六、针对性建议
1. 简历优化建议（针对该岗位如何优化简历关键词）
2. 技能补充建议（建议优先学习哪些技能）
3. 面试准备建议（可能会被问到的技术点）"""

        try:
            response = self.qa_engine.client.chat.completions.create(
                model=self.qa_engine.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"## 求职者简历信息\n{json.dumps(parsed, ensure_ascii=False, indent=2)}\n\n## 目标岗位信息\n{json.dumps(job, ensure_ascii=False, indent=2)}"}
                ],
                temperature=0.7,
                max_tokens=4000,
                extra_body={"enable_search": True}
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"单岗位深度分析失败: {e}")
            return f"分析失败: {str(e)}"

    def optimize_resume(self, resume_text: str, job: dict, user_input: str = "") -> str:
        """AI优化简历：根据目标岗位需求生成增量补充内容，保留原简历完整结构"""
        parsed = self._parse_resume_with_ai(resume_text)

        system_prompt = (
            "你是一位资深的招聘顾问和简历优化专家。请根据求职者的简历和目标岗位需求，生成针对性的增量补充内容。\n\n"
            "重要原则：\n"
            "1. 不要重写整份简历，只输出需要新增或修改的内容段落\n"
            "2. 保持真实，不要编造经历，只能基于用户提供的信息\n"
            "3. 如果用户提供了额外的项目经历或技能，将其写成可直接插入简历的段落\n"
            "4. 优化表达方式，使描述更专业、更有说服力、更符合岗位关键词\n"
            "5. 所有输出内容应为可直接插入简历的完整段落\n\n"
            "关键要求：\n"
            "- 首先仔细分析【原简历内容】，找出简历中已有的模块标题（如：个人技能、专业技能、项目经历、项目经验、工作经历、教育背景等）\n"
            "- 每个增量内容必须用【模块：xxx】的格式标明它属于简历中的哪个模块，xxx必须是原简历中实际出现的模块名称\n"
            "- 如果原简历中没有对应的模块名称，则新增一个合适的模块名称\n\n"
            "请按以下格式输出增量内容，每个部分用清晰的标题分隔：\n\n"
            "【模块：项目经历】\n"
            "（这里输出应插入到「项目经历」模块下的内容，比如新增的项目描述）\n\n"
            "【模块：专业技能】\n"
            "（这里输出应插入到「专业技能」模块下的内容，比如补充的技能描述）\n\n"
            "【模块：工作经历】\n"
            "（这里输出应插入到「工作经历」模块下的内容，比如优化后的工作描述）\n\n"
            "注意：只输出增量内容，不要输出完整的简历，不要重复原简历已有内容。"
        )

        try:
            response = self.qa_engine.client.chat.completions.create(
                model=self.qa_engine.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"## 原简历内容\n{resume_text}\n\n## 简历结构化信息\n{json.dumps(parsed, ensure_ascii=False, indent=2)}\n\n## 目标岗位要求\n{json.dumps(job, ensure_ascii=False, indent=2)}\n\n## 用户补充的项目经历和技能\n{user_input if user_input else '（无补充）'}"}
                ],
                temperature=0.5,
                max_tokens=6000,
                extra_body={"enable_search": True}
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"简历优化失败: {e}")
            return f"优化失败: {str(e)}"
