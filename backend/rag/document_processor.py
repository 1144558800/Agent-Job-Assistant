# -*- coding: utf-8 -*-
"""
文档处理器 - 对爬取的数据进行清洗、分块
"""
from typing import List
from loguru import logger
try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
except ImportError:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
from scrapers.base import JobItem

class DocumentProcessor:
    """文档处理器"""
    
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 100):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "；", "，", " ", ""]
        )
    
    def jobs_to_documents(self, jobs: list) -> List[dict]:
        """将 JobItem 列表转换为文档列表"""
        documents = []
        for job in jobs:
            job_dict = job if isinstance(job, dict) else (job.model_dump() if hasattr(job, 'model_dump') else job.dict())
            doc = {
                "id": f"{job_dict.get('platform', '')}_{job_dict.get('job_name', '')}_{job_dict.get('company_name', '')}",
                "content": self._format_job_content(job_dict),
                "metadata": {
                    "platform": job_dict.get("platform", ""),
                    "job_name": job_dict.get("job_name", ""),
                    "company_name": job_dict.get("company_name", ""),
                    "company_industry": job_dict.get("company_industry", ""),
                    "company_size": job_dict.get("company_size", ""),
                    "salary": job_dict.get("salary", ""),
                    "location": job_dict.get("location", ""),
                    "job_url": job_dict.get("job_url", ""),
                    "company_address": job_dict.get("company_address", "")
                }
            }
            documents.append(doc)
        return documents
    
    def _format_job_content(self, job: dict) -> str:
        """格式化岗位信息为文本"""
        parts = [
            f"岗位名称: {job.get('job_name', '')}",
            f"公司名称: {job.get('company_name', '')}",
            f"薪资待遇: {job.get('salary', '')}",
            f"工作地点: {job.get('location', '')}",
        ]
        if job.get("company_industry"):
            parts.append(f"公司行业: {job['company_industry']}")
        if job.get("company_size"):
            parts.append(f"公司规模: {job['company_size']}")
        if job.get("company_info"):
            parts.append(f"公司介绍: {job['company_info']}")
        if job.get("responsibilities"):
            parts.append(f"岗位职责: {job['responsibilities']}")
        if job.get("requirements"):
            parts.append(f"技能要求: {job['requirements']}")
        return "\n".join(parts)
    
    def split_documents(self, documents: List[dict]) -> List[dict]:
        """对文档进行分块"""
        chunks = []
        for doc in documents:
            texts = self.text_splitter.split_text(doc["content"])
            for i, text in enumerate(texts):
                chunk = {
                    "id": f"{doc['id']}_chunk_{i}",
                    "content": text,
                    "metadata": {**doc["metadata"], "chunk_index": i}
                }
                chunks.append(chunk)
        logger.info(f"文档分块完成: {len(documents)} 个文档 -> {len(chunks)} 个块")
        return chunks
