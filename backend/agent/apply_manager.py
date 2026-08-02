# -*- coding: utf-8 -*-
"""
自动投递管理器 - 管理简历匹配、生成打招呼消息、记录投递历史
已集成 Hermes 自进化：每次投递操作自动记录经验
"""
import os
import json
import time
from pathlib import Path
from typing import List, Optional, Dict
from loguru import logger

from scrapers.base import JobItem

# 投递历史文件路径
APPLY_HISTORY_FILE = Path(__file__).resolve().parent.parent / "data" / "apply_history.json"


def load_apply_history() -> list:
    """加载投递历史"""
    if not APPLY_HISTORY_FILE.exists():
        logger.debug("[ApplyManager] 投递历史文件不存在: {}", APPLY_HISTORY_FILE)
        return []
    try:
        with open(APPLY_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.debug("[ApplyManager] 投递历史加载成功: {} 条记录", len(data))
        return data
    except Exception as e:
        logger.warning("[ApplyManager] 投递历史文件损坏: {}", e)
        return []


def save_apply_history(history: list):
    """保存投递历史"""
    APPLY_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(APPLY_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    logger.debug("[ApplyManager] 投递历史已保存: {} 条记录", len(history))


def is_already_applied(platform_job_id: str, platform: str) -> bool:
    """检查是否已经投递过"""
    history = load_apply_history()
    for item in history:
        if item.get("platform_job_id") == platform_job_id and item.get("platform") == platform:
            logger.debug("[ApplyManager] 重复投递检测: [{}] {} - 已投递", platform, str(platform_job_id)[:30])
            return True
    logger.debug("[ApplyManager] 重复投递检测: [{}] {} - 未投递", platform, str(platform_job_id)[:30])
    return False


def record_apply(platform_job_id: str, platform: str, job_name: str,
                 company_name: str, greeting: str, success: bool, message: str):
    """记录投递结果，同时写入 Hermes 经验记忆"""
    history = load_apply_history()
    record = {
        "platform_job_id": platform_job_id,
        "platform": platform,
        "job_name": job_name,
        "company_name": company_name,
        "greeting": greeting[:200],
        "success": success,
        "message": message,
        "applied_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    history.append(record)
    save_apply_history(history)
    logger.info("[ApplyManager][投递记录] [{}] {} | {} | 结果={} | {}", 
                platform, job_name, company_name, "成功" if success else "失败", message)

    # Hermes 自进化：记录投递经验
    try:
        from agent.hermes_memory import get_hermes_memory
        hm = get_hermes_memory()
        hm.record_experience(
            action_type="apply",
            success=success,
            result_summary=f"{'成功' if success else '失败'}: {message[:100]}",
            platform=platform,
            input_params={
                "job_name": job_name,
                "company_name": company_name,
                "platform": platform,
            },
            result_detail={
                "greeting": greeting[:200],
                "message": message,
            },
            context={
                "platform_job_id": str(platform_job_id)[:50],
            }
        )
        # 检查是否需要自动触发反思
        from config import HERMES_AUTO_REFLECT_THRESHOLD
        if HERMES_AUTO_REFLECT_THRESHOLD > 0:
            stats = hm.get_statistics()
            apply_count = stats.get("by_action", {}).get("apply", {}).get("total", 0)
            if apply_count > 0 and apply_count % HERMES_AUTO_REFLECT_THRESHOLD == 0:
                logger.info("[ApplyManager] Hermes 自动反思触发: 已累积 {} 条投递经验", apply_count)
                hm.reflect()
    except Exception as e:
        logger.warning("[ApplyManager] Hermes 经验记录失败: {}", e)


def generate_greeting(job: JobItem, resume_text: str, match_score: float = 0) -> str:
    """根据岗位信息和简历内容生成个性化的打招呼消息。
    
    优先级：
    1. 如果有 Hermes 中高反馈的成功模板，优先参考其风格
    2. 否则使用基于技能关键词匹配的模板
    """
    logger.debug("[ApplyManager] 生成问候语: job={}, company={}, match_score={:.2f}", 
                job.job_name, job.company_name, match_score)
    
    skills_keywords = extract_keywords_from_resume(resume_text)
    
    # 提取技能关键词匹配
    matched_skills = []
    job_text = f"{job.job_name} {job.requirements or ''} {job.responsibilities or ''}"
    for skill in skills_keywords:
        if skill.lower() in job_text.lower():
            matched_skills.append(skill)
    
    logger.debug("[ApplyManager] 技能匹配: 简历技能={}, 岗位匹配={}", 
                skills_keywords, matched_skills)
    
    # 尝试从 Hermes 获取历史成功招呼语经验
    hermes_style_hint = _get_hermes_greeting_insight(job, skills_keywords)
    
    if hermes_style_hint:
        # 基于 Hermes 历史成功经验生成招呼语
        greeting = _build_hermes_inspired_greeting(job, matched_skills, hermes_style_hint, match_score)
        logger.info("[ApplyManager] 使用 Hermes 历史经验生成问候语")
    elif matched_skills:
        skills_str = "、".join(matched_skills[:3])
        greeting = (
            f"您好，我对{job.job_name}这个岗位很感兴趣。"
            f"我在{skills_str}方面有丰富的经验，与岗位要求非常匹配。"
            f"期待能有机会进一步沟通！"
        )
    else:
        greeting = (
            f"您好，我对{job.job_name}这个岗位很感兴趣。"
            f"我有相关的技术背景和项目经验，希望能有机会进一步沟通。"
        )
    
    logger.debug("[ApplyManager] 问候语生成完毕: {}", greeting[:80])
    return greeting


def _get_hermes_greeting_insight(job: JobItem, skills: list) -> dict:
    """从 Hermes 获取招呼语相关的历史成功经验
    
    返回包含成功招呼语风格提示的字典，如果无可用数据则返回空字典
    """
    try:
        from agent.hermes_memory import get_hermes_memory
        hm = get_hermes_memory()
        
        # 构建查询上下文
        context = f"greeting {job.job_name} {job.company_name} {' '.join(skills)}"
        
        # 查找相似经验（招呼语相关）
        similar = hm.find_similar_experiences("apply", context, top_k=5)
        
        # 筛选成功的、有用户正向反馈的经验
        successful = []
        for exp in similar:
            if exp.get("success") and exp.get("user_feedback") in ("positive", None):
                detail = exp.get("result_detail", {})
                greeting_text = detail.get("greeting", "")
                if greeting_text:
                    successful.append({
                        "greeting": greeting_text,
                        "feedback": exp.get("user_feedback"),
                        "job_name": exp.get("input_params", {}).get("job_name", ""),
                        "similarity": exp.get("similarity_score", 0),
                    })
        
        if successful:
            logger.info("[ApplyManager] Hermes 招呼语洞察: 找到 {} 条历史成功模板", len(successful))
            return {
                "has_history": True,
                "successful_examples": successful[:3],
                "count": len(successful),
            }
        else:
            logger.debug("[ApplyManager] Hermes 招呼语洞察: 无历史成功模板")
            return {}
            
    except Exception as e:
        logger.warning("[ApplyManager] Hermes 招呼语洞察查询失败: {}", e)
        return {}


def _build_hermes_inspired_greeting(job: JobItem, matched_skills: list, 
                                     hermes_hint: dict, match_score: float) -> str:
    """基于 Hermes 历史成功经验构建招呼语"""
    examples = hermes_hint.get("successful_examples", [])
    
    # 分析历史成功模板的风格特征
    has_concrete_skills = any("经验" in ex.get("greeting", "") for ex in examples)
    uses_exclamation = any("！" in ex.get("greeting", "") for ex in examples)
    
    logger.debug("[ApplyManager] 历史模板分析: 具体技能={}, 感叹语气={}", 
                has_concrete_skills, uses_exclamation)
    
    if matched_skills:
        skills_str = "、".join(matched_skills[:3])
        
        # 根据历史风格调整
        if has_concrete_skills and uses_exclamation:
            # 历史成功模板偏"具体技能+积极语气"
            greeting = (
                f"您好！看到贵司的{job.job_name}岗位，非常感兴趣。"
                f"我在{skills_str}方面有丰富的实战经验，与岗位要求高度匹配。"
                f"期待与您进一步沟通！"
            )
        elif has_concrete_skills:
            # 历史成功模板偏"具体技能+正式语气"
            greeting = (
                f"您好，我对{job.job_name}岗位很感兴趣。"
                f"我在{skills_str}方面有丰富的项目经验，和贵司的岗位要求比较匹配。"
                f"希望能有机会深入交流。"
            )
        else:
            # 历史成功模板偏简洁风格
            greeting = (
                f"您好，看到贵司在招{job.job_name}，我在{skills_str}方面经验丰富。"
                f"期待能有机会沟通，谢谢！"
            )
    else:
        greeting = (
            f"您好，我对{job.job_name}这个岗位很感兴趣。"
            f"我有相关的技术背景和项目经验，希望能有机会进一步沟通。"
        )
    
    logger.debug("[ApplyManager] Hermes风格问候语生成完毕")
    return greeting


def extract_keywords_from_resume(resume_text: str) -> List[str]:
    """从简历中提取技能关键词"""
    common_skills = [
        "Python", "Java", "JavaScript", "Go", "C++", "Rust",
        "React", "Vue", "Node.js", "Spring", "Django", "Flask", "FastAPI",
        "TensorFlow", "PyTorch", "机器学习", "深度学习", "NLP", "大模型", "LLM",
        "MySQL", "PostgreSQL", "MongoDB", "Redis", "Kafka", "RabbitMQ",
        "Docker", "Kubernetes", "AWS", "阿里云", "Linux", "Git",
        "数据分析", "数据挖掘", "SQL", "Spark", "Hadoop", "Flink",
        "AI", "人工智能", "RAG", "Agent", "LangChain",
    ]
    matched = []
    resume_lower = resume_text.lower()
    for skill in common_skills:
        if skill.lower() in resume_lower:
            matched.append(skill)
    logger.info("[ApplyManager] 简历关键词提取: 扫描{}技能词, 命中{}个 -> {}", 
               len(common_skills), len(matched), matched)
    return matched


def get_apply_statistics() -> Dict:
    """获取投递统计信息"""
    history = load_apply_history()
    total = len(history)
    success = sum(1 for h in history if h.get("success"))
    failed = total - success
    
    # 按日期统计
    by_date = {}
    for h in history:
        date = h.get("applied_at", "")[:10]
        by_date[date] = by_date.get(date, 0) + 1
    
    logger.info("[ApplyManager] 投递统计: 总计={}, 成功={}, 失败={}, 日期分布={}", 
               total, success, failed, by_date)
    
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "by_date": by_date,
        "recent": history[-10:] if history else []
    }
