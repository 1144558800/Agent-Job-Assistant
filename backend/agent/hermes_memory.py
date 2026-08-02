# -*- coding: utf-8 -*-
"""
Hermes 自进化记忆系统
核心功能：
1. 经验记录 - 记录每次投递/沟通的结果
2. 反思沉淀 - 定期分析经验，提取策略洞察
3. FAISS 语义检索 - 快速查找相似历史案例
4. 洞察验证 - 对新洞察进行AI验证
"""
import json
import time
import pickle
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from loguru import logger

import config

# 记忆存储目录
HERMES_DIR = config.BASE_DIR / "data" / "hermes"
HERMES_DIR.mkdir(parents=True, exist_ok=True)
EXPERIENCE_FILE = HERMES_DIR / "experiences.jsonl"
INSIGHT_FILE = HERMES_DIR / "insights.json"
INDEX_FILE = HERMES_DIR / "experience_index.faiss"
META_FILE = HERMES_DIR / "experience_meta.pkl"


class HermesMemory:
    """自进化记忆系统"""

    def __init__(self):
        self._experiences: List[dict] = []
        self._insights: List[dict] = []
        self._index = None
        self._meta: List[dict] = []
        self._embedder = None
        self._loaded = False

    def _ensure_loaded(self):
        """确保数据已加载"""
        if self._loaded:
            return
        self.load_all()
        self._loaded = True

    def _get_embedder(self):
        """获取嵌入模型（延迟加载）"""
        if self._embedder is None:
            try:
                from rag.embeddings import EmbeddingService
                self._embedder = EmbeddingService()
                logger.info("[Hermes] 嵌入模型已加载")
            except Exception as e:
                logger.warning("[Hermes] 嵌入模型加载失败: {}", e)
        return self._embedder

    # ========== 经验记录 ==========

    def record_experience(self, experience_type: str, content: str, result: dict, thread_id: str = ""):
        """
        记录一次经验
        experience_type: apply/communicate/search/match/polish
        content: 经验描述文本
        result: 结果数据
        """
        exp = {
            "id": f"exp_{int(time.time() * 1000)}",
            "type": experience_type,
            "content": content,
            "result": result,
            "thread_id": thread_id,
            "timestamp": datetime.now().isoformat(),
            "success": bool(result.get("success", False)),
            "tags": self._extract_tags(content),
        }

        # 追加写入文件
        try:
            with open(EXPERIENCE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(exp, ensure_ascii=False) + "\n")
            logger.info("[Hermes] 经验已记录: type={}, success={}", experience_type, exp["success"])
        except Exception as e:
            logger.error("[Hermes] 经验记录失败: {}", e)
            return

        # 缓存
        self._experiences.append(exp)

        # 异步添加到向量索引
        self._add_to_index(exp)

        # 每10条经验触发一次反思
        if len(self._experiences) % 10 == 0:
            self.reflect()

    def _extract_tags(self, content: str) -> List[str]:
        """从经验内容中提取标签"""
        tags = []
        keyword_map = {
            "高回复": ["回复", "感兴趣", "面试", "通过"],
            "低回复": ["未回复", "已读不回", "不合适"],
            "Python": ["python", "Python"],
            "Java": ["java", "Java"],
            "Go": ["go", "Go", "golang"],
            "前端": ["前端", "vue", "react", "前端开发"],
            "AI": ["AI", "人工智能", "机器学习", "深度学习", "NLP"],
        }
        for tag, keywords in keyword_map.items():
            if any(kw in content for kw in keywords):
                tags.append(tag)
        return tags

    # ========== 向量索引 ==========

    def _add_to_index(self, exp: dict):
        """将经验添加到 FAISS 索引"""
        try:
            embedder = self._get_embedder()
            if embedder is None:
                return

            text = exp.get("content", "") + " " + json.dumps(exp.get("result", {}), ensure_ascii=False)
            vector = embedder.embed_text(text)
            if vector is None:
                return

            try:
                import faiss
                if self._index is None:
                    dim = len(vector)
                    self._index = faiss.IndexFlatL2(dim)
                    # 如果已有磁盘索引，加载后合并
                    if INDEX_FILE.exists():
                        try:
                            self._index = faiss.read_index(str(INDEX_FILE))
                            logger.info("[Hermes] 已加载磁盘索引: {} 条", self._index.ntotal)
                        except Exception:
                            self._index = faiss.IndexFlatL2(dim)

                vec_np = np.array([vector]).astype('float32')
                self._index.add(vec_np)
                self._meta.append({"id": exp.get("id"), "type": exp.get("type")})

                # 保存索引
                faiss.write_index(self._index, str(INDEX_FILE))
                with open(META_FILE, "wb") as f:
                    pickle.dump(self._meta, f)
            except ImportError:
                pass

        except Exception as e:
            logger.warning("[Hermes] 添加到索引失败: {}", e)

    def search_similar(self, query: str, top_k: int = 5) -> List[dict]:
        """搜索相似历史经验"""
        self._ensure_loaded()

        try:
            embedder = self._get_embedder()
            if embedder is None or self._index is None or self._index.ntotal == 0:
                return []

            vector = embedder.embed_text(query)
            if vector is None:
                return []

            import faiss
            vec_np = np.array([vector]).astype('float32')
            distances, indices = self._index.search(vec_np, min(top_k, self._index.ntotal))

            results = []
            for i, idx in enumerate(indices[0]):
                if idx < len(self._meta):
                    exp_id = self._meta[idx].get("id")
                    exp = next((e for e in self._experiences if e.get("id") == exp_id), None)
                    if exp:
                        results.append({
                            "experience": exp,
                            "similarity": float(1.0 / (1.0 + distances[0][i])),
                        })
            return results
        except Exception as e:
            logger.warning("[Hermes] 搜索相似经验失败: {}", e)
            return []

    # ========== 反思沉淀 ==========

    def reflect(self, force: bool = False):
        """
        反思分析经验，生成策略洞察
        force: 是否强制反思（忽略频率限制）
        """
        self._ensure_loaded()

        # 避免频繁反思（至少间隔 1 小时）
        if not force and self._insights:
            last_time = self._insights[-1].get("created_at", "")
            if last_time:
                try:
                    last_dt = datetime.fromisoformat(last_time)
                    if (datetime.now() - last_dt).seconds < 3600:
                        return
                except Exception:
                    pass

        if len(self._experiences) < 5:
            logger.info("[Hermes] 经验数量不足({})，跳过反思", len(self._experiences))
            return

        logger.info("[Hermes] 开始反思分析，当前经验数: {}", len(self._experiences))

        # 基础统计分析
        stats = self._calculate_stats()

        # 生成洞察
        insights = self._generate_insights(stats)

        # 保存
        self._insights = insights
        self._save_insights()

        logger.info("[Hermes] 反思完成，生成 {} 条洞察", len(insights))

    def _calculate_stats(self) -> dict:
        """计算统计信息"""
        total = len(self._experiences)
        if total == 0:
            return {}

        apply_exps = [e for e in self._experiences if e["type"] == "apply"]
        communicate_exps = [e for e in self._experiences if e["type"] == "communicate"]

        apply_success = sum(1 for e in apply_exps if e["success"])
        comm_success = sum(1 for e in communicate_exps if e["success"])

        # 提取高效模式
        high_ctr_exps = [e for e in communicate_exps if e.get("result", {}).get("response", False)]

        return {
            "total_experiences": total,
            "apply_count": len(apply_exps),
            "apply_success_rate": apply_success / len(apply_exps) if apply_exps else 0,
            "communicate_count": len(communicate_exps),
            "communicate_response_rate": len(high_ctr_exps) / len(communicate_exps) if communicate_exps else 0,
            "recent_trend": "stable",
        }

    def _generate_insights(self, stats: dict) -> List[dict]:
        """基于统计生成策略洞察"""
        insights = (self._insights or []).copy()

        # 检查是否需要AI辅助
        if len(self._experiences) > 20:
            ai_insights = self._ai_reflect(stats)
            if ai_insights:
                insights.extend(ai_insights)

        # 基础洞察
        if stats.get("apply_success_rate", 0) > 0:
            insights.append({
                "id": f"insight_{int(time.time())}",
                "category": "strategy",
                "content": f"投递成功率: {stats['apply_success_rate']:.0%}",
                "confidence": 0.8,
                "created_at": datetime.now().isoformat(),
            })

        return insights

    def _ai_reflect(self, stats: dict) -> List[dict]:
        """使用 AI 进行深度反思"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=config.AI_API_KEY, base_url=config.AI_API_BASE)

            recent = self._experiences[-50:]
            summary = json.dumps(recent, ensure_ascii=False, indent=2)[:8000]

            prompt = f"""## 历史投递/沟通经验记录
{summary}

## 任务
请分析以上经验，总结出3-5条策略洞察（每条用简短句子表达）：
1. 哪种招呼语风格回复率高？
2. 什么时段投递效果好？
3. 哪些岗位类型更适合？
4. 有没有需要避免的常见错误？

请用 JSON 数组返回，格式：[{{"category":"strategy","content":"...","confidence":0.8}}]"""

            response = client.chat.completions.create(
                model=config.AI_MODEL,
                messages=[
                    {"role": "system", "content": "你是策略分析专家，擅长从数据中提炼可执行的洞察。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=1000,
            )

            result_text = response.choices[0].message.content.strip()
            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[1] if "\n" in result_text else result_text
                if "```" in result_text:
                    result_text = result_text.rsplit("```", 1)[0]

            insights = json.loads(result_text)
            for ins in insights:
                ins["id"] = f"insight_{int(time.time() * 1000)}"
                ins["created_at"] = datetime.now().isoformat()

            logger.info("[Hermes] AI 反思生成 {} 条洞察", len(insights))
            return insights
        except Exception as e:
            logger.warning("[Hermes] AI 反思失败: {}", e)
            return []

    # ========== 持久化 ==========

    def load_all(self):
        """加载所有经验数据"""
        # 加载经验
        self._experiences = []
        if EXPERIENCE_FILE.exists():
            try:
                with open(EXPERIENCE_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            self._experiences.append(json.loads(line))
                logger.info("[Hermes] 加载 {} 条经验", len(self._experiences))
            except Exception as e:
                logger.error("[Hermes] 加载经验失败: {}", e)

        # 加载洞察
        self._insights = load_all_insights()

        # 加载索引
        if INDEX_FILE.exists() and META_FILE.exists():
            try:
                import faiss
                self._index = faiss.read_index(str(INDEX_FILE))
                with open(META_FILE, "rb") as f:
                    self._meta = pickle.load(f)
                logger.info("[Hermes] 加载向量索引: {} 条", self._index.ntotal)
            except Exception as e:
                logger.warning("[Hermes] 加载索引失败: {}", e)

        self._loaded = True

    def _save_insights(self):
        """保存洞察到文件"""
        try:
            with open(INSIGHT_FILE, "w", encoding="utf-8") as f:
                json.dump(self._insights, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("[Hermes] 保存洞察失败: {}", e)

    def get_insights(self, category: str = "", limit: int = 5) -> List[dict]:
        """获取策略洞察"""
        self._ensure_loaded()
        if category:
            filtered = [i for i in self._insights if i.get("category") == category]
        else:
            filtered = self._insights
        return sorted(filtered, key=lambda x: x.get("created_at", ""), reverse=True)[:limit]

    def get_stats(self) -> dict:
        """获取统计概览"""
        self._ensure_loaded()
        return self._calculate_stats()


def load_all_insights() -> List[dict]:
    """加载所有洞察（不初始化 HermesMemory 实例）"""
    if not INSIGHT_FILE.exists():
        return []
    try:
        with open(INSIGHT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


# 全局单例
_hermes_memory = None


def get_hermes_memory() -> HermesMemory:
    global _hermes_memory
    if _hermes_memory is None:
        _hermes_memory = HermesMemory()
    return _hermes_memory
