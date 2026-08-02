# -*- coding: utf-8 -*-
"""
Hermes 自进化记忆模块 - 经验记录、反思沉淀、策略优化

核心机制：
1. 经验记录：自动记录每次关键操作的输入、输出、成功/失败状态
2. 反思沉淀：定期调用 AI 对积累的经验做总结，提炼有效/无效模式
3. 策略优化：根据反思结果，生成可执行的策略调整建议
4. 相似经验检索：基于 FAISS 向量库查找与当前场景相似的历史经验
"""
import os
import sys
import json
import time
import hashlib
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field, asdict
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 经验数据目录
EXPERIENCE_DIR = Path(__file__).resolve().parent.parent / "data" / "hermes"
EXPERIENCE_FILE = EXPERIENCE_DIR / "experiences.json"
INSIGHTS_FILE = EXPERIENCE_DIR / "insights.json"
REFLECTION_LOG_FILE = EXPERIENCE_DIR / "reflection_log.json"


@dataclass
class ExperienceRecord:
    """单条经验记录"""
    # 操作标识
    action_type: str          # 操作类型: search, apply, match, greeting, login, query
    platform: str = ""        # 平台名称（如 BOSS直聘、猎聘）
    
    # 输入参数
    input_params: Dict[str, Any] = field(default_factory=dict)
    
    # 操作结果
    success: bool = False     # 是否成功
    result_summary: str = ""  # 结果摘要
    result_detail: Dict[str, Any] = field(default_factory=dict)
    
    # 上下文
    context: Dict[str, Any] = field(default_factory=dict)
    
    # 时间戳
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    
    # 用户反馈（可选，用于强化学习）
    user_feedback: Optional[str] = None  # positive, negative, neutral
    feedback_note: Optional[str] = None  # 用户备注
    
    # 唯一标识
    record_id: str = ""


@dataclass
class Insight:
    """反思沉淀后生成的洞察"""
    insight_id: str = ""
    category: str = ""           # 分类: search_strategy, apply_strategy, greeting_style, platform_preference, timing
    title: str = ""              # 洞察标题
    description: str = ""        # 详细描述
    confidence: float = 0.0      # 置信度 0-1
    evidence_count: int = 0      # 支持此洞察的经验条数
    suggestion: str = ""         # 策略调整建议
    related_experience_ids: List[str] = field(default_factory=list)
    created_at: str = ""
    is_active: bool = True       # 是否仍然有效


@dataclass
class ReflectionLog:
    """反思日志"""
    reflection_id: str = ""
    triggered_at: str = ""
    experience_count: int = 0
    new_insights: List[Dict] = field(default_factory=list)
    updated_insights: List[Dict] = field(default_factory=list)
    summary: str = ""


class HermesMemory:
    """Hermes 自进化记忆管理器"""

    def __init__(self, max_experiences: int = 500):
        self.max_experiences = max_experiences
        self._experiences: List[ExperienceRecord] = []
        self._insights: List[Insight] = []
        self._reflection_logs: List[ReflectionLog] = []
        self._loaded = False

    # ========== 数据持久化 ==========

    def _ensure_loaded(self):
        """确保数据已加载"""
        if not self._loaded:
            self.load()

    def load(self):
        """从磁盘加载经验数据"""
        EXPERIENCE_DIR.mkdir(parents=True, exist_ok=True)
        
        # 加载经验记录
        if EXPERIENCE_FILE.exists():
            try:
                with open(EXPERIENCE_FILE, "r", encoding="utf-8") as f:
                    raw_list = json.load(f)
                self._experiences = [ExperienceRecord(**item) for item in raw_list]
                logger.info("[Hermes] 经验记录加载成功: {} 条", len(self._experiences))
            except Exception as e:
                logger.warning("[Hermes] 经验记录加载失败: {}", e)
                self._experiences = []
        else:
            self._experiences = []

        # 加载洞察
        if INSIGHTS_FILE.exists():
            try:
                with open(INSIGHTS_FILE, "r", encoding="utf-8") as f:
                    raw_list = json.load(f)
                self._insights = [Insight(**item) for item in raw_list]
                logger.info("[Hermes] 洞察加载成功: {} 条", len(self._insights))
            except Exception as e:
                logger.warning("[Hermes] 洞察加载失败: {}", e)
                self._insights = []
        else:
            self._insights = []

        # 加载反思日志
        if REFLECTION_LOG_FILE.exists():
            try:
                with open(REFLECTION_LOG_FILE, "r", encoding="utf-8") as f:
                    raw_list = json.load(f)
                self._reflection_logs = [ReflectionLog(**item) for item in raw_list]
            except Exception as e:
                logger.warning("[Hermes] 反思日志加载失败: {}", e)
                self._reflection_logs = []
        else:
            self._reflection_logs = []

        self._loaded = True

    def save(self):
        """保存经验数据到磁盘"""
        EXPERIENCE_DIR.mkdir(parents=True, exist_ok=True)
        
        with open(EXPERIENCE_FILE, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in self._experiences], f, ensure_ascii=False, indent=2)
        
        with open(INSIGHTS_FILE, "w", encoding="utf-8") as f:
            json.dump([asdict(i) for i in self._insights], f, ensure_ascii=False, indent=2)
        
        with open(REFLECTION_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in self._reflection_logs], f, ensure_ascii=False, indent=2)
        
        logger.info("[Hermes] 数据已保存: {} 条经验, {} 条洞察, {} 条反思日志",
                   len(self._experiences), len(self._insights), len(self._reflection_logs))

    # ========== 经验记录 ==========

    def record_experience(
        self,
        action_type: str,
        success: bool,
        result_summary: str = "",
        platform: str = "",
        input_params: Optional[Dict] = None,
        result_detail: Optional[Dict] = None,
        context: Optional[Dict] = None,
    ) -> str:
        """记录一条操作经验
        
        返回记录ID
        """
        self._ensure_loaded()
        
        record_id = hashlib.md5(
            f"{action_type}_{time.time()}_{len(self._experiences)}".encode()
        ).hexdigest()[:12]
        
        record = ExperienceRecord(
            record_id=record_id,
            action_type=action_type,
            platform=platform,
            input_params=input_params or {},
            success=success,
            result_summary=result_summary,
            result_detail=result_detail or {},
            context=context or {},
        )
        
        self._experiences.append(record)
        
        # 控制经验数量上限
        if len(self._experiences) > self.max_experiences:
            self._experiences = self._experiences[-self.max_experiences:]
        
        # 新增经验后标记 FAISS 索引过期
        self._invalidate_faiss_index()
        
        # 自动保存
        self.save()
        
        logger.info("[Hermes] 经验记录: [{}] {} | {} | 成功={}",
                   record_id, action_type, platform, success)
        
        return record_id

    def record_user_feedback(self, record_id: str, feedback: str, note: str = ""):
        """记录用户对某条经验的反馈"""
        self._ensure_loaded()
        
        for exp in self._experiences:
            if exp.record_id == record_id:
                exp.user_feedback = feedback
                exp.feedback_note = note
                self.save()
                logger.info("[Hermes] 用户反馈已记录: [{}] feedback={}", record_id, feedback)
                return True
        
        logger.warning("[Hermes] 未找到经验记录: {}", record_id)
        return False

    # ========== 经验查询 ==========

    def get_recent_experiences(self, count: int = 20, action_type: Optional[str] = None) -> List[Dict]:
        """获取最近的经验记录"""
        self._ensure_loaded()
        
        filtered = self._experiences
        if action_type:
            filtered = [e for e in filtered if e.action_type == action_type]
        
        # 取最近的 count 条
        recent = filtered[-count:]
        logger.debug("[Hermes] 查询最近经验: action_type={}, 总数={}, 返回={}", 
                    action_type or "全部", len(filtered), len(recent))
        return [asdict(e) for e in recent]

    def get_statistics(self) -> Dict:
        """获取经验统计数据"""
        self._ensure_loaded()
        
        total = len(self._experiences)
        logger.debug("[Hermes] 查询经验统计: 总数={}", total)
        if total == 0:
            return {"total": 0, "by_action": {}, "success_rate": 0, "by_platform": {}}
        
        by_action = {}
        by_platform = {}
        success_count = 0
        
        for e in self._experiences:
            # 按操作类型统计
            if e.action_type not in by_action:
                by_action[e.action_type] = {"total": 0, "success": 0}
            by_action[e.action_type]["total"] += 1
            if e.success:
                by_action[e.action_type]["success"] += 1
            
            # 按平台统计
            if e.platform:
                if e.platform not in by_platform:
                    by_platform[e.platform] = {"total": 0, "success": 0}
                by_platform[e.platform]["total"] += 1
                if e.success:
                    by_platform[e.platform]["success"] += 1
            
            if e.success:
                success_count += 1
        
        # 计算各操作类型的成功率
        for k, v in by_action.items():
            v["success_rate"] = round(v["success"] / v["total"], 2) if v["total"] > 0 else 0
        
        for k, v in by_platform.items():
            v["success_rate"] = round(v["success"] / v["total"], 2) if v["total"] > 0 else 0
        
        return {
            "total": total,
            "by_action": by_action,
            "by_platform": by_platform,
            "success_rate": round(success_count / total, 2),
            "insight_count": len(self._insights),
        }

    # ========== 反思沉淀 ==========

    def check_consecutive_failures(self, action_type: str = None, threshold: int = 3) -> bool:
        """检查是否存在连续失败，若达到阈值则自动触发反思
        
        参数:
            action_type: 操作类型筛选，None 表示检查所有类型
            threshold: 连续失败阈值，默认3次
        
        返回 True 表示已触发反思
        """
        self._ensure_loaded()
        
        # 获取最近的经验
        recent = self._experiences[-20:]  # 只检查最近20条
        
        consecutive_fails = 0
        for exp in reversed(recent):
            if action_type and exp.action_type != action_type:
                continue
            if not exp.success:
                consecutive_fails += 1
            else:
                break  # 遇到成功就重置
        
        logger.info("[Hermes] 连续失败检测: action_type={}, 连续失败={}, 阈值={}",
                   action_type or "全部", consecutive_fails, threshold)
        
        if consecutive_fails >= threshold:
            logger.warning("[Hermes] 连续失败次数({})达到阈值({})，自动触发反思！",
                         consecutive_fails, threshold)
            try:
                result = self.reflect()
                logger.info("[Hermes] 事件驱动反思完成: {}", 
                           "成功" if result.get("success") else "失败")
                return result.get("success", False)
            except Exception as e:
                logger.error("[Hermes] 事件驱动反思异常: {}", e)
                return False
        
        return False

    def reflect(self) -> Dict:
        """触发 AI 反思：分析历史经验，生成新的洞察和策略建议
        
        使用 DeepSeek API 进行智能分析
        """
        self._ensure_loaded()
        
        total = len(self._experiences)
        if total < 5:
            logger.info("[Hermes] 经验不足（{} 条），跳过反思（需要至少5条）", total)
            return {
                "success": False,
                "message": f"经验数据不足（当前 {total} 条，需要至少 5 条）",
                "experience_count": total,
            }
        
        # 构建反思提示词
        experiences_text = self._build_reflection_prompt()
        
        reflection_prompt = f"""你是一个求职策略分析专家。请分析以下 Agent 求职筛选助手的操作历史记录，提炼出可执行的策略优化建议。

=== 操作历史记录 ===
{experiences_text}

请从以下维度进行分析，并以 JSON 格式返回：

1. **搜索策略优化**: 哪些关键词/城市组合产生了更多有效岗位？
2. **投递策略优化**: 哪些类型岗位投递成功率更高？什么时间投递效果好？
3. **招呼语优化**: 当前招呼语模板效果如何？如何改进？
4. **平台偏好**: 哪些平台对当前用户更有效？
5. **整体模式**: 发现的其他有意义的模式

返回格式（严格 JSON）：
{{
    "insights": [
        {{
            "category": "search_strategy|apply_strategy|greeting_style|platform_preference|timing|general",
            "title": "洞察标题（简洁）",
            "description": "详细描述你发现的模式",
            "confidence": 0.0-1.0,
            "evidence_count": 支持此结论的经验条数,
            "suggestion": "具体的、可执行的策略调整建议"
        }}
    ],
    "summary": "整体反思总结（200字以内）",
    "recommended_actions": ["建议执行的具体操作1", "建议执行的具体操作2"]
}}

注意：
- 只基于实际数据做分析，不要编造
- 如果数据不足以支撑某个维度的结论，可以跳过
- 建议要具体、可执行
- 确保返回的是合法 JSON"""

        # 调用 DeepSeek AI 进行反思
        try:
            ai_result = self._call_ai_reflection(reflection_prompt)
            
            if not ai_result:
                return {
                    "success": False,
                    "message": "AI 反思调用失败",
                    "experience_count": total,
                }
            
            # 解析 AI 返回的洞察
            new_insights = []
            for item in ai_result.get("insights", []):
                insight = Insight(
                    insight_id=hashlib.md5(
                        f"{item.get('category','')}_{item.get('title','')}_{time.time()}".encode()
                    ).hexdigest()[:12],
                    category=item.get("category", "general"),
                    title=item.get("title", ""),
                    description=item.get("description", ""),
                    confidence=item.get("confidence", 0.5),
                    evidence_count=item.get("evidence_count", 0),
                    suggestion=item.get("suggestion", ""),
                    created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                    is_active=True,
                )
                new_insights.append(insight)
            
            # 保存洞察
            self._insights.extend(new_insights)
            
            # 控制洞察数量（保留最近200条）
            if len(self._insights) > 200:
                self._insights = self._insights[-200:]
            
            # 记录反思日志
            reflection_log = ReflectionLog(
                reflection_id=hashlib.md5(f"reflect_{time.time()}".encode()).hexdigest()[:12],
                triggered_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                experience_count=total,
                new_insights=[asdict(i) for i in new_insights],
                summary=ai_result.get("summary", ""),
            )
            self._reflection_logs.append(reflection_log)
            
            self.save()
            
            logger.info("[Hermes] 反思完成: 生成 {} 条新洞察, 总计 {} 条洞察",
                       len(new_insights), len(self._insights))
            
            # 洞察验证：检查已有洞察是否与最近经验矛盾
            validation = self.validate_insights()
            if validation["downgraded"] > 0 or validation["deactivated"] > 0:
                logger.info("[Hermes] 洞察验证: 降级{}条, 停用{}条", 
                           validation["downgraded"], validation["deactivated"])
            
            return {
                "success": True,
                "message": f"反思完成，基于 {total} 条经验生成 {len(new_insights)} 条洞察",
                "experience_count": total,
                "new_insights": [asdict(i) for i in new_insights],
                "summary": ai_result.get("summary", ""),
                "recommended_actions": ai_result.get("recommended_actions", []),
            }
            
        except Exception as e:
            logger.error("[Hermes] 反思异常: type={}, msg={}", type(e).__name__, str(e))
            import traceback
            logger.error("[Hermes] 反思异常堆栈:\n{}", traceback.format_exc())
            return {
                "success": False,
                "message": f"反思过程出错: {str(e)}",
                "experience_count": total,
            }

    def _build_reflection_prompt(self) -> str:
        """构建反思用的经验摘要文本
        
        用户正向反馈（positive）的经验会被标记为[高价值]，在反思时获得更多关注
        """
        self._ensure_loaded()
        
        lines = []
        
        # 统计用户反馈
        positive_count = sum(1 for e in self._experiences if e.user_feedback == "positive")
        negative_count = sum(1 for e in self._experiences if e.user_feedback == "negative")
        if positive_count > 0 or negative_count > 0:
            lines.append(f"## 用户反馈概览")
            lines.append(f"正向反馈: {positive_count} 条, 负向反馈: {negative_count} 条")
            lines.append("注意：[高价值] 标记的经验代表用户明确认可，应重点参考")
        
        # 按操作类型分组
        by_action = {}
        for e in self._experiences:
            if e.action_type not in by_action:
                by_action[e.action_type] = []
            by_action[e.action_type].append(e)
        
        for action_type, exps in by_action.items():
            lines.append(f"\n## {action_type} 操作（共 {len(exps)} 条）")
            
            # 成功率统计
            success_count = sum(1 for e in exps if e.success)
            positive_in_type = sum(1 for e in exps if e.user_feedback == "positive")
            negative_in_type = sum(1 for e in exps if e.user_feedback == "negative")
            
            stats_parts = [f"成功率: {success_count}/{len(exps)} = {round(success_count/len(exps)*100, 1)}%"]
            if positive_in_type > 0:
                stats_parts.append(f"用户认可: {positive_in_type}条")
            if negative_in_type > 0:
                stats_parts.append(f"用户不满意: {negative_in_type}条")
            lines.append(" | ".join(stats_parts))
            
            # 先展示有正向反馈的高价值经验，再展示其他
            high_value = [e for e in exps if e.user_feedback == "positive"]
            other = [e for e in exps if e.user_feedback != "positive"]
            
            # 展示高价值经验（最多5条）
            for e in high_value[-5:]:
                input_str = json.dumps(e.input_params, ensure_ascii=False)[:150]
                result_str = e.result_summary[:100]
                lines.append(
                    f"  [高价值] [{e.timestamp}] {action_type} | 平台={e.platform} | "
                    f"入参={input_str} | 结果={result_str} | 用户认可"
                )
            
            # 展示其他经验（最多5条，不含高价值已展示的）
            remaining = min(5 - len(high_value[-5:]), len(other))
            if remaining > 0:
                for e in other[-remaining:]:
                    input_str = json.dumps(e.input_params, ensure_ascii=False)[:150]
                    result_str = e.result_summary[:100]
                    feedback_str = ""
                    if e.user_feedback == "negative":
                        feedback_str = " [用户不满意]"
                    elif e.feedback_note:
                        feedback_str = f" [备注: {e.feedback_note[:50]}]"
                    lines.append(
                        f"  [{e.timestamp}] {'成功' if e.success else '失败'} | "
                        f"平台={e.platform} | 入参={input_str} | 结果={result_str}{feedback_str}"
                    )
        
        # 洞察历史（最近活跃的）
        if self._insights:
            lines.append("\n## 已有洞察")
            active_insights = [i for i in self._insights if i.is_active][-5:]
            for ins in active_insights:
                lines.append(f"  [{ins.category}] {ins.title} (置信度: {ins.confidence})")
                lines.append(f"    建议: {ins.suggestion}")
        
        result = "\n".join(lines)
        logger.info("[Hermes] 反思 Prompt 构建完成: 长度={}, 高价值经验={}条", 
                   len(result), positive_count)
        return result

    def _call_ai_reflection(self, prompt: str) -> Optional[Dict]:
        """调用 DeepSeek AI 进行反思分析"""
        try:
            from langchain_openai import ChatOpenAI
            from config import AI_API_KEY, AI_API_BASE, AI_MODEL
            
            llm = ChatOpenAI(
                model=AI_MODEL,
                api_key=AI_API_KEY,
                base_url=AI_API_BASE,
                temperature=0.3,
                streaming=False,
            )
            
            from langchain_core.messages import SystemMessage, HumanMessage
            
            messages = [
                SystemMessage(content="你是一个数据分析专家，请严格按 JSON 格式返回分析结果。"),
                HumanMessage(content=prompt),
            ]
            
            response = llm.invoke(messages)
            content = response.content
            
            logger.info("[Hermes] AI 反思原始响应长度: {}", len(content))
            
            # 提取 JSON（处理 markdown 代码块包裹的情况）
            json_str = content.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()
            
            result = json.loads(json_str)
            return result
            
        except json.JSONDecodeError as e:
            logger.error("[Hermes] AI 反思返回的 JSON 解析失败: {} | 原始内容: {}", e, content[:500] if 'content' in dir() else 'N/A')
            return None
        except Exception as e:
            logger.error("[Hermes] AI 反思调用失败: type={}, msg={}", type(e).__name__, str(e))
            return None

    # ========== 洞察查询 ==========

    def get_active_insights(self, category: Optional[str] = None) -> List[Dict]:
        """获取当前活跃的策略洞察"""
        self._ensure_loaded()
        
        active = [i for i in self._insights if i.is_active]
        
        if category:
            active = [i for i in active if i.category == category]
        
        # 按置信度排序
        active.sort(key=lambda x: x.confidence, reverse=True)
        
        result = [asdict(i) for i in active]
        logger.info("[Hermes] 查询活跃洞察: category={}, 总数={}, 活跃={}",
                   category or "全部", len(self._insights), len(result))
        if result:
            for ins in result[:3]:
                logger.debug("[Hermes]   洞察: [{}] {} (置信度={})",
                           ins["category"], ins["title"], ins["confidence"])
        return result

    def get_latest_insight_summary(self) -> str:
        """获取最新洞察的文本摘要（用于注入 Agent System Prompt）"""
        self._ensure_loaded()
        
        active = [i for i in self._insights if i.is_active]
        if not active:
            logger.debug("[Hermes] 洞察摘要: 无活跃洞察")
            return ""
        
        # 取高置信度洞察
        high_confidence = [i for i in active if i.confidence >= 0.6]
        if not high_confidence:
            high_confidence = active[-3:]
        
        lines = []
        for ins in high_confidence[:5]:
            lines.append(f"- [{ins.category}] {ins.title}: {ins.suggestion}")
        
        summary = "\n".join(lines)
        logger.info("[Hermes] 洞察摘要: 活跃洞察={}, 高置信度={}, 摘要长度={}",
                   len(active), len(high_confidence), len(summary))
        return summary

    def deactivate_insight(self, insight_id: str) -> bool:
        """停用某条洞察"""
        self._ensure_loaded()
        
        for ins in self._insights:
            if ins.insight_id == insight_id:
                ins.is_active = False
                self.save()
                logger.info("[Hermes] 洞察已停用: [{}] {}", insight_id, ins.title)
                return True
        
        return False

    def validate_insights(self) -> Dict:
        """验证现有洞察的有效性：检查最近经验是否与洞察矛盾
        
        如果洞察的建议与最近经验趋势相矛盾，自动降低置信度或停用
        
        返回验证结果摘要
        """
        self._ensure_loaded()
        
        active = [i for i in self._insights if i.is_active]
        if not active:
            logger.debug("[Hermes] 洞察验证: 无活跃洞察，跳过")
            return {"validated": 0, "downgraded": 0, "deactivated": 0}
        
        recent = self._experiences[-20:]  # 最近20条经验
        if len(recent) < 5:
            logger.debug("[Hermes] 洞察验证: 最近经验不足5条，跳过")
            return {"validated": 0, "downgraded": 0, "deactivated": 0}
        
        downgraded = 0
        deactivated = 0
        
        for ins in active:
            # 根据洞察类别检查相关经验
            if ins.category == "platform_preference":
                # 检查推荐平台的最近成功率
                platform_name = self._extract_platform_from_insight(ins)
                if platform_name:
                    platform_exps = [e for e in recent if e.platform == platform_name]
                    if platform_exps:
                        fail_rate = sum(1 for e in platform_exps if not e.success) / len(platform_exps)
                        if fail_rate > 0.6 and len(platform_exps) >= 3:
                            # 该平台最近60%以上失败，降低置信度
                            old_conf = ins.confidence
                            ins.confidence = round(ins.confidence * 0.6, 2)
                            logger.warning("[Hermes] 洞察验证: [{}] {} 置信度降低 {:.2f}→{:.2f} (平台{}最近失败率{:.0%})",
                                         ins.insight_id[:8], ins.title, old_conf, ins.confidence, 
                                         platform_name, fail_rate)
                            downgraded += 1
                            
                            if ins.confidence < 0.3:
                                ins.is_active = False
                                deactivated += 1
                                logger.warning("[Hermes] 洞察验证: [{}] {} 置信度过低({:.2f})，已自动停用",
                                             ins.insight_id[:8], ins.title, ins.confidence)
            
            elif ins.category == "apply_strategy":
                # 检查投递策略是否仍然有效
                apply_exps = [e for e in recent if e.action_type == "apply"]
                if apply_exps:
                    fail_rate = sum(1 for e in apply_exps if not e.success) / len(apply_exps)
                    if fail_rate > 0.6 and len(apply_exps) >= 3:
                        old_conf = ins.confidence
                        ins.confidence = round(ins.confidence * 0.7, 2)
                        logger.warning("[Hermes] 洞察验证: [{}] {} 置信度降低 {:.2f}→{:.2f} (投递失败率{:.0%})",
                                     ins.insight_id[:8], ins.title, old_conf, ins.confidence, fail_rate)
                        downgraded += 1
                        
                        if ins.confidence < 0.3:
                            ins.is_active = False
                            deactivated += 1
                            logger.warning("[Hermes] 洞察验证: [{}] {} 置信度过低({:.2f})，已自动停用",
                                         ins.insight_id[:8], ins.title, ins.confidence)
            
            elif ins.category == "search_strategy":
                # 检查搜索策略是否仍然有效
                search_exps = [e for e in recent if e.action_type == "search"]
                if search_exps:
                    fail_rate = sum(1 for e in search_exps if not e.success) / len(search_exps)
                    if fail_rate > 0.5 and len(search_exps) >= 3:
                        old_conf = ins.confidence
                        ins.confidence = round(ins.confidence * 0.7, 2)
                        logger.warning("[Hermes] 洞察验证: [{}] {} 置信度降低 {:.2f}→{:.2f} (搜索失败率{:.0%})",
                                     ins.insight_id[:8], ins.title, old_conf, ins.confidence, fail_rate)
                        downgraded += 1
        
        if downgraded > 0:
            self.save()
            logger.info("[Hermes] 洞察验证完成: 检查{}条, 降级{}条, 停用{}条",
                       len(active), downgraded, deactivated)
        
        return {
            "validated": len(active),
            "downgraded": downgraded,
            "deactivated": deactivated,
        }

    def _extract_platform_from_insight(self, insight: Insight) -> Optional[str]:
        """从洞察描述中提取平台名称"""
        platforms = ["BOSS直聘", "猎聘", "前程无忧", "智联招聘", "boss", "liepin", "51job", "zhaopin"]
        combined = f"{insight.title} {insight.description} {insight.suggestion}"
        for p in platforms:
            if p in combined:
                return p
        return None

    # ========== 相似经验检索（基于 FAISS 语义检索） ==========

    def _get_embedding_service(self):
        """获取 Embedding 服务（延迟导入避免循环依赖）"""
        try:
            from rag.embeddings import EmbeddingService
            return EmbeddingService()
        except Exception as e:
            logger.warning("[Hermes] Embedding 服务初始化失败: {}", e)
            return None

    def _build_experience_text(self, exp: ExperienceRecord) -> str:
        """将经验记录转换为可用于语义检索的文本"""
        parts = [
            f"操作类型: {exp.action_type}",
            f"平台: {exp.platform}",
            f"结果: {'成功' if exp.success else '失败'}",
            f"摘要: {exp.result_summary}",
        ]
        if exp.input_params:
            parts.append(f"入参: {json.dumps(exp.input_params, ensure_ascii=False)}")
        if exp.user_feedback:
            parts.append(f"用户反馈: {exp.user_feedback}")
        return " | ".join(parts)

    def _ensure_faiss_index(self):
        """确保 FAISS 索引已初始化（用于经验语义检索）"""
        if not hasattr(self, '_exp_faiss_index') or self._exp_faiss_index is None:
            try:
                import numpy as np
                import faiss
                
                embed_service = self._get_embedding_service()
                if embed_service is None:
                    logger.warning("[Hermes] 无法获取 Embedding 服务，回退到关键词匹配")
                    return
                
                dim = embed_service.get_embedding_dimension()
                self._exp_faiss_index = faiss.IndexFlatL2(dim)
                self._exp_vectors = []  # 存储已索引的经验记录引用
                
                # 索引所有现有经验
                if self._experiences:
                    texts = [self._build_experience_text(e) for e in self._experiences]
                    vectors = embed_service.embed_texts(texts)
                    if vectors:
                        vec_array = np.array(vectors, dtype=np.float32)
                        self._exp_faiss_index.add(vec_array)
                        self._exp_vectors = list(self._experiences)
                        logger.info("[Hermes] FAISS 语义索引构建完成: {} 条经验", len(self._exp_vectors))
                
            except ImportError as e:
                logger.warning("[Hermes] FAISS/NumPy 导入失败，回退到关键词匹配: {}", e)
                self._exp_faiss_index = None
            except Exception as e:
                logger.warning("[Hermes] FAISS 索引初始化失败，回退到关键词匹配: {}", e)
                self._exp_faiss_index = None

    def _invalidate_faiss_index(self):
        """标记 FAISS 索引需要重建（新增经验后调用）"""
        if hasattr(self, '_exp_faiss_index'):
            self._exp_faiss_index = None
            self._exp_vectors = []
            logger.debug("[Hermes] FAISS 索引已标记为过期")

    def find_similar_experiences(self, action_type: str, context_text: str, top_k: int = 5) -> List[Dict]:
        """查找与当前场景相似的历史经验
        
        优先使用 FAISS 语义检索，如果不可用则回退到关键词匹配
        """
        self._ensure_loaded()
        
        # 筛选同类型操作
        same_type = [e for e in self._experiences if e.action_type == action_type]
        if not same_type:
            logger.debug("[Hermes] 相似经验查询: action_type={}, 无同类经验", action_type)
            return []
        
        # 尝试使用 FAISS 语义检索
        faiss_results = self._search_by_faiss(action_type, context_text, same_type, top_k)
        if faiss_results is not None:
            logger.info("[Hermes] 相似经验查询(FAISS语义): action_type={}, 同类经验={}, 返回={}",
                       action_type, len(same_type), len(faiss_results))
            return faiss_results
        
        # 回退到关键词匹配
        logger.info("[Hermes] 相似经验查询(关键词回退): action_type={}, 同类经验={}", 
                   action_type, len(same_type))
        return self._search_by_keywords(context_text, same_type, top_k)

    def _search_by_faiss(self, action_type: str, context_text: str, 
                         candidates: List[ExperienceRecord], top_k: int) -> Optional[List[Dict]]:
        """使用 FAISS 语义检索相似经验，失败返回 None"""
        try:
            import numpy as np
            
            self._ensure_faiss_index()
            if self._exp_faiss_index is None or not hasattr(self, '_exp_vectors'):
                return None
            
            embed_service = self._get_embedding_service()
            if embed_service is None:
                return None
            
            # 生成查询向量
            query_text = f"{action_type} {context_text}"
            query_vector = embed_service.embed_text(query_text)
            if query_vector is None:
                return None
            
            query_array = np.array([query_vector], dtype=np.float32)
            
            # FAISS 搜索
            search_k = min(top_k * 2, len(self._exp_vectors))
            if search_k == 0:
                return []
            
            distances, indices = self._exp_faiss_index.search(query_array, search_k)
            
            # 收集结果，只保留同类型候选
            results = []
            for dist, idx in zip(distances[0], indices[0]):
                if idx < 0 or idx >= len(self._exp_vectors):
                    continue
                exp = self._exp_vectors[idx]
                if exp not in candidates:
                    continue
                
                # 距离转相似度分数 (L2距离越小越相似)
                max_dist = max(distances[0]) if max(distances[0]) > 0 else 1.0
                similarity = 1.0 - (dist / max_dist) if max_dist > 0 else 1.0
                
                d = asdict(exp)
                d["similarity_score"] = round(max(0, similarity), 4)
                d["search_method"] = "faiss_semantic"
                results.append(d)
                
                if len(results) >= top_k:
                    break
            
            return results
            
        except Exception as e:
            logger.warning("[Hermes] FAISS 语义检索失败，回退关键词匹配: {}", e)
            return None

    def _search_by_keywords(self, context_text: str, 
                            candidates: List[ExperienceRecord], top_k: int) -> List[Dict]:
        """关键词匹配（回退方案）"""
        context_keywords = set(context_text.lower().split())
        
        scored = []
        for exp in candidates:
            exp_text = f"{exp.action_type} {exp.platform} {json.dumps(exp.input_params, ensure_ascii=False)} {exp.result_summary}"
            exp_keywords = set(exp_text.lower().split())
            
            # Jaccard 相似度 + 用户反馈加权
            if not context_keywords or not exp_keywords:
                score = 0
            else:
                intersection = context_keywords & exp_keywords
                union = context_keywords | exp_keywords
                score = len(intersection) / len(union) if union else 0
            
            # 用户正向反馈加权（+0.15）
            if exp.user_feedback == "positive":
                score += 0.15
            # 用户负向反馈降权（-0.1）
            elif exp.user_feedback == "negative":
                score -= 0.1
            
            scored.append((score, exp))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        
        results = []
        for score, exp in scored[:top_k]:
            d = asdict(exp)
            d["similarity_score"] = round(score, 4)
            d["search_method"] = "keyword_jaccard"
            results.append(d)
        
        logger.debug("[Hermes] 关键词匹配: 候选={}, 返回={}, 最高分={}",
                    len(candidates), len(results), 
                    round(scored[0][0], 4) if scored else 0)
        return results

    # ========== 策略建议 ==========

    def get_optimized_params(self, action_type: str, current_params: Dict) -> Dict:
        """基于历史经验，返回优化后的参数建议"""
        self._ensure_loaded()
        
        logger.debug("[Hermes] 策略优化查询: action_type={}, params_keys={}",
                    action_type, list(current_params.keys()))
        
        suggestions = {}
        
        # 查找同类操作的洞察
        category_map = {
            "search": "search_strategy",
            "apply": "apply_strategy",
            "greeting": "greeting_style",
        }
        category = category_map.get(action_type, "general")
        
        relevant_insights = [i for i in self._insights if i.category == category and i.is_active]
        
        if relevant_insights:
            suggestions["insights_applied"] = [
                {"title": i.title, "suggestion": i.suggestion} for i in relevant_insights[:3]
            ]
        
        # 查找相似经验中的成功案例
        context_text = json.dumps(current_params, ensure_ascii=False)
        similar = self.find_similar_experiences(action_type, context_text, top_k=3)
        successful = [s for s in similar if s.get("success")]
        if successful:
            suggestions["similar_successes"] = [
                {"result_summary": s.get("result_summary"), "similarity": s.get("similarity_score")}
                for s in successful
            ]
        
        return suggestions


# ========== 全局单例 ==========

_hermes_memory: Optional[HermesMemory] = None


def get_hermes_memory() -> HermesMemory:
    """获取 HermesMemory 全局单例"""
    global _hermes_memory
    if _hermes_memory is None:
        _hermes_memory = HermesMemory()
        _hermes_memory.load()
    return _hermes_memory
