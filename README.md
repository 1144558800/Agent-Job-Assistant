# Agent 求职筛选助手

基于 AI 的智能求职筛选与自动化沟通系统，支持多平台职位搜索、简历匹配、AI 润色、定时任务和自动化投递。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + Vite + Element Plus + Pinia |
| 后端 | FastAPI + LangGraph + FAISS + Playwright |
| AI | DeepSeek API（OpenAI 兼容） |
| 数据库 | FAISS（向量数据库） + 本地 JSON 存储 |

## 核心功能

- **多平台职位搜索**：支持 BOSS 直聘、猎聘、前程无忧(51Job)、智联招聘四大平台
- **AI 简历解析与匹配**：自动解析 PDF/Word/TXT 简历，与岗位智能匹配
- **简历 AI 润色**：保留原始 docx 格式，AI 精准润色工作/项目经验
- **AI 对话交互**：基于 LangGraph ReAct Agent 的自然语言交互
- **定时任务**：支持 Cron 表达式定时搜索，自动保存到 FAISS 知识库
- **Hermes 自进化记忆系统**：记录投递/沟通历史，积累经验，持续优化策略
- **Guardrails 安全约束**：频率熔断、内容审核、操作确认、审计日志
- **桌面自动化**：模拟真人操作招聘平台，支持自动打招呼

## 快速开始

### 1. 环境要求

- Python 3.10+
- Node.js 18+
- Windows 10/11

### 2. 配置 API Key

```bash
# 复制环境变量模板
copy .env.example .env

# 编辑 .env 文件，填入你的 DeepSeek API Key
AI_API_KEY=sk-your-deepseek-api-key
```

### 3. 安装依赖

```bash
# 后端依赖
cd backend
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium

# 前端依赖
cd frontend
npm install
```

### 4. 启动项目

双击 `start.bat` 或在终端运行：

```bash
python run.py
```

启动后会自动打开浏览器访问 http://localhost:3001

### 5. 登录招聘平台

首次使用前需要登录各招聘平台获取 Cookie：
- 在前端界面点击"登录 BOSS 直聘"等按钮
- 在弹出的浏览器窗口中扫码登录
- Cookie 会自动保存，后续搜索无需重复登录

## 项目结构

```
Agent求职筛选助手/
├── backend/
│   ├── main.py              # FastAPI 主应用
│   ├── config.py            # 全局配置
│   ├── run_server.py        # 后端启动脚本
│   ├── api/                 # API 路由
│   │   ├── routes.py        # 核心 API（chat SSE、upload、status 等）
│   │   └── models.py        # Pydantic 模型
│   ├── agent/               # AI Agent 模块
│   │   ├── graph.py         # LangGraph ReAct Agent
│   │   ├── tools.py         # Agent 工具函数（17个）
│   │   ├── state.py         # Agent 状态定义
│   │   ├── guardrails.py    # 安全约束层
│   │   ├── context_manager.py    # 对话持久化
│   │   ├── apply_manager.py      # 投递管理
│   │   ├── hermes_memory.py      # 自进化记忆系统
│   │   └── desktop_controller.py # 桌面自动化
│   ├── scrapers/            # 多平台爬虫
│   │   ├── boss.py          # BOSS 直聘
│   │   ├── liepin.py        # 猎聘
│   │   ├── job51.py         # 前程无忧
│   │   ├── zhaopin.py       # 智联招聘
│   │   └── scraper_manager.py    # 爬虫管理器
│   ├── rag/                 # RAG 知识库
│   │   ├── faiss_store.py   # FAISS 向量存储
│   │   ├── embeddings.py    # 向量化服务
│   │   └── qa_engine.py     # QA 引擎
│   ├── resume/              # 简历处理
│   │   ├── parser.py        # PDF/Word 解析
│   │   ├── matcher.py       # 岗位匹配
│   │   └── resume_editor.py # AI 润色
│   └── scheduler/           # 定时任务
│       └── scheduler.py     # APScheduler 调度
├── frontend/
│   ├── src/
│   │   ├── App.vue          # 根组件
│   │   ├── main.js          # 入口文件
│   │   ├── views/Chat.vue   # 聊天主界面
│   │   ├── api/index.js     # API 封装
│   │   └── router/index.js  # 路由配置
│   ├── package.json
│   └── vite.config.js
├── .env.example             # 环境变量模板
├── run.py                   # 项目启动器（守护模式）
├── start.bat                # 一键启动脚本
├── run.bat                  # 简单启动脚本
└── 关闭服务.bat             # 关闭服务脚本
```

## 使用说明

在聊天窗口中通过自然语言与 Agent 交互：

- "帮我搜索北京的 Python 开发岗位"
- "分析刚才搜到的岗位薪资水平"
- "把这些岗位保存到知识库"
- "上传简历并匹配知识库中的岗位"
- "每天早上8点自动搜索 Python 岗位"
- "把岗位数据导出为 Excel"

## 注意事项

1. 首次使用需要配置 DeepSeek API Key（在 .env 文件中）
2. 爬虫功能需要安装 Playwright 浏览器：`playwright install chromium`
3. 自动化投递前请先在对应平台手动登录保存 Cookie
4. 请遵守各招聘平台的使用条款，合理使用自动化功能
