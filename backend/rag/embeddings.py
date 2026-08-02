# -*- coding: utf-8 -*-
"""
Embedding 处理 - 将文本转换为向量
"""
import os
from typing import List, Optional
from loguru import logger
import numpy as np
from sentence_transformers import SentenceTransformer

# 设置 HuggingFace 镜像（国内加速）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

class EmbeddingService:
    """Embedding 服务"""
    
    def __init__(self, model_name: str = "shibing624/text2vec-base-chinese"):
        self.model_name = model_name
        self.model = None
        logger.info(f"Embedding 模型: {model_name}")
    
    def _load_model(self):
        """加载模型（延迟加载）"""
        if self.model is None:
            try:
                logger.info(f"正在加载 Embedding 模型: {self.model_name}")
                self.model = SentenceTransformer(self.model_name)
                logger.info("Embedding 模型加载完成")
            except Exception as e:
                logger.error(f"加载 Embedding 模型失败: {e}")
                raise
    
    def embed_text(self, text: str) -> Optional[List[float]]:
        """将文本转为向量"""
        self._load_model()
        try:
            vector = self.model.encode(text, show_progress_bar=False)
            return vector.tolist()
        except Exception as e:
            logger.error(f"文本向量化失败: {e}")
            return None
    
    def embed_texts(self, texts: List[str]) -> Optional[List[List[float]]]:
        """批量将文本转为向量"""
        self._load_model()
        try:
            vectors = self.model.encode(texts, show_progress_bar=False)
            return [v.tolist() for v in vectors]
        except Exception as e:
            logger.error(f"批量文本向量化失败: {e}")
            return None
    
    def get_embedding_dimension(self) -> int:
        """获取向量维度"""
        self._load_model()
        return self.model.get_sentence_embedding_dimension()
