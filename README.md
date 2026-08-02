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
copy .env.example .env
# 编辑 .env 文件，填入你的 DeepSeek API Key
AI_API_KEY=sk-your-deepseek-api-key
```

### 3. 安装依赖

```bash
cd backend
pip install -r requirements.txt
playwright install chromium

cd ../frontend
npm install
```

### 4. 启动项目

双击 `start.bat` 或在终端运行：

```bash
python run.py
```

启动后会自动打开浏览器访问 http://localhost:3001