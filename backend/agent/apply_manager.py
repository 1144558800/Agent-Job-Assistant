# -*- coding: utf-8 -*-
"""
投递管理器 - 批量投递、招呼语生成、投递记录
"""
import time
import json
import random
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from loguru import logger

import config
from agent.guardrails import check_rate_limit, audit_content, sanitize_greeting, log_audit

# 投递记录目录
APPLY_DIR = config.BASE_DIR / "data" / "applies"
APPLY_DIR.mkdir(parents=True, exist_ok=True)

# 招呼语文案池
DEFAULT_GREETINGS = [
    "您好，我对贵公司的{job_name}岗位很感兴趣，我有{experience}年的相关工作经验，希望能有机会进一步沟通。",
    "您好，看到贵司在招聘{job_name}，我的技能和经验与该岗位高度匹配，期待您的回复。",
    "您好，我仔细阅读了{job_name}的职位描述，自认为非常符合要求，希望能详细聊聊。",
    "您好，我对{company}的{job_name}岗位非常感兴趣，我有相关的项目经验和技能储备，希望能有机会面试。",
    "您好，关注贵司已久，看到{job_name}开放招聘，我的技术栈与该岗位完美匹配，期待进一步沟通。",
]


class ApplyManager:
    """投递管理器"""

    def __init__(self):
        self._records: Dict[str, list] = {}

    def generate_greeting(self, job: dict, resume_text: str = "", hermes_insights: list = None) -> str:
        """
        生成招呼语
        有简历时基于简历生成，无简历时使用模板
        hermes_insights: Hermes 自进化记忆中的历史高效模板参考
        """
        job_name = job.get("job_name", "")
        company = job.get("company_name", "")
        experience = "3"  # 默认值

        if resume_text:
            greeting = self._generate_personalized_greeting(job, resume_text, hermes_insights)
        else:
            greeting = random.choice(DEFAULT_GREETINGS).format(
                job_name=job_name or "该岗位",
                company=company or "贵公司",
                experience=experience,
            )

        # 安全审查
        greeting = sanitize_greeting(greeting)
        logger.info("[Apply] 招呼语已生成: {}...", greeting[:50])
        return greeting

    def _generate_personalized_greeting(self, job: dict, resume_text: str, hermes_insights: list = None) -> str:
        """
        基于简历生成个性化招呼语
        使用 AI 分析简历和岗位，生成自然的打招呼内容
        同时参考 Hermes 记忆中的历史高效招呼语模板
        """
        try:
            from openai import OpenAI
            client = OpenAI(api_key=config.AI_API_KEY, base_url=config.AI_API_BASE)

            job_name = job.get("job_name", "")
            company = job.get("company_name", "")
            requirements = job.get("requirements", "")

            # 构建 Hermes 历史参考
            hermes_hint = ""
            if hermes_insights:
                high_ctr = [i for i in hermes_insights if i.get("ctr", 0) > 0.5]
                if high_ctr:
                    patterns = [i.get("pattern", "") for i in high_ctr[:3] if i.get("pattern")]
                    if patterns:
                        hermes_hint = "\n\n历史高回复率招呼语特征参考（请融入你的生成中）：\n" + "\n".join(
                            f"- {p}" for p in patterns
                        )

            prompt = f"""请根据以下信息生成一段简洁自然的打招呼消息（50-80字）：

目标岗位：{job_name}
公司：{company}
岗位要求：{requirements}

我的简历摘要：{resume_text[:1000]}
{hermes_hint}

要求：
1. 语气自然真诚，不要过于模板化
2. 突出与岗位的匹配度
3. 不要包含手机号、邮箱等联系方式
4. 纯文本，不要 Markdown 格式
5. 控制在 80 字以内"""

            response = client.chat.completions.create(
                model=config.AI_MODEL,
                messages=[
                    {"role": "system", "content": "你是一个专业的求职顾问，擅长写简洁真诚的打招呼消息。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
                max_tokens=200,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"[Apply] AI 生成招呼语失败，使用默认模板: {e}")
            return random.choice(DEFAULT_GREETINGS).format(
                job_name=job.get("job_name", "该岗位"),
                company=job.get("company_name", "贵公司"),
                experience="3",
            )

    def auto_apply(self, jobs: List[dict], thread_id: str, max_count: int = 30) -> List[dict]:
        """
        批量自动投递
        返回: [{job, success, message, greeting}]
        """
        results = []
        applied_count = 0

        for job in jobs:
            # 频率检查
            if not check_rate_limit("apply"):
                logger.warning("[Apply] 频率限制，停止投递")
                results.append({
                    "job": job,
                    "success": False,
                    "message": "已达到小时投递上限",
                })
                break

            if applied_count >= max_count:
                break

            try:
                greeting = self.generate_greeting(job)

                if not audit_content(greeting):
                    results.append({
                        "job": job,
                        "success": False,
                        "message": "招呼语包含敏感内容",
                    })
                    continue

                # 记录投递
                self._record_apply(job, greeting, thread_id)
                applied_count += 1

                results.append({
                    "job": job,
                    "success": True,
                    "message": "投递成功",
                    "greeting": greeting,
                })

                # 审计日志
                log_audit("auto_apply", {
                    "job_name": job.get("job_name", ""),
                    "company": job.get("company_name", ""),
                    "platform": job.get("platform", ""),
                }, True, thread_id)

                # 随机延迟 2-5 秒，模拟真人行为
                delay = random.uniform(2, 5)
                logger.info("[Apply] 投递完成，等待 {:.1f}s ...", delay)
                time.sleep(delay)

            except Exception as e:
                logger.error(f"[Apply] 投递异常: {e}")
                results.append({
                    "job": job,
                    "success": False,
                    "message": str(e),
                })
                log_audit("auto_apply", {
                    "job_name": job.get("job_name", ""),
                    "company": job.get("company_name", ""),
                    "error": str(e),
                }, False, thread_id)

        logger.info(f"[Apply] 批量投递完成: {applied_count}/{len(jobs)}")
        return results

    def auto_communicate(self, jobs: List[dict], thread_id: str, message_template: str = "") -> List[dict]:
        """
        批量自动沟通（打招呼）
        返回: [{job, success, message, greeting}]
        """
        results = []
        communicated_count = 0

        for job in jobs:
            if not check_rate_limit("communicate"):
                logger.warning("[Apply] 沟通频率限制")
                results.append({
                    "job": job,
                    "success": False,
                    "message": "已达到小时沟通上限",
                })
                break

            try:
                greeting = message_template if message_template else self.generate_greeting(job)
                greeting = sanitize_greeting(greeting)

                if not audit_content(greeting):
                    continue

                self._record_communicate(job, greeting, thread_id)
                communicated_count += 1

                results.append({
                    "job": job,
                    "success": True,
                    "message": "沟通消息已发送",
                    "greeting": greeting,
                })

                log_audit("auto_communicate", {
                    "job_name": job.get("job_name", ""),
                    "company": job.get("company_name", ""),
                }, True, thread_id)

                delay = random.uniform(3, 6)
                time.sleep(delay)

            except Exception as e:
                logger.error(f"[Apply] 沟通异常: {e}")
                results.append({
                    "job": job,
                    "success": False,
                    "message": str(e),
                })

        logger.info(f"[Apply] 批量沟通完成: {communicated_count}/{len(jobs)}")
        return results

    def _record_apply(self, job: dict, greeting: str, thread_id: str):
        """记录投递"""
        record = {
            "time": datetime.now().isoformat(),
            "thread_id": thread_id,
            "type": "apply",
            "job_name": job.get("job_name", ""),
            "company": job.get("company_name", ""),
            "platform": job.get("platform", ""),
            "greeting": greeting,
        }
        self._save_record(record)

    def _record_communicate(self, job: dict, greeting: str, thread_id: str):
        """记录沟通"""
        record = {
            "time": datetime.now().isoformat(),
            "thread_id": thread_id,
            "type": "communicate",
            "job_name": job.get("job_name", ""),
            "company": job.get("company_name", ""),
            "greeting": greeting,
        }
        self._save_record(record)

    def _save_record(self, record: dict):
        """保存投递记录到文件"""
        try:
            date_str = datetime.now().strftime("%Y-%m-%d")
            record_file = APPLY_DIR / f"apply_{date_str}.jsonl"
            with open(record_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"[Apply] 记录保存失败: {e}")

    def get_records(self, date_str: str = "") -> list:
        """获取投递记录"""
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        record_file = APPLY_DIR / f"apply_{date_str}.jsonl"
        if not record_file.exists():
            return []

        records = []
        try:
            with open(record_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        except Exception as e:
            logger.error(f"[Apply] 读取记录失败: {e}")

        return records


# 全局单例
_apply_manager = None


def get_apply_manager() -> ApplyManager:
    global _apply_manager
    if _apply_manager is None:
        _apply_manager = ApplyManager()
    return _apply_manager
