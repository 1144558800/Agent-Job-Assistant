# -*- coding: utf-8 -*-
"""
核心 API 路由 - 对话、文件上传、状态查询等
"""
import os
import sys
import json
import asyncio
import uuid
import shutil
import time
import traceback
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile, File, Query, Request
from fastapi.responses import StreamingResponse, FileResponse
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import UPLOAD_DIR, POLISHED_DIR
from api.models import (
    ChatRequest, UploadResponse, StatusResponse,
    CookieStatusResponse, LoginResponse,
    ScheduleRequest, ScheduleResponse,
    ExportRequest, ExportResponse,
)

router = APIRouter()

# ---- 全局状态 ----
# 存储上传的简历信息 {thread_id: {filename, text, path, original_path, polished_path}}
_resume_store: Dict[str, dict] = {}
# 存储岗位搜索结果 {thread_id: [jobs]}
_job_store: Dict[str, list] = {}

# 确保上传目录存在
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
POLISHED_DIR.mkdir(parents=True, exist_ok=True)


# ==================== 资源释放辅助 ====================

async def _cleanup_thread_resources(thread_id: str):
    """清理指定 thread 的上传文件和记录"""
    try:
        if thread_id in _resume_store:
            info = _resume_store.pop(thread_id)
            for key in ("path", "original_path", "polished_path"):
                p = info.get(key)
                if p and os.path.isfile(p):
                    try:
                        os.remove(p)
                        logger.info("[清理] 已删除文件: {}", p)
                    except Exception as e:
                        logger.warning("[清理] 删除文件失败: {} - {}", p, e)
            logger.info("[清理] 已释放 thread '{}' 的上传资源", thread_id)
    except Exception as e:
        logger.warning("[清理] 释放资源异常: {}", e)


# ==================== 辅助函数 ====================

async def _parse_resume_file(file_path: str, filename: str) -> dict:
    """解析简历文件，返回 {text, file_type}"""
    suffix = Path(filename).suffix.lower()
    text = None
    try:
        from resume.parser import extract_text_from_pdf, extract_text_from_docx, extract_text_from_txt
        if suffix == ".pdf":
            text = extract_text_from_pdf(file_path)
        elif suffix == ".docx":
            text = extract_text_from_docx(file_path)
        elif suffix == ".txt":
            text = extract_text_from_txt(file_path)
    except Exception as e:
        logger.warning(f"简历解析失败: {e}")
    return {"text": text, "file_type": suffix}


# ==================== 核心对话接口 ====================

@router.post("/chat")
async def chat(request: ChatRequest, http_request: Request):
    """对话接口 - SSE 流式返回"""
    logger.info("[Chat] 收到消息: thread={}, message={}", request.thread_id, request.message[:60])
    
    # 检测新建对话请求，清理旧资源
    msg_lower = request.message.strip().lower()
    new_session_keywords = ["新对话", "新建对话", "新建会话", "清除上下文", "清空上下文", "重置对话"]
    is_new_session = any(kw in msg_lower for kw in new_session_keywords)
    if is_new_session:
        await _cleanup_thread_resources(request.thread_id)
        logger.info("[Chat] 用户请求新建对话，已清理 thread '{}' 的资源", request.thread_id)

    return StreamingResponse(
        _chat_stream(request, http_request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


async def _chat_stream(request: ChatRequest, http_request: Request):
    """SSE 事件流生成器"""
    from agent.graph import create_agent
    from agent.state import AgentState
    from agent.context_manager import get_context_manager

    ctx_mgr = get_context_manager()
    thread_id = request.thread_id
    t_start = time.time()

    # 1. 构建初始状态
    history = ctx_mgr.get_history(thread_id)
    resume_info = _resume_store.get(thread_id, {})
    resume_text = resume_info.get("text", "")

    # 整理文件信息供 Agent 感知（含预览路径）
    uploaded_files_info = ""
    file_preview_info = {}
    if resume_info:
        uploaded_files_info = json.dumps({
            "filename": resume_info.get("filename", ""),
            "text_preview": resume_text[:500] if resume_text else "",
            "preview_url": f"/api/file-preview?thread_id={thread_id}&filename={resume_info.get('filename', '')}",
            "polished_preview_url": (
                f"/api/file-preview?thread_id={thread_id}&filename={resume_info.get('polished_filename', '')}"
                if resume_info.get("polished_filename") else ""
            ),
        }, ensure_ascii=False)

    initial_state: AgentState = {
        "messages": history + [{"role": "user", "content": request.message}],
        "context": {
            "thread_id": thread_id,
            "resume_text": resume_text,
            "uploaded_files": uploaded_files_info,
        },
        "search_results": [],
        "analysis_results": {},
        "tool_calls": [],
    }

    agent = create_agent()
    final_result = ""
    tool_call_count = 0

    try:
        # 2. 执行 Agent，流式输出 token
        logger.info("[Chat] Agent 开始执行, thread={}", thread_id)
        async for event_chunk in agent.astream_events(initial_state, version="v2"):
            kind = event_chunk.get("event")

            # 检查客户端是否断开
            if await http_request.is_disconnected():
                logger.info("[Chat] 客户端已断开, thread={}", thread_id)
                break

            if kind == "on_chat_model_stream":
                chunk = event_chunk.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    token = chunk.content
                    final_result += token
                    yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"

            elif kind == "on_tool_start":
                tool_call_count += 1
                tool_name = event_chunk.get("name", "unknown")
                tool_input = event_chunk.get("data", {}).get("input", {})
                logger.info("[Chat] Tool start: {}, input_keys={}", tool_name, list(tool_input.keys()) if isinstance(tool_input, dict) else str(tool_input)[:80])
                # 脱敏处理敏感字段
                safe_input = {}
                if isinstance(tool_input, dict):
                    for k, v in tool_input.items():
                        if k in ("message", "greeting_message", "greeting"):
                            safe_input[k] = str(v)[:30] + "..."
                        else:
                            safe_input[k] = v
                yield f"data: {json.dumps({'type': 'tool_start', 'tool': tool_name, 'input': safe_input}, ensure_ascii=False)}\n\n"

            elif kind == "on_tool_end":
                tool_name = event_chunk.get("name", "unknown")
                tool_output = event_chunk.get("data", {}).get("output")
                logger.info("[Chat] Tool end: {}", tool_name)
                yield f"data: {json.dumps({'type': 'tool_end', 'tool': tool_name}, ensure_ascii=False)}\n\n"

                # 如果是搜索结果，发送统计信息
                if tool_name == "search_jobs" and tool_output:
                    try:
                        output_obj = json.loads(tool_output) if isinstance(tool_output, str) else tool_output
                        jobs_data = output_obj.get("jobs", []) if isinstance(output_obj, dict) else []
                        if jobs_data:
                            platform_counts = {}
                            for j in jobs_data:
                                p = j.get("platform", "未知")
                                platform_counts[p] = platform_counts.get(p, 0) + 1
                            yield f"data: {json.dumps({'type': 'search_result', 'count': len(jobs_data), 'platforms': platform_counts}, ensure_ascii=False)}\n\n"
                    except Exception:
                        pass

                # 如果是导出结果，发送文件信息
                if tool_name == "export_excel" and tool_output:
                    try:
                        output_obj = json.loads(tool_output) if isinstance(tool_output, str) else tool_output
                        if isinstance(output_obj, dict) and output_obj.get("success"):
                            yield f"data: {json.dumps({'type': 'export_result', 'data': output_obj}, ensure_ascii=False)}\n\n"
                    except Exception:
                        pass

                # 如果是简历润色结果，发送文件信息
                if tool_name == "polish_resume" and tool_output:
                    try:
                        output_obj = json.loads(tool_output) if isinstance(tool_output, str) else tool_output
                        if isinstance(output_obj, dict) and output_obj.get("success"):
                            yield f"data: {json.dumps({'type': 'polish_result', 'data': output_obj}, ensure_ascii=False)}\n\n"
                    except Exception:
                        pass

        # 3. 上下文使用率预警
        if final_result:
            token_estimate = len(final_result) * 0.6
            ctx_usage = ctx_mgr.get_usage(thread_id)
            if ctx_usage is not None and ctx_usage > 70:
                yield f"data: {json.dumps({'type': 'context_warning', 'usage': ctx_usage, 'tokens': int(token_estimate)}, ensure_ascii=False)}\n\n"

        # 4. 输出校验
        from agent.guardrails import validate_output, OutputVerificationResult
        verif = validate_output(final_result)
        if verif is not OutputVerificationResult.valid:
            logger.warning("[Chat] 输出校验未通过: {}", verif)
            yield f"data: {json.dumps({'type': 'verification_warning', 'message': f'输出校验: {verif.value}'}, ensure_ascii=False)}\n\n"

        # 5. 保存对话历史
        if final_result:
            ctx_mgr.add_message(thread_id, "user", request.message)
            ctx_mgr.add_message(thread_id, "assistant", final_result)
            logger.info("[Chat] 对话已保存, thread={}, messages_in_context={}", thread_id, ctx_mgr.get_message_count(thread_id))

        # 6. 完成信号
        t_total = time.time() - t_start
        logger.info("[Chat] Agent 完成, thread={}, tokens={}, tool_calls={}, time={:.1f}s", thread_id, len(final_result), tool_call_count, t_total)
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception as e:
        logger.error("[Chat] Agent 异常: {}", e)
        logger.error(traceback.format_exc())
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"


# ==================== 文件上传 ====================


def _copy_to_public_dir(src_path: str, thread_id: str, filename: str) -> str:
    """将文件复制到 thread 专属公开目录，生成可预览的路径"""
    public_dir = UPLOAD_DIR / thread_id
    public_dir.mkdir(parents=True, exist_ok=True)
    dst = public_dir / filename
    shutil.copy2(src_path, dst)
    logger.info("[预览] 已复制到公开目录: {}", dst)
    return str(dst)


@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...), thread_id: str = Query(default="default")):
    """上传简历文件"""
    logger.info("[Upload] 收到文件: {}, thread={}, size={}", file.filename, thread_id, file.size if hasattr(file, 'size') else 'unknown')

    if not file.filename:
        raise HTTPException(status_code=400, detail="未选择文件")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in [".pdf", ".docx", ".doc", ".txt"]:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {suffix}，支持 PDF/Word/TXT")

    # 保存文件
    safe_filename = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = UPLOAD_DIR / safe_filename

    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        logger.info("[Upload] 文件已保存: {}", file_path)
    except Exception as e:
        logger.error("[Upload] 文件保存失败: {}", e)
        raise HTTPException(status_code=500, detail=f"文件保存失败: {e}")

    # 解析简历
    resume_data = await _parse_resume_file(str(file_path), file.filename)

    # 存储简历信息
    _resume_store[thread_id] = {
        "filename": safe_filename,
        "original_name": file.filename,
        "text": resume_data.get("text", ""),
        "path": str(file_path),
        "file_type": resume_data.get("file_type", ""),
        "uploaded_at": datetime.now().isoformat(),
    }

    logger.info("[Upload] 简历已存储: thread={}, filename={}, text_len={}", thread_id, safe_filename, len(resume_data.get("text", "") or ""))

    return UploadResponse(
        success=True,
        file_name=safe_filename,
        file_path=str(file_path),
        resume_data=resume_data,
    )


# ==================== 文件预览 ====================

@router.get("/file-preview")
async def file_preview(thread_id: str = Query(...), filename: str = Query(...)):
    """预览上传的文件（供前端 iframe 使用）"""
    logger.info("[预览] 请求预览: thread={}, filename={}", thread_id, filename)

    # 先在公开目录查找（润色后文件只会保存在这里）
    file_path = UPLOAD_DIR / thread_id / filename
    if not file_path.exists():
        # 在根目录查找
        file_path = UPLOAD_DIR / filename

    if not file_path.exists():
        logger.warning("[预览] 文件不存在: {}", file_path)
        raise HTTPException(status_code=404, detail="文件不存在")

    logger.info("[预览] 返回文件: {}", file_path)
    return FileResponse(str(file_path))


# ==================== 系统状态 ====================

@router.get("/status", response_model=StatusResponse)
async def get_status():
    """获取系统状态"""
    faiss_total = 0
    try:
        from rag.faiss_store import FaissStore
        from config import FAISS_INDEX_DIR
        store = FaissStore(str(FAISS_INDEX_DIR))
        try:
            store.load()
            faiss_total = store.total_count
        except FileNotFoundError:
            pass
    except Exception as e:
        logger.warning(f"获取 FAISS 状态失败: {e}")

    # 检查 Hermes 记忆洞察数量
    memory_insights = 0
    try:
        from agent.hermes_memory import load_all_insights
        insights = load_all_insights()
        memory_insights = len(insights)
    except Exception as e:
        logger.warning(f"获取 Hermes 状态失败: {e}")

    return StatusResponse(
        faiss_total=faiss_total,
        memory_insights_count=memory_insights,
    )


# ==================== Cookie / 登录 ====================

@router.get("/cookies/{platform}", response_model=CookieStatusResponse)
async def check_cookies(platform: str):
    """检查指定平台的 Cookie 状态"""
    try:
        from scrapers.scraper_manager import ScraperManager
        mgr = ScraperManager()
        scraper = mgr.scrapers.get(platform)
        if not scraper:
            return CookieStatusResponse(platform=platform, has_cookies=False, valid=False)

        has = scraper.has_cookies()
        valid = False
        if has:
            valid = scraper.verify_cookies()

        return CookieStatusResponse(platform=platform, has_cookies=has, valid=valid)
    except Exception as e:
        logger.error(f"检查 Cookie 失败: {e}")
        return CookieStatusResponse(platform=platform, has_cookies=False, valid=False)


@router.post("/login/{platform}", response_model=LoginResponse)
async def trigger_login(platform: str):
    """触发手动登录"""
    logger.info(f"[Login] 触发登录: {platform}")
    try:
        from scrapers.scraper_manager import ScraperManager
        mgr = ScraperManager()
        scraper = mgr.scrapers.get(platform)
        if not scraper:
            return LoginResponse(platform=platform, logged_in=False)

        success, _ = await scraper.manual_login()
        return LoginResponse(platform=platform, logged_in=success)
    except Exception as e:
        logger.error(f"登录失败: {e}")
        return LoginResponse(platform=platform, logged_in=False)


# ==================== 定时任务 ====================

@router.get("/schedules")
async def list_schedules():
    """获取所有定时任务"""
    try:
        from scheduler.scheduler import get_scheduler
        scheduler = get_scheduler()
        return scheduler.list_jobs()
    except Exception as e:
        logger.error(f"获取定时任务失败: {e}")
        return []


@router.post("/schedules", response_model=ScheduleResponse)
async def create_schedule(req: ScheduleRequest):
    """创建定时任务"""
    try:
        from scheduler.scheduler import get_scheduler
        scheduler = get_scheduler()
        job_id = scheduler.add_job(req.keyword, req.city, req.cron, req.platforms)
        return ScheduleResponse(success=True, job_id=job_id, message=f"定时任务已创建: {job_id}")
    except Exception as e:
        logger.error(f"创建定时任务失败: {e}")
        return ScheduleResponse(success=False, message=str(e))


@router.delete("/schedules/{job_id}")
async def delete_schedule(job_id: str):
    """删除定时任务"""
    try:
        from scheduler.scheduler import get_scheduler
        scheduler = get_scheduler()
        result = scheduler.remove_job(job_id)
        return {"success": result}
    except Exception as e:
        logger.error(f"删除定时任务失败: {e}")
        return {"success": False, "message": str(e)}
