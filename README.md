# Agent 求职筛选助手

基于 AI Agent 的智能求职筛选与自动化沟通系统。支持多平台岗位搜索、简历智能匹配、桌面自动化沟通、定时任务等完整求职流程。

## 功能特性

- **多平台岗位搜索** - 支持 BOSS直聘、猎聘、前程无忧(51job)、智联招聘四大平台
- **AI Agent 对话** - 基于 LangGraph 的智能 Agent，自然语言交互完成求职操作
- **简历智能匹配** - 上传简历后 AI 自动分析岗位匹配度，精准筛选
- **桌面自动化沟通** - 控制真实浏览器自动搜索、筛选、匹配、打招呼（反爬无忧）
- **RAG 知识库** - FAISS 向量检索，快速查询已搜索的岗位信息
- **定时搜索** - 设置定时任务自动搜索并推送新岗位
- **简历润色** - AI 辅助优化简历内容
- **Hermes 自进化** - 经验记忆系统，越用越智能

## 项目架构

```
Agent求职筛选助手/
├── backend/               # 后端 (Python FastAPI + LangGraph)
│   ├── agent/             # AI Agent 核心（LangGraph、工具、记忆）
│   ├── api/               # API 路由层
│   ├── rag/               # RAG 知识库（FAISS 向量检索）
│   ├── resume/            # 简历解析、匹配、润色
│   ├── scrapers/          # 多平台爬虫
│   ├── scheduler/         # 定时任务调度
│   └── config.py          # 全局配置
├── frontend/              # 前端 (Vue 3 + Element Plus + Vite)
│   └── src/
│       ├── views/Chat.vue # 主聊天界面
│       └── api/index.js   # 后端 API 调用
├── .env.example           # 环境变量模板
├── run.py                 # 启动器（守护进程模式）
└── run.bat                # Windows 一键启动
```

## 快速开始

### 环境要求

- **Python** >= 3.10
- **Node.js** >= 18
- **Windows** 操作系统（桌面自动化功能依赖 Windows API）

### 安装步骤

**1. 克隆项目**

```bash
git clone https://github.com/1144558800/Agent-Job-Assistant.git
cd Agent-Job-Assistant
```

**2. 配置 API 密钥**

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env，填入你的 DeepSeek API Key（必填）
# AI_API_KEY=你的密钥
```

> DeepSeek API Key 获取地址：https://platform.deepseek.com

**3. 安装后端依赖**

```bash
cd backend
pip install -r requirements.txt
cd ..
```

**4. 安装前端依赖**

```bash
cd frontend
npm install
cd ..
```

**5. 启动服务**

Windows 下双击 `run.bat`，或命令行执行：

```bash
python run.py
```

服务启动后会自动打开浏览器访问 `http://localhost:3001`。

### 手动启动

```bash
# 终端1：启动后端 (端口 8001)
cd backend
python run_server.py

# 终端2：启动前端 (端口 3001)
cd frontend
npx vite --port 3001
```

## 使用指南

### 1. 上传简历

在聊天界面左侧面板上传 PDF/Word/TXT 格式的简历，Agent 会自动解析并用于后续匹配。

### 2. 搜索岗位

在聊天对话框中输入：

```
帮我在猎聘上搜索 AI应用工程师 岗位，南京，月薪不低于15K
```

Agent 会调用爬虫搜索岗位并存入知识库。

### 3. 桌面自动化沟通

**前提：确保你已经用浏览器登录了目标招聘网站（BOSS直聘/猎聘等）。**

```
帮我在 BOSS直聘 上自动搜索 AI开发工程师，深圳，月薪20K以上，
匹配度80%以上的帮我自动打招呼
```

Agent 会：
1. 在你的浏览器中打开招聘网站搜索页面
2. 逐个打开岗位详情，OCR 读取岗位描述
3. AI 匹配你的简历与岗位要求
4. 匹配度达标时自动点击"立即沟通"并发送招呼语
5. 操作结束后返回完整日志报告

**停止自动化：** 在启动 Agent 的终端窗口中按 `Ctrl+C`。

### 4. 定时搜索

```
帮我设置每天早上9点自动搜索 Python开发 岗位，北京
```

## 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | Vue 3, Element Plus, Vite, Axios, Markdown-it |
| **后端** | FastAPI, Uvicorn, LangGraph, Loguru |
| **AI** | DeepSeek API (兼容 OpenAI), Ollama 本地模型 |
| **向量检索** | FAISS, text2vec-base-chinese |
| **桌面自动化** | PyAutoGUI, PaddleOCR, msvcrt |
| **爬虫** | aiohttp, BeautifulSoup4, PyQuery |
| **定时任务** | APScheduler |

## 可选配置

### 使用其他 AI 模型

支持任何 OpenAI 兼容的 API，只需修改 `.env`：

```env
# 通义千问
AI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_MODEL=qwen-plus

# 智谱 GLM
AI_API_BASE=https://open.bigmodel.cn/api/paas/v4
AI_MODEL=glm-4-flash
```

### 使用 Ollama 本地模型

```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
```

## 常见问题

**Q: 桌面自动化功能支持哪些浏览器？**
A: 支持搜狗浏览器、Chrome、Edge、Firefox、360浏览器等主流浏览器。自动化通过截图+OCR+模拟键盘鼠标操作，不使用 WebDriver，不会被反爬系统检测。

**Q: 为什么自动化沟通时所有岗位都被跳过了？**
A: 请确保已在左侧面板上传了简历。没有简历时 Agent 无法匹配岗位，会拒绝执行自动化。

**Q: 自动化操作期间可以正常使用电脑吗？**
A: 不可以，自动化会接管鼠标和键盘。紧急情况可将鼠标移至屏幕左上角触发 PyAutoGUI 的紧急停止。

## 项目许可

MIT License

## 免责声明

本项目仅供学习研究使用。使用桌面自动化功能时，请遵守相关招聘平台的用户协议，合理控制操作频率。
