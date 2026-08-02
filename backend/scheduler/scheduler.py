# -*- coding: utf-8 -*-
"""
定时任务调度器 - 基于 APScheduler
"""
import os
import sys
import json
import asyncio
from datetime import datetime
from pathlib import Path
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import SCHEDULE_DIR


class JobScheduler:
    """定时搜索任务调度器"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.jobs_file = SCHEDULE_DIR / "scheduled_jobs.json"
        self._scraper_manager = None
    
    def _get_scraper_manager(self):
        if self._scraper_manager is None:
            from scrapers.scraper_manager import ScraperManager
            self._scraper_manager = ScraperManager()
        return self._scraper_manager
    
    def add_job(self, keyword: str, city: str, cron: str, platforms: str = None) -> str:
        """添加定时搜索任务"""
        job_id = f"search_{keyword}_{city}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        platform_list = [p.strip() for p in platforms.split(",")] if platforms else None
        
        async def search_task():
            logger.info(f"[定时任务] 开始搜索: keyword={keyword}, city={city}")
            try:
                mgr = self._get_scraper_manager()
                jobs = await mgr.search_all(keyword, city, platforms=platform_list)
                logger.info(f"[定时任务] 搜索完成: {len(jobs)} 个岗位")
                
                # 自动保存到 FAISS
                if jobs:
                    self._auto_save_to_faiss(jobs)
            except Exception as e:
                logger.error(f"[定时任务] 搜索失败: {e}")
        
        self.scheduler.add_job(
            search_task,
            trigger=CronTrigger.from_crontab(cron),
            id=job_id,
            replace_existing=True,
        )
        
        # 保存到磁盘
        self._save_jobs_config()
        
        logger.info(f"[定时任务] 已添加: {job_id}, cron={cron}")
        return job_id
    
    def _auto_save_to_faiss(self, jobs):
        """定时任务自动保存到 FAISS"""
        try:
            from config import FAISS_INDEX_DIR
            from rag.faiss_store import FaissStore
            from rag.document_processor import DocumentProcessor
            from rag.embeddings import EmbeddingService
            
            store = FaissStore(str(FAISS_INDEX_DIR))
            try:
                store.load()
            except FileNotFoundError:
                pass
            
            doc_processor = DocumentProcessor()
            embed_service = EmbeddingService()
            
            documents = doc_processor.jobs_to_documents(jobs)
            chunks = doc_processor.split_documents(documents)
            texts = [chunk["content"] for chunk in chunks]
            vectors = embed_service.embed_texts(texts)
            
            if store.index is None:
                dim = embed_service.get_embedding_dimension()
                store.create_index(dim)
            
            if vectors:
                store.add_vectors(vectors, chunks)
                store.save()
                logger.info(f"[定时任务] 自动保存 {len(jobs)} 个岗位到 FAISS")
        except Exception as e:
            logger.error(f"[定时任务] 自动保存失败: {e}")
    
    def remove_job(self, job_id: str) -> bool:
        """移除定时任务"""
        try:
            self.scheduler.remove_job(job_id)
            self._save_jobs_config()
            return True
        except Exception:
            return False
    
    def list_jobs(self) -> list:
        """列出所有定时任务"""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger),
            })
        return jobs
    
    def _save_jobs_config(self):
        """保存定时任务配置到磁盘"""
        SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
        config = []
        for job in self.scheduler.get_jobs():
            config.append({
                "id": job.id,
                "trigger": str(job.trigger),
                "next_run": str(job.next_run_time) if job.next_run_time else None,
            })
        with open(self.jobs_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    
    def start(self):
        """启动调度器"""
        self.scheduler.start()
        logger.info("[定时任务] 调度器已启动")
    
    def shutdown(self):
        """关闭调度器"""
        self.scheduler.shutdown(wait=False)
        logger.info("[定时任务] 调度器已关闭")


# 全局单例
_scheduler = None


def get_scheduler() -> JobScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = JobScheduler()
    return _scheduler
