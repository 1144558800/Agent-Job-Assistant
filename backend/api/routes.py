# -*- coding: utf-8 -*-
"""
API 路由 - Agent 对话接口 + 文件上传
"""
import os
import sys
import re
import json
import time
import asyncio
import uuid
from pathlib import Path
from typing import Optional
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import UPLOAD_DIR, FAISS_INDEX_DIR, AI_MODEL
from agent.graph import get_agent, SYSTEM_PROMPT
from agent.tools import (
    _get_scraper_manager, _get_faiss_store,
    _get_embedding_service, _get_doc_processor
)
from scheduler.scheduler import get_scheduler
from agent.context_manager import (
    load_conversation, persist_conversation,
    check_context_usage, trim_messages,
    serialize_langchain_message, deserialize_langchain_message,
    delete_conversation,
    CONTEXT_WARNING_THRESHOLD, DEEPSEEK_MAX_TOKENS,
)

router = APIRouter()

# 存储每个会话的临时数据
_session_data = {}


def _get_session_data(thread_id: str) -> dict:
    if thread_id not in _session_data:
        _session_data[thread_id] = {
            "search_results": [],
            "resume_path": None,
            "resume_data": None,
        }
    return _session_data[thread_id]


# ---- Agent 对话接口（SSE 流式） ----

class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = "default"


def _get_latest_resume_file(thread_id: Optional[str] = None) -> Optional[Path]:
    """获取指定对话最近上传的简历文件路径（严格隔离，仅 default 回退到全局）"""
    # 优先检查对话专属目录
    if thread_id and thread_id != "default":
        session_dir = UPLOAD_DIR / thread_id
        if session_dir.exists():
            resume_files = []
            for ext in [".pdf", ".docx", ".doc", ".txt"]:
                resume_files.extend(list(session_dir.glob(f"*{ext}")))
            if resume_files:
                logger.debug("[_get_latest_resume_file] 对话专属目录找到 {} 个文件 (thread={})",
                           len(resume_files), thread_id)
                return max(resume_files, key=lambda f: f.stat().st_mtime)
        # 对话目录存在但为空，不回退到全局
        return None
    
    # 仅对 "default" 或无 thread_id 回退到全局上传目录（兼容旧逻辑）
    if not thread_id or thread_id == "default":
        if UPLOAD_DIR.exists():
            resume_files = []
            for ext in [".pdf", ".docx", ".doc", ".txt"]:
                resume_files.extend(list(UPLOAD_DIR.glob(f"*{ext}")))
            if resume_files:
                return max(resume_files, key=lambda f: f.stat().st_mtime)
    return None


def _build_context_message(user_message: str, thread_id: Optional[str] = None) -> str:
    """构建带上下文信息的用户消息，让 Agent 感知当前系统状态（不影响 System Prompt 缓存）"""
    context_parts = []
    
    # 1. 检测已上传的简历（优先对话专属，回退全局）
    resume_file = _get_latest_resume_file(thread_id)
    if resume_file:
        context_parts.append(
            f"用户已上传简历文件: {resume_file.name}\n"
            f"如果用户提到匹配、投递等操作，可以直接使用 match_resume 或 auto_apply_jobs 工具，无需重复要求上传。"
        )
        logger.debug("[Chat] 简历已上传({})，注入上下文到消息", resume_file.name)
    
    # 2. Hermes 自进化洞察注入（作为用户消息上下文，不修改 System Prompt）
    try:
        from agent.hermes_memory import get_hermes_memory
        from config import HERMES_INSIGHT_INJECT
        if HERMES_INSIGHT_INJECT:
            hm = get_hermes_memory()
            insight_text = hm.get_latest_insight_summary()
            if insight_text:
                context_parts.append(f"[历史经验洞察]\n{insight_text}")
                logger.info("[Chat] Hermes 洞察已注入到用户消息上下文")
    except Exception as e:
        logger.debug("[Chat] Hermes 洞察注入失败(非致命): {}", e)
    
    # 构建最终消息
    if context_parts:
        context = (
            f"[--- 系统上下文信息 ---]\n"
            + "\n---\n".join(context_parts)
            + f"\n\n[--- 用户消息 ---]\n"
        )
        return context + user_message
    return user_message


@router.post("/chat", summary="Agent 对话（SSE 流式）")
async def chat(request: ChatRequest):
    """与 Agent 对话，通过 Server-Sent Events 流式返回"""
    # ===== 入口日志：记录完整请求 =====
    t_request_start = time.time()
    logger.info("=" * 60)
    logger.info("[Chat] === 收到新请求 ===")
    logger.info("[Chat] thread_id = {}", request.thread_id)
    logger.info("[Chat] message = {}", request.message[:100])
    logger.info("[Chat] message_length = {} 字符", len(request.message))
    
    # 注入上下文信息（简历状态等），让 Agent 感知当前系统状态
    context_message = _build_context_message(request.message, request.thread_id)
    
    # 上下文管理：恢复 + 检查 + 裁剪
    conv_data = load_conversation(request.thread_id)
    was_restored = False
    needs_context_warning = False
    
    async def event_stream():
        nonlocal was_restored, needs_context_warning
        t_stream_start = time.time()
        tool_call_history = []  # 追踪工具调用
    
        try:
            agent = get_agent()
            logger.info("[Chat] Agent 已获取，开始流式调用...")
            
            # 配置参数
            config = {"configurable": {"thread_id": request.thread_id}}
            
            # ---- 上下文恢复（仅在新对话/服务重启后恢复） ----
            if conv_data and conv_data.get("messages"):
                try:
                    # 检查当前状态是否为空（MemorySaver 无记录 = 新对话或服务重启）
                    current_state_before = agent.get_state(config)
                    existing_msgs = current_state_before.values.get("messages", []) if current_state_before and current_state_before.values else []
                    
                    if not existing_msgs:
                        # 内存中无状态，从文件恢复
                        restored_msgs = []
                        for m_data in conv_data["messages"]:
                            try:
                                restored_msgs.append(deserialize_langchain_message(m_data))
                            except Exception:
                                continue
                        
                        if restored_msgs:
                            # 恢复前校验消息完整性：确保没有孤儿 ToolMessage
                            from agent.context_manager import validate_messages
                            before_count = len(restored_msgs)
                            restored_msgs = validate_messages(restored_msgs)
                            after_count = len(restored_msgs)
                            agent.update_state(config, {"messages": restored_msgs})
                            was_restored = True
                            logger.info("[Chat] 对话已恢复: {} 条消息 -> 校验后 {} 条", before_count, after_count)
                            
                            # 校验清理后重新持久化，防止下次重启再读到脏数据
                            if after_count != before_count:
                                try:
                                    cleaned_serialized = [serialize_langchain_message(m) for m in restored_msgs]
                                    persist_conversation(request.thread_id, cleaned_serialized,
                                                       conv_data.get("metadata"))
                                    logger.info("[Chat] 清理后的对话已重新持久化 ({} 条 -> {} 条)", before_count, after_count)
                                except Exception as ex:
                                    logger.warning("[Chat] 重新持久化失败: {}", ex)
                    else:
                        logger.info("[Chat] 内存中已有 {} 条消息，跳过文件恢复", len(existing_msgs))
                except Exception as e:
                    logger.warning("[Chat] 对话恢复失败: {}", e)
                    # 恢复失败时删除损坏的持久化文件
                    try:
                        delete_conversation(request.thread_id)
                        logger.info("[Chat] 已删除损坏的对话持久化文件: {}", request.thread_id)
                    except Exception:
                        pass
            
            # ---- 上下文检查与裁剪 ----
            try:
                current_state = agent.get_state(config)
                current_msgs = current_state.values.get("messages", []) if current_state.values else []
                if current_msgs:
                    serialized_msgs = [serialize_langchain_message(m) for m in current_msgs]
                    usage, total_tokens, is_over = check_context_usage(serialized_msgs, SYSTEM_PROMPT)
                    logger.info("[Chat] 上下文使用率: {:.1%} (~{} tokens)", usage, total_tokens)
                    
                    if is_over:
                        # 裁剪消息
                        trimmed_ser, cut_count = trim_messages(serialized_msgs, SYSTEM_PROMPT)
                        logger.warning("[Chat] 上下文超80%, 裁剪了 {} 条消息", cut_count)
                        # 更新 agent 状态为裁剪后的消息
                        trimmed_objects = []
                        for m_data in trimmed_ser:
                            try:
                                trimmed_objects.append(deserialize_langchain_message(m_data))
                            except Exception:
                                continue
                        if trimmed_objects:
                            agent.update_state(config, {"messages": trimmed_objects})
                            logger.info("[Chat] 裁剪后状态已更新: {} 条消息", len(trimmed_objects))
                    
                    # 计算裁剪后的使用率
                    final_usage, _, _ = check_context_usage(
                        [serialize_langchain_message(m) for m in (agent.get_state(config).values.get("messages", []) if agent.get_state(config).values else [])], 
                        SYSTEM_PROMPT
                    )
                    if final_usage >= CONTEXT_WARNING_THRESHOLD:
                        needs_context_warning = True
            except Exception as e:
                logger.warning("[Chat] 上下文检查/裁剪失败: {}", e)
            
            # ---- 消息完整性预校验（防止 MemorySaver 中残留孤儿 tool_calls） ----
            try:
                pre_state = agent.get_state(config)
                if pre_state and pre_state.values:
                    pre_msgs = pre_state.values.get("messages", [])
                    if pre_msgs:
                        from agent.context_manager import validate_messages
                        cleaned = validate_messages(pre_msgs)
                        if len(cleaned) != len(pre_msgs):
                            agent.update_state(config, {"messages": cleaned})
                            logger.warning("[Chat] 预校验清理了 {} 条异常消息", len(pre_msgs) - len(cleaned))
            except Exception as e:
                logger.warning("[Chat] 预校验失败: {}", e)
            
            # 流式调用 Agent
            final_message = ""
            async for event in agent.astream_events(
                {"messages": [("user", context_message)]},
                config=config,
                version="v2",
            ):
                kind = event.get("event", "")
                
                # 处理 LLM 流式输出（逐 token 返回）
                if kind == "on_chat_model_stream":
                    content = event["data"]["chunk"].content
                    if content:
                        final_message += content
                        yield f"data: {json.dumps({'type': 'token', 'content': content}, ensure_ascii=False)}\n\n"
                
                # 处理工具调用开始
                elif kind == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    tool_input = event["data"].get("input", {})
                    t_tool_start = time.time()
                    tool_call_history.append({"name": tool_name, "input": tool_input, "start": t_tool_start})
                    logger.info("[Chat] 工具开始 -> {}, 参数 = {}", tool_name, json.dumps(tool_input, ensure_ascii=False, default=str)[:200])
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool': tool_name, 'input': str(tool_input)}, ensure_ascii=False)}\n\n"
                
                # 处理工具调用结束
                elif kind == "on_tool_end":
                    tool_name = event.get("name", "unknown")
                    output = event["data"].get("output", "")
                    t_tool_end = time.time()
                    
                    # 计算该工具耗时，同时保存输出结果供后续校验
                    tool_elapsed = 0
                    for tc in tool_call_history:
                        if tc["name"] == tool_name and "elapsed" not in tc:
                            tool_elapsed = t_tool_end - tc["start"]
                            tc["elapsed"] = tool_elapsed
                            tc["output"] = output  # 保存工具返回结果用于输出校验
                            break
                    
                    logger.info("[Chat] 工具完成 -> {}, 耗时 = {:.2f}s", tool_name, tool_elapsed)
                    
                    # 记录工具输出摘要
                    output_preview = str(output)[:300] if output else "(空)"
                    logger.info("[Chat] 工具输出摘要(前300字符): {}", output_preview)
                    
                    # 如果工具返回的是 JSON 字符串，尝试解析
                    try:
                        if isinstance(output, str):
                            parsed = json.loads(output)
                            # 如果是搜索工具，缓存搜索结果
                            if tool_name == "search_jobs" and parsed.get("success"):
                                mgr = _get_scraper_manager()
                                all_jobs = getattr(mgr, '_last_search_results', [])
                                count = parsed.get("count", 0)
                                platforms = parsed.get("summary_by_platform", {})
                                logger.info("[Chat] 搜索结果: 总数={}, 平台分布={}", count, platforms)
                                if count > 0:
                                    yield f"data: {json.dumps({'type': 'search_result', 'count': count, 'platforms': platforms}, ensure_ascii=False)}\n\n"
                                else:
                                    logger.warning("[Chat] 搜索结果为空！message={}", parsed.get("message", ""))
                            elif tool_name == "analyze_jobs":
                                yield f"data: {json.dumps({'type': 'analysis_result', 'data': parsed}, ensure_ascii=False)}\n\n"
                            elif tool_name == "export_excel":
                                yield f"data: {json.dumps({'type': 'export_result', 'data': parsed}, ensure_ascii=False)}\n\n"
                            elif tool_name == "auto_apply_jobs":
                                yield f"data: {json.dumps({'type': 'apply_result', 'data': parsed}, ensure_ascii=False)}\n\n"
                            elif tool_name == "check_apply_history":
                                yield f"data: {json.dumps({'type': 'apply_history', 'data': parsed}, ensure_ascii=False)}\n\n"
                            elif tool_name == "reflect_on_experience":
                                yield f"data: {json.dumps({'type': 'hermes_reflection', 'data': parsed}, ensure_ascii=False)}\n\n"
                            elif tool_name == "get_experience_insights":
                                yield f"data: {json.dumps({'type': 'hermes_insights', 'data': parsed}, ensure_ascii=False)}\n\n"
                            elif tool_name == "record_user_feedback":
                                yield f"data: {json.dumps({'type': 'hermes_feedback', 'data': parsed}, ensure_ascii=False)}\n\n"
                            elif tool_name == "polish_resume":
                                # 润色完成后，提取润色后文本用于前端预览
                                polish_text_preview = ""
                                if parsed.get("success") and parsed.get("output_file"):
                                    try:
                                        from resume.parser import extract_resume_text
                                        polish_text_preview = extract_resume_text(parsed["output_file"]) or ""
                                        logger.info("[Chat] polish_resume 预览文本长度: {}", len(polish_text_preview))
                                    except Exception as e:
                                        logger.warning("[Chat] 提取润色文本预览失败: {}", e)
                                yield f"data: {json.dumps({'type': 'polish_result', 'data': parsed, 'preview_text': polish_text_preview[:3000]}, ensure_ascii=False)}\n\n"
                        else:
                            yield f"data: {json.dumps({'type': 'tool_end', 'tool': tool_name, 'output': str(output)[:500]}, ensure_ascii=False)}\n\n"
                    except Exception as parse_err:
                        logger.warning("[Chat] 工具 {} 返回非JSON或解析失败: {} | output_type={} | output[:200]={}", 
                                      tool_name, parse_err, type(output).__name__, str(output)[:200])
                        yield f"data: {json.dumps({'type': 'tool_end', 'tool': tool_name}, ensure_ascii=False)}\n\n"
            
            # 发送完成信号
            t_done = time.time()
            total_elapsed = t_done - t_stream_start
            logger.info("[Chat] 对话完成: 总耗时={:.2f}s, 回复长度={}, 工具调用次数={}", 
                       total_elapsed, len(final_message), len(tool_call_history))
            for tc in tool_call_history:
                logger.info("[Chat]   工具 [{}] 耗时={:.2f}s", tc["name"], tc.get("elapsed", 0))
            logger.info("=" * 60)
            
            # ---- 输出校验层：对比 Agent 回复中的数字与工具返回数据 ----
            verification_issues = []
            if final_message and tool_call_history:
                try:
                    for tc in tool_call_history:
                        tool_name = tc["name"]
                        output_str = tc.get("output", "")
                        if isinstance(output_str, str):
                            try:
                                output_json = json.loads(output_str)
                            except json.JSONDecodeError:
                                continue
                        else:
                            continue
                        
                        if tool_name == "search_jobs" and output_json.get("success"):
                            actual_count = output_json.get("count", 0)
                            # 从 Agent 回复中提取数字
                            nums = re.findall(r'(\d+)\s*(?:个|条|项)?\s*岗位', final_message)
                            for num_str in nums:
                                claimed = int(num_str)
                                if claimed != actual_count and abs(claimed - actual_count) > 2:
                                    verification_issues.append(
                                        f"岗位数量不一致: Agent 回复中提到 {claimed} 个，但搜索工具实际返回 {actual_count} 个"
                                    )
                        
                        elif tool_name == "auto_apply_jobs" and output_json.get("success"):
                            actual_success = output_json.get("success_count", 0)
                            actual_fail = output_json.get("fail_count", 0)
                            nums = re.findall(r'(?:成功|已投递|投递成功|打招呼)\s*(\d+)', final_message)
                            for num_str in nums:
                                claimed = int(num_str)
                                if claimed != actual_success and abs(claimed - actual_success) > 1:
                                    verification_issues.append(
                                        f"投递数量不一致: Agent 声称 {claimed} 个，但实际成功 {actual_success} 个，失败 {actual_fail} 个"
                                    )
                        
                        elif tool_name == "match_resume" and output_json.get("success"):
                            actual_matched = output_json.get("matched_count", 0)
                            nums = re.findall(r'(?:匹配[到了的]*|适合|推荐)\s*(\d+)', final_message)
                            for num_str in nums:
                                claimed = int(num_str)
                                if claimed != actual_matched and abs(claimed - actual_matched) > 2:
                                    verification_issues.append(
                                        f"匹配数量不一致: Agent 声称 {claimed} 个，但工具实际匹配 {actual_matched} 个"
                                    )
                    
                    if verification_issues:
                        issue_detail = "; ".join(verification_issues)
                        logger.warning("[Chat] 输出校验发现不一致: {}", issue_detail)
                        yield f"data: {json.dumps({'type': 'verification_warning', 'message': f'[输出校验提示] 检测到以下数据可能不一致: {issue_detail}。请以工具实际返回数据为准。', 'issues': verification_issues}, ensure_ascii=False)}\n\n"
                except Exception as ve:
                    logger.warning("[Chat] 输出校验执行异常: {}", ve)
            
            yield f"data: {json.dumps({'type': 'done', 'message': final_message}, ensure_ascii=False)}\n\n"
            
            # ---- 对话持久化 ----
            try:
                state = agent.get_state(config)
                if state and state.values:
                    serialized = [serialize_langchain_message(m) for m in state.values.get("messages", [])]
                    if serialized:
                        persist_conversation(request.thread_id, serialized, {
                            "title": request.message[:50],
                            "estimated_tokens": sum(len(str(m.get("content", ""))) for m in serialized),
                        })
                        logger.debug("[Chat] 对话已持久化: {} 条消息", len(serialized))
            except Exception as e:
                logger.warning("[Chat] 对话持久化失败: {}", e)
            
            # ---- 上下文使用率检查与警告 ----
            try:
                state = agent.get_state(config)
                if state and state.values:
                    current_msgs = state.values.get("messages", [])
                    serialized = [serialize_langchain_message(m) for m in current_msgs]
                    usage_after, total_after, _ = check_context_usage(serialized, SYSTEM_PROMPT)
                    usage_pct = int(usage_after * 100)
                    if usage_after >= CONTEXT_WARNING_THRESHOLD:
                        warning_msg = (
                            f"[上下文使用率已达到 {usage_pct}%，接近 DeepSeek 128K 上限。"
                            "建议新建对话以释放上下文空间，避免后续消息被自动裁剪。]"
                        )
                        yield f"data: {json.dumps({'type': 'context_warning', 'usage': usage_pct, 'tokens': total_after, 'message': warning_msg}, ensure_ascii=False)}\n\n"
                        logger.warning("[Chat] 上下文警告: {}% (~{} tokens)", usage_pct, total_after)
            except Exception as e:
                logger.warning("[Chat] 上下文警告生成失败: {}", e)
            
        except Exception as e:
            t_error = time.time()
            elapsed = t_error - t_stream_start
            logger.error("[Chat] 异常: type={}, msg={}, 已耗时={:.2f}s", type(e).__name__, str(e), elapsed)
            import traceback
            logger.error("[Chat] 异常堆栈:\n{}", traceback.format_exc())
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ---- 文件上传接口 ----

@router.post("/upload", summary="上传简历文件")
async def upload_file(file: UploadFile = File(...), thread_id: str = Query("default")):
    """上传简历文件（支持 PDF/Word/TXT）"""
    logger.info(f"[Upload] 文件名: {file.filename}")
    
    # 验证文件类型
    ext = Path(file.filename).suffix.lower()
    if ext not in [".pdf", ".docx", ".doc", ".txt"]:
        raise HTTPException(status_code=400, detail="不支持的文件格式，请上传 PDF/Word/TXT 文件")
    
    # 保存文件到对话专属目录
    session_dir = UPLOAD_DIR / thread_id
    session_dir.mkdir(parents=True, exist_ok=True)
    file_path = session_dir / file.filename
    
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    # 尝试解析简历
    resume_data = None
    try:
        from resume.parser import extract_resume_text
        resume_text = extract_resume_text(str(file_path))
        if resume_text:
            resume_data = {"text": resume_text, "length": len(resume_text)}
            logger.info("[Upload] 简历解析成功: {}, {} 字符", file.filename, len(resume_text))
        else:
            logger.warning("[Upload] 简历解析返回空: {}", file.filename)
    except Exception as e:
        logger.warning("[Upload] 简历解析失败: {}", e)
    
    return {
        "success": True,
        "message": "文件上传成功",
        "file_name": file.filename,
        "file_size": len(content),
        "file_path": str(file_path.relative_to(UPLOAD_DIR)),
        "resume_data": resume_data
    }


@router.get("/preview-file", summary="获取文件文本内容预览")
async def preview_file(thread_id: str = Query("default"), filename: str = Query(...)):
    """获取上传目录中指定文件的文本内容用于前端预览"""
    from resume.parser import extract_resume_text
    file_path = UPLOAD_DIR / thread_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    text = extract_resume_text(str(file_path))
    logger.info("[Preview] 预览文件: {}, {} 字符", filename, len(text) if text else 0)
    return {"success": True, "text": text or "", "filename": filename}


@router.get("/file-preview", summary="文件二进制预览（iframe嵌入，保留原始格式）")
async def file_preview_binary(thread_id: str = Query("default"), filename: str = Query(...)):
    """
    以二进制形式返回文件内容，用于前端 iframe 嵌入预览。
    DOCX 文件通过 Word COM 转为 PDF 后返回，Chrome/Edge 原生支持 PDF 内嵌渲染。
    完美保留图片、表格、字体、颜色、文本框等所有原始格式。
    """
    from fastapi.responses import FileResponse
    from urllib.parse import quote

    file_path = UPLOAD_DIR / thread_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = file_path.suffix.lower()
    encoded_filename = quote(filename, safe="")

    # PDF 和 TXT 直接返回（浏览器原生支持内嵌预览）
    if ext == ".pdf":
        logger.info("[FilePreview] 直接返回 PDF: {}", filename)
        return FileResponse(file_path, media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}"})

    if ext == ".txt":
        logger.info("[FilePreview] 直接返回 TXT: {}", filename)
        return FileResponse(file_path, media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}"})

    # DOCX 通过 Word COM 转为 PDF（保留全部格式）
    if ext in [".docx", ".doc"]:
        cache_dir = UPLOAD_DIR / thread_id / ".preview_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        pdf_name = file_path.stem + ".pdf"
        pdf_path = cache_dir / pdf_name

        # 缓存命中：PDF 比 DOCX 新，直接使用
        if pdf_path.exists() and pdf_path.stat().st_mtime >= file_path.stat().st_mtime:
            logger.info("[FilePreview] 使用缓存的 PDF: {}", pdf_name)
            return FileResponse(pdf_path, media_type="application/pdf",
                headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(pdf_name, safe='')}"})

        # Word COM 转换 DOCX -> PDF
        logger.info("[FilePreview] Word COM 转换 DOCX -> PDF: {}", filename)
        try:
            from docx2pdf import convert
            convert(str(file_path), str(pdf_path))
            if pdf_path.exists():
                logger.info("[FilePreview] 转换成功: {}, 大小={}", pdf_name, pdf_path.stat().st_size)
                return FileResponse(pdf_path, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(pdf_name, safe='')}"})
            else:
                logger.warning("[FilePreview] Word COM 转换后 PDF 不存在")
        except ImportError:
            logger.warning("[FilePreview] docx2pdf 未安装")
        except Exception as e:
            logger.warning("[FilePreview] Word COM 转换失败: {}", str(e)[:200])

        # 转换失败时降级：返回原始 DOCX（部分浏览器可内嵌渲染）
        logger.info("[FilePreview] 降级返回原始 DOCX")
        return FileResponse(file_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}"})

    raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")


# ---- 状态查询接口 ----

@router.get("/status", summary="获取系统状态")
async def get_status():
    """获取系统运行状态"""
    store = _get_faiss_store()
    
    # 确保 FAISS 已加载
    if store.index is None:
        try:
            store.load()
        except FileNotFoundError:
            pass
    
    mgr = _get_scraper_manager()
    
    return {
        "success": True,
        "faiss_total": store.total_count,
        "supported_platforms": mgr.get_supported_platforms(),
        "model": AI_MODEL,
    }


@router.get("/schedules", summary="获取定时任务列表")
async def list_schedules():
    """获取所有定时搜索任务"""
    scheduler = get_scheduler()
    jobs = scheduler.list_jobs()
    return {"success": True, "jobs": jobs}


@router.delete("/schedules/{job_id}", summary="删除定时任务")
async def delete_schedule(job_id: str):
    """删除指定定时任务"""
    scheduler = get_scheduler()
    ok = scheduler.remove_job(job_id)
    return {"success": ok, "message": "已删除" if ok else "未找到该任务"}


# ---- Cookie/登录相关 ----

@router.get("/cookies/{platform}", summary="检查平台 Cookie 状态")
async def check_cookies(platform: str):
    """检查指定平台 Cookie 状态（快速检查，不验证有效性）"""
    mgr = _get_scraper_manager()
    scraper = mgr.scrapers.get(platform)
    if not scraper:
        return {"success": False, "has_cookies": False, "message": f"未知平台: {platform}"}
    
    has_cookies = hasattr(scraper, "has_cookies") and scraper.has_cookies()
    cookie_count = len(scraper.get_cookies()) if has_cookies else 0
    
    return {
        "success": True,
        "platform": platform,
        "has_cookies": has_cookies,
        "cookie_count": cookie_count
    }


@router.post("/login/{platform}", summary="触发平台登录")
async def trigger_login(platform: str):
    """触發平台登录（BOSS直聘等需要手动登录的平台）"""
    mgr = _get_scraper_manager()
    scraper = mgr.scrapers.get(platform)
    if not scraper:
        return {"success": False, "message": f"未知平台: {platform}"}
    
    if hasattr(scraper, "manual_login"):
        # 使用 run_in_executor 在线程池中运行，避免嵌套事件循环问题
        loop = asyncio.get_running_loop()
        def _do_login():
            return asyncio.run(scraper.manual_login())
        loop.run_in_executor(None, _do_login)
        logger.info("[Login] 已触发 {} 登录（在独立线程中运行）", platform)
        return {"success": True, "message": f"正在打开 {platform} 登录窗口，请在浏览器中完成登录"}
    
    return {"success": False, "message": f"{platform} 不支持手动登录"}
