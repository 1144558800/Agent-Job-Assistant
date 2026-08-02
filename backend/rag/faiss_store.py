# -*- coding: utf-8 -*-
"""
FAISS 向量存储
"""
import pickle
import json
from pathlib import Path
from typing import List, Optional
from loguru import logger
import numpy as np
import faiss

class FaissStore:
    """FAISS 向量数据库存储"""
    
    def __init__(self, index_dir: str = None):
        self.index_dir = Path(index_dir) if index_dir else None
        self.index = None
        self.documents = []  # 存储文档元数据
        self.dimension = 0
    
    def create_index(self, dimension: int):
        """创建 FAISS 索引"""
        self.dimension = dimension
        self.index = faiss.IndexFlatL2(dimension)
        logger.info(f"创建 FAISS 索引, 维度: {dimension}")
    
    def add_vectors(self, vectors: List[List[float]], documents: List[dict]):
        """添加向量和文档"""
        if self.index is None:
            raise ValueError("索引未创建，请先调用 create_index")
        
        vectors_np = np.array(vectors).astype('float32')
        self.index.add(vectors_np)
        self.documents.extend(documents)
        logger.info(f"添加 {len(vectors)} 条向量到索引，当前总数: {self.index.ntotal}")
    
    def search(self, query_vector: List[float], top_k: int = 5) -> List[dict]:
        """搜索最相似的文档"""
        if self.index is None or self.index.ntotal == 0:
            return []
        
        query_np = np.array([query_vector]).astype('float32')
        distances, indices = self.index.search(query_np, min(top_k, self.index.ntotal))
        
        results = []
        for i, idx in enumerate(indices[0]):
            if idx < len(self.documents):
                results.append({
                    "document": self.documents[idx],
                    "score": float(distances[0][i])
                })
        return results
    
    def save(self, path: str = None):
        """保存索引和文档到磁盘"""
        save_path = Path(path) if path else self.index_dir
        if not save_path:
            raise ValueError("请指定保存路径")
        
        save_path.mkdir(parents=True, exist_ok=True)
        
        # 保存 FAISS 索引
        faiss.write_index(self.index, str(save_path / "index.faiss"))
        
        # 保存文档数据
        with open(save_path / "documents.pkl", "wb") as f:
            pickle.dump(self.documents, f)
        
        # 保存配置
        config = {"dimension": self.dimension}
        with open(save_path / "config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False)
        
        logger.info(f"FAISS 索引已保存到: {save_path}")
    
    def load(self, path: str = None):
        """从磁盘加载索引和文档"""
        load_path = Path(path) if path else self.index_dir
        if not load_path or not load_path.exists():
            raise FileNotFoundError(f"索引路径不存在: {load_path}")
        
        # 加载 FAISS 索引
        index_file = load_path / "index.faiss"
        if index_file.exists():
            self.index = faiss.read_index(str(index_file))
            self.dimension = self.index.d
        
        # 加载文档数据
        doc_file = load_path / "documents.pkl"
        if doc_file.exists():
            with open(doc_file, "rb") as f:
                self.documents = pickle.load(f)
        
        # 加载配置
        config_file = load_path / "config.json"
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
                self.dimension = config.get("dimension", self.dimension)
        
        logger.info(f"FAISS 索引已加载, 包含 {len(self.documents)} 条文档")
    
    def clear(self):
        """清空索引和文档"""
        self.index = None
        self.documents = []
        self.dimension = 0
        logger.info("FAISS 索引已清空")
    
    @property
    def total_count(self) -> int:
        """获取文档总数"""
        return len(self.documents)

    def get_all(self) -> list:
        """获取所有存储的文档（岗位数据）"""
        return self.documents
