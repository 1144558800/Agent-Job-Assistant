<template>
  <div class="app-layout">
    <!-- 对话列表侧边栏 -->
    <div class="conversation-sidebar" :class="{ collapsed: !sidebarVisible }">
      <div class="sidebar-header">
        <el-button type="primary" @click="createNewConversation" class="new-chat-btn">
          <el-icon><Plus /></el-icon>
          <span>新对话</span>
        </el-button>
      </div>
      <div class="conversation-list">
        <div
          v-for="conv in conversations"
          :key="conv.id"
          class="conversation-item"
          :class="{ active: conv.id === activeConversationId }"
          @click="switchConversation(conv.id)"
        >
          <div class="conv-title">{{ conv.title || '新对话' }}</div>
          <div class="conv-meta">
            <span class="conv-time">{{ formatTime(conv.updatedAt) }}</span>
            <el-button class="conv-delete" text size="small" @click="deleteConversation(conv.id, $event)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>
        <div v-if="conversations.length === 0" class="no-conversations">暂无对话</div>
      </div>
    </div>

    <!-- 切换侧边栏按钮 -->
    <div class="sidebar-toggle" @click="sidebarVisible = !sidebarVisible">
      <el-icon><Fold v-if="sidebarVisible" /><Expand v-else /></el-icon>
    </div>

    <!-- 主聊天区域 -->
    <div class="chat-container" :class="{ 'with-preview': resumePanelVisible }">
      <!-- 顶部标题栏 -->
      <div class="chat-header">
        <h2>Agent 求职筛选助手</h2>
        <div class="header-status">
          <span><span class="status-dot" :class="status.faissTotal > 0 ? 'online' : 'offline'"></span>FAISS: {{ status.faissTotal }}条</span>
          <span><span class="status-dot" :class="status.bossOnline ? 'online' : 'offline'"></span>BOSS直聘</span>
        </div>
      </div>

      <!-- 消息区域 -->
      <div class="chat-messages" ref="messagesContainer">
        <!-- 空状态引导 -->
        <div v-if="messages.length === 0" class="empty-state">
          <el-icon><ChatDotRound /></el-icon>
          <h3>Agent 求职筛选助手</h3>
          <p>通过自然对话完成岗位搜索、分析、匹配等操作</p>
          <ul class="hint-list">
            <li>"帮我搜索北京的 Python 开发岗位"</li>
            <li>"分析刚才搜到的岗位薪资水平"</li>
            <li>"把这些岗位保存到知识库"</li>
            <li>"上传简历并匹配知识库中的岗位"</li>
            <li>"每天早上8点自动搜索 Python 岗位"</li>
            <li>"把岗位数据导出为 Excel"</li>
          </ul>
        </div>

        <!-- 消息列表 -->
        <div v-for="(msg, idx) in messages" :key="idx" class="message" :class="msg.role">
          <div class="avatar">
            <el-icon v-if="msg.role === 'user'"><User /></el-icon>
            <el-icon v-else><Service /></el-icon>
          </div>
          <div class="bubble" :class="msg.role === 'agent' ? 'agent-bubble' : ''">
            <!-- Agent 消息 -->
            <template v-if="msg.role === 'agent'">
              <div v-if="msg.toolCards && msg.toolCards.length > 0">
                <div v-for="(card, ci) in msg.toolCards" :key="ci" class="tool-card" :class="card.status">
                  <el-icon class="tool-icon">
                    <Loading v-if="card.status === 'running'" class="is-loading" />
                    <CircleCheck v-else-if="card.status === 'success'" />
                    <CircleClose v-else />
                  </el-icon>
                  <span>{{ card.text }}</span>
                </div>
              </div>
              <!-- Markdown 内容 + 交互选项 -->
              <div v-if="msg.interactiveOptions && msg.interactiveOptions.length > 0">
                <div v-html="msg.renderedContentBeforeOptions || ''"></div>
                <div class="interactive-options">
                  <div class="options-label">{{ msg.interactiveOptionsLabel || '请选择：' }}</div>
                  <el-radio-group v-if="msg.interactiveOptionsType === 'radio'"
                    v-model="msg.selectedOption" @change="onOptionSelected(msg, idx)">
                    <div v-for="(opt, oi) in msg.interactiveOptions" :key="oi" class="option-item">
                      <el-radio :value="oi">{{ opt }}</el-radio>
                    </div>
                  </el-radio-group>
                  <el-checkbox-group v-else
                    v-model="msg.selectedOptions" @change="onMultiOptionSelected(msg, idx)">
                    <div v-for="(opt, oi) in msg.interactiveOptions" :key="oi" class="option-item">
                      <el-checkbox :value="oi">{{ opt }}</el-checkbox>
                    </div>
                  </el-checkbox-group>
                  <div class="options-actions">
                    <el-button type="primary" size="small" @click="confirmOptions(msg, idx)" :disabled="!hasOptionSelected(msg)">
                      确定
                    </el-button>
                    <span class="options-hint">点击选项后按确定，无需打字</span>
                  </div>
                </div>
                <div v-html="msg.renderedContentAfterOptions || ''" style="margin-top:8px"></div>
              </div>
              <div v-else v-html="msg.renderedContent || msg.content"></div>
              <!-- 结果卡片 -->
              <div v-if="msg.resultCard" class="result-card">
                <div class="stat-row">
                  <div class="stat-item" v-for="(stat, si) in msg.resultCard.stats" :key="si">
                    <div class="stat-num">{{ stat.value }}</div>
                    <div class="stat-label">{{ stat.label }}</div>
                  </div>
                </div>
              </div>
            </template>
            <!-- 用户消息 -->
            <template v-else>
              {{ msg.content }}
            </template>
          </div>
        </div>

        <!-- 打字动画 -->
        <div v-if="isLoading" class="message agent">
          <div class="avatar"><el-icon><Service /></el-icon></div>
          <div class="bubble agent-bubble">
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
          </div>
        </div>
      </div>

      <!-- 输入区域 -->
      <div class="chat-input-area">
        <div class="input-row">
          <el-input v-model="inputMessage" type="textarea" :rows="1" :autosize="{ minRows: 1, maxRows: 4 }"
            placeholder="输入你的需求，按 Enter 发送..." @keydown.enter.exact="handleSend" :disabled="isLoading"
            resize="none" />
          <div class="actions">
            <el-tooltip content="上传简历（PDF/Word/TXT）" placement="top">
              <el-button type="default" circle @click="triggerUpload" :disabled="isLoading">
                <el-icon><Upload /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip content="预览简历" placement="top">
              <el-button type="default" circle @click="toggleResumePanel" :disabled="!resumeOriginalText">
                <el-icon><Document /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip content="发送 (Enter)" placement="top">
              <el-button type="primary" circle @click="handleSend" :disabled="isLoading || !inputMessage.trim()">
                <el-icon><Promotion /></el-icon>
              </el-button>
            </el-tooltip>
          </div>
        </div>
        <div class="upload-hint" v-if="uploadedFile">
          <el-icon style="color:#67c23a"><Document /></el-icon>
          <span class="file-name">已上传: {{ uploadedFile }}</span>
          <el-button text size="small" type="primary" @click="toggleResumePanel" v-if="resumeOriginalText" style="margin-left:8px">预览</el-button>
        </div>
        <div class="upload-hint" v-else>
          <span>支持上传简历文件：PDF / Word / TXT</span>
        </div>
        <div v-if="isLoading" class="stop-row">
          <el-button type="danger" plain @click="handleStop" class="stop-btn">
            <el-icon><VideoPause /></el-icon>
            <span>终止 Agent 操作</span>
          </el-button>
        </div>
        <input ref="fileInput" type="file" accept=".pdf,.doc,.docx,.txt" style="display: none" @change="handleFileSelected" />
      </div>

      <!-- 上传弹窗 -->
      <el-dialog v-model="uploadDialogVisible" title="上传简历" width="450px" :close-on-click-modal="false">
        <div class="upload-tip">
          <p>请选择简历文件进行分析和岗位匹配</p>
          <p style="font-size:12px;color:#c0c4cc;margin-top:4px">支持格式：PDF、Word (.docx/.doc)、TXT</p>
        </div>
        <el-upload class="upload-dialog-area" drag :auto-upload="false" :on-change="handleDialogFileSelected"
          :limit="1" accept=".pdf,.doc,.docx,.txt">
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">拖拽文件到此处或 <em>点击上传</em></div>
        </el-upload>
        <template #footer>
          <el-button @click="uploadDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="confirmUpload" :disabled="!pendingFile">确认上传</el-button>
        </template>
      </el-dialog>
    </div>

    <!-- 简历预览面板 -->
    <div class="resume-panel" :class="{ visible: resumePanelVisible }">
      <div class="resume-panel-header">
        <h3>简历预览 - {{ resumeFileName }}</h3>
        <div class="resume-panel-actions">
          <el-button text size="small" @click="openInNewTab" title="新窗口打开">
            <el-icon><FullScreen /></el-icon>
          </el-button>
          <el-button text @click="resumePanelVisible = false"><el-icon><Close /></el-icon></el-button>
        </div>
      </div>
      <div class="resume-tabs">
        <div class="resume-tab" :class="{ active: resumeActiveTab === 'original' }"
          @click="resumeActiveTab = 'original'">
          原始简历
        </div>
        <div class="resume-tab" :class="{ active: resumeActiveTab === 'polished' }"
          @click="resumeActiveTab = 'polished'" v-if="resumePolishedFile">
          润色后
        </div>
      </div>
      <div class="resume-content">
        <div v-if="resumeActiveTab === 'original'" class="resume-iframe-wrapper">
          <div v-if="resumeIframeLoading" class="iframe-loading">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span>正在加载预览...</span>
          </div>
          <iframe
            :src="originalPreviewUrl"
            class="resume-iframe"
            @load="resumeIframeLoading = false"
            frameborder="0"
          ></iframe>
        </div>
        <div v-else class="resume-iframe-wrapper">
          <div v-if="resumeIframeLoading" class="iframe-loading">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span>正在加载预览...</span>
          </div>
          <iframe
            :src="polishedPreviewUrl"
            class="resume-iframe"
            @load="resumeIframeLoading = false"
            frameborder="0"
          ></iframe>
          <div class="polish-action">
            <span class="polish-file-path">已保存至: {{ resumePolishedPath }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick, computed } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api/index.js'
import MarkdownIt from 'markdown-it'

// ---------- Markdown 渲染器 ----------
const md = new MarkdownIt({ breaks: true, linkify: true })
const defaultLinkRender = md.renderer.rules.link_open || function (tokens, idx, options, env, self) {
  return self.renderToken(tokens, idx, options)
}
md.renderer.rules.link_open = function (tokens, idx, options, env, self) {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLinkRender(tokens, idx, options, env, self)
}

// ---------- 状态 ----------
const inputMessage = ref('')
const messages = ref([])
const isLoading = ref(false)
const messagesContainer = ref(null)
const fileInput = ref(null)
const uploadedFile = ref(null)
const uploadDialogVisible = ref(false)
const pendingFile = ref(null)
const sidebarVisible = ref(true)
const abortController = ref(null)

// ====== 简历预览面板状态 ======
const resumePanelVisible = ref(false)
const resumeFileName = ref('')
const resumeOriginalText = ref('')
const resumeOriginalFile = ref('')  // 原始简历文件名（用于 iframe 预览）
const resumePolishedFile = ref('')  // 润色后简历文件名（用于 iframe 预览）
const resumePolishedPath = ref('')
const resumeActiveTab = ref('original')
const resumeIframeLoading = ref(false)
const currentThreadId = ref('')

// 计算预览 URL
const originalPreviewUrl = computed(() => {
  if (!resumeOriginalFile.value || !currentThreadId.value) return ''
  return `/api/file-preview?thread_id=${currentThreadId.value}&filename=${encodeURIComponent(resumeOriginalFile.value)}`
})
const polishedPreviewUrl = computed(() => {
  if (!resumePolishedFile.value || !currentThreadId.value) return ''
  return `/api/file-preview?thread_id=${currentThreadId.value}&filename=${encodeURIComponent(resumePolishedFile.value)}`
})

// ====== 对话管理 ======
const STORAGE_KEY = 'agent_chat_conversations'
const conversations = ref([])
const activeConversationId = ref(null)

function loadConversations() {
  try {
    const data = localStorage.getItem(STORAGE_KEY)
    if (data) conversations.value = JSON.parse(data)
  } catch (e) {
    console.error('[Chat][日志] 加载对话列表失败:', e)
    conversations.value = []
  }
  if (conversations.value.length === 0) {
    console.log('[Chat][日志] 无对话记录，创建新对话')
    createNewConversation()
  } else {
    const lastId = localStorage.getItem('agent_last_conversation')
    const found = conversations.value.find(c => c.id === lastId)
    if (found) {
      switchConversation(found.id)
    } else {
      switchConversation(conversations.value[0].id)
    }
  }
}

function saveConversations() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations.value))
  } catch (e) {
    console.error('[Chat][日志] 保存对话列表失败:', e)
  }
}

function saveCurrentMessages() {
  const conv = conversations.value.find(c => c.id === activeConversationId.value)
  if (conv && messages.value.length > 0) {
    conv.messages = [...messages.value]
    const firstUserMsg = messages.value.find(m => m.role === 'user')
    if (firstUserMsg && !conv.title) {
      conv.title = firstUserMsg.content.substring(0, 30)
    }
    conv.updatedAt = Date.now()
    saveConversations()
    console.log('[Chat][日志] 已保存对话消息, threadId=', conv.threadId, '消息数=', messages.value.length)
  }
}

function createNewConversation() {
  saveCurrentMessages()
  const newConv = {
    id: 'conv_' + Date.now(),
    title: '',
    messages: [],
    threadId: 'thread_' + Date.now(),
    createdAt: Date.now(),
    updatedAt: Date.now(),
  }
  conversations.value.unshift(newConv)
  saveConversations()
  console.log('[Chat][日志] 新建对话, threadId=', newConv.threadId)
  switchConversation(newConv.id)
}

function switchConversation(convId) {
  saveCurrentMessages()
  const conv = conversations.value.find(c => c.id === convId)
  if (!conv) return
  activeConversationId.value = conv.id
  const loadedMessages = conv.messages ? [...conv.messages] : []
  messages.value = loadedMessages.map(msg => {
    if (msg.role === 'agent' && msg.content) {
      msg.renderedContent = md.render(msg.content)
    }
    return msg
  })
  currentAgentMessage = null
  currentToolCards = []
  currentResultCard = null
  isLoading.value = false
  localStorage.setItem('agent_last_conversation', conv.id)
  resetResumePreview()
  console.log('[Chat][日志] 切换对话, convId=', convId)
  scrollToBottom()
}

function deleteConversation(convId, e) {
  e.stopPropagation()
  const idx = conversations.value.findIndex(c => c.id === convId)
  if (idx === -1) return
  conversations.value.splice(idx, 1)
  saveConversations()
  console.log('[Chat][日志] 删除对话, convId=', convId)
  if (activeConversationId.value === convId) {
    if (conversations.value.length > 0) {
      switchConversation(conversations.value[0].id)
    } else {
      createNewConversation()
    }
  }
}

function formatTime(ts) {
  const d = new Date(ts)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

function resetResumePreview() {
  resumeOriginalText.value = ''
  resumeOriginalFile.value = ''
  resumePolishedFile.value = ''
  resumePolishedPath.value = ''
  resumeFileName.value = ''
  resumeActiveTab.value = 'original'
  resumePanelVisible.value = false
  resumeIframeLoading.value = false
  console.log('[Chat][日志] 简历预览状态已重置')
}

const status = reactive({
  faissTotal: 0,
  bossOnline: false,
})

let currentAgentMessage = null
let currentToolCards = []
let currentResultCard = null

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

async function loadStatus() {
  try {
    const res = await api.getStatus()
    status.faissTotal = res.data.faiss_total || 0
  } catch (e) {
    console.error('[Chat][日志] 加载状态失败:', e)
  }
  try {
    const res = await api.checkCookies('boss')
    status.bossOnline = res.data.has_cookies
  } catch (e) {
    status.bossOnline = false
  }
}

// ====== 简历预览面板控制 ======
function toggleResumePanel() {
  resumePanelVisible.value = !resumePanelVisible.value
  if (resumePanelVisible.value) {
    resumeIframeLoading.value = true
  }
  console.log('[Chat][日志] 简历预览面板:', resumePanelVisible.value ? '打开' : '关闭')
  if (resumePanelVisible.value && !resumePolishedFile.value) {
    resumeActiveTab.value = 'original'
  }
}

function openInNewTab() {
  const url = resumeActiveTab.value === 'original' ? originalPreviewUrl.value : polishedPreviewUrl.value
  if (url) {
    window.open(url, '_blank')
    console.log('[Chat][日志] 新窗口打开预览:', url)
  }
}

// ---------- 发送消息 ----------
async function handleSend() {
  const text = inputMessage.value.trim()
  if (!text || isLoading.value) return

  console.log('[Chat][日志] 用户发送消息:', text.substring(0, 50))
  messages.value.push({ role: 'user', content: text })
  inputMessage.value = ''
  scrollToBottom()

  currentAgentMessage = null
  currentToolCards = []
  currentResultCard = null

  const agentMsgIndex = messages.value.length
  messages.value.push({ role: 'agent', content: '', renderedContent: '', toolCards: [], resultCard: null })
  isLoading.value = true
  scrollToBottom()

  const controller = new AbortController()
  abortController.value = controller

  try {
    const conv = conversations.value.find(c => c.id === activeConversationId.value)
    const threadId = conv ? conv.threadId : 'default'
    currentThreadId.value = threadId
    console.log('[Chat][日志] 发送 SSE 请求, threadId=', threadId)
    const response = await api.chatStream(text, threadId, controller.signal)

    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6)
          if (!data) continue
          try {
            const event = JSON.parse(data)
            processEvent(event, agentMsgIndex)
          } catch (e) {
            console.error('[Chat][日志] 解析事件失败:', e)
          }
        }
      }
    }

    if (buffer.startsWith('data: ')) {
      try {
        const event = JSON.parse(buffer.slice(6))
        processEvent(event, agentMsgIndex)
      } catch (e) {}
    }
  } catch (e) {
    if (e.name === 'AbortError') {
      console.log('[Chat][日志] Agent 操作被用户终止')
      const lastMsg = messages.value[agentMsgIndex]
      if (lastMsg && !lastMsg.content) {
        lastMsg.content = '操作已终止。'
        lastMsg.renderedContent = md.render(lastMsg.content)
      } else if (lastMsg && lastMsg.content) {
        lastMsg.content += '\n\n---\n*操作已终止。*'
        lastMsg.renderedContent = md.render(lastMsg.content)
      }
    } else {
      console.error('[Chat][日志] SSE 错误:', e)
      if (currentAgentMessage) {
        currentAgentMessage.content += `\n\n[请求超时或出错: ${e.message}]`
        updateAgentMessage(agentMsgIndex)
      } else {
        messages.value[agentMsgIndex].content = `抱歉，请求出错了: ${e.message}`
        messages.value[agentMsgIndex].renderedContent = md.render(messages.value[agentMsgIndex].content)
      }
    }
  } finally {
    isLoading.value = false
    abortController.value = null
    saveCurrentMessages()
    scrollToBottom()
    console.log('[Chat][日志] 发送完成')
  }
}

function handleStop() {
  if (abortController.value) {
    abortController.value.abort()
    console.log('[Chat][日志] 用户触发终止操作')
  }
}

// ====== SSE 事件处理 ======
function processEvent(event, agentMsgIndex) {
  currentAgentMessage = messages.value[agentMsgIndex]

  switch (event.type) {
    case 'token':
      currentAgentMessage.content += event.content
      // 实时检测交互选项模式
      detectInteractiveOptions(currentAgentMessage)
      currentAgentMessage.renderedContent = md.render(currentAgentMessage.content)
      break

    case 'tool_start':
      console.log('[Chat][日志] 工具开始:', event.tool)
      currentToolCards.push({
        tool: event.tool,
        text: getToolStartText(event.tool, event.input),
        status: 'running',
      })
      currentAgentMessage.toolCards = [...currentToolCards]
      break

    case 'tool_end':
      console.log('[Chat][日志] 工具完成:', event.tool)
      const runningIdx = currentToolCards.map(c => c.status).lastIndexOf('running')
      if (runningIdx >= 0) currentToolCards[runningIdx].status = 'success'
      currentAgentMessage.toolCards = [...currentToolCards]
      break

    case 'search_result':
      currentResultCard = {
        stats: [
          { label: '搜索岗位', value: event.count },
          ...(event.platforms ? Object.entries(event.platforms).map(([k, v]) => ({ label: k, value: v })) : []),
        ]
      }
      currentAgentMessage.resultCard = currentResultCard
      break

    case 'analysis_result':
      if (event.data) {
        const d = event.data
        const stats = [{ label: '总岗位', value: d.total_jobs }]
        if (d.salary_avg) stats.push({ label: '平均薪资', value: d.salary_avg + 'K' })
        if (d.top_companies && Object.keys(d.top_companies).length > 0) {
          stats.push({ label: '最多公司', value: Object.keys(d.top_companies)[0] })
        }
        currentResultCard = { stats }
        currentAgentMessage.resultCard = currentResultCard
      }
      break

    case 'export_result':
      if (event.data && event.data.success) {
        currentToolCards.push({
          text: `导出完成: ${event.data.file_name} (${event.data.count}条)`,
          status: 'success',
        })
        currentAgentMessage.toolCards = [...currentToolCards]
      }
      break

    case 'polish_result':
      console.log('[Chat][日志] 简历润色结果:', event.data)
      if (event.data && event.data.success) {
        // 显示润色完成卡片
        currentToolCards.push({
          text: `简历润色完成: ${event.data.output_filename || '已生成文件'}`,
          status: 'success',
        })
        currentAgentMessage.toolCards = [...currentToolCards]

        // 更新简历预览面板 - 润色后文件
        if (event.data.output_filename) {
          resumePolishedFile.value = event.data.output_filename
          resumePolishedPath.value = event.data.output_file || ''
          resumeActiveTab.value = 'polished'
          resumePanelVisible.value = true
          resumeIframeLoading.value = true
          console.log('[Chat][日志] 润色文件预览已就绪:',
            event.data.output_filename, '路径=', event.data.output_file)
        }
        if (event.data.output_filename) {
          resumeFileName.value = resumeFileName.value || event.data.output_filename
        }
      }
      break

    case 'error':
      currentAgentMessage.content += `\n\n> 出错: ${event.message}`
      currentAgentMessage.renderedContent = md.render(currentAgentMessage.content)
      break

    case 'context_warning':
      const usagePct = event.usage || 0
      const tokenCount = event.tokens || 0
      currentAgentMessage.content += `\n\n---\n### [系统提示] 上下文使用率: ${usagePct}% (~${tokenCount} tokens)\n\n当前对话上下文已接近 DeepSeek 128K 上限，建议新建对话以释放上下文空间，避免后续消息被自动裁剪。\n`
      currentAgentMessage.renderedContent = md.render(currentAgentMessage.content)
      break

    case 'verification_warning':
      console.warn('[Verification]', event.message)
      currentAgentMessage.content += `\n\n---\n### [数据校验提醒] ${event.message}\n`
      currentAgentMessage.renderedContent = md.render(currentAgentMessage.content)
      break

    case 'done':
      break
  }
  scrollToBottom()
}

function updateAgentMessage(agentMsgIndex) {
  if (messages.value[agentMsgIndex]) {
    messages.value[agentMsgIndex].renderedContent = md.render(messages.value[agentMsgIndex].content)
  }
}

function getToolStartText(tool, input) {
  const map = {
    'search_jobs': '正在多平台搜索岗位...',
    'save_to_knowledge': '正在保存到知识库...',
    'query_knowledge': '正在查询知识库...',
    'analyze_jobs': '正在分析岗位数据...',
    'match_resume': '正在匹配简历...',
    'check_login_status': '正在检查登录状态...',
    'export_excel': '正在导出 Excel...',
    'schedule_search': '正在创建定时任务...',
    'polish_resume': '正在 AI 润色简历...',
  }
  return map[tool] || `正在执行: ${tool}`
}

// ====== 交互选项检测与处理 ======
function detectInteractiveOptions(msg) {
  // 检测 Agent 消息中是否包含需要用户选择的选项
  // 模式1: 编号列表 "1. xxx\n2. xxx\n3. xxx"
  // 模式2: "请选择:" / "请选择以下" + 选项列表
  const content = msg.content || ''
  if (!content.includes('\n')) return

  // 检测选项模式
  const optionPatterns = [
    // 编号列表: "1. ", "2. ", "3. "
    /(?:请选择|你想|您想|选择|挑选).*?[\s\S]*?(\d+\.\s+.+?(?:\n|$)){2,}/,
    // "你可以选择：" + 列表
    /(?:你可以|您可以|请).*?[选择挑选].*?\n\s*[-*•\d]+[.)、]\s+.+/,
  ]

  let matched = false
  for (const pattern of optionPatterns) {
    if (pattern.test(content)) {
      matched = true
      break
    }
  }
  if (!matched) return

  // 解析选项行
  const lines = content.split('\n')
  const optionLines = []
  let inOptions = false
  let optionsLabel = '请选择：'
  let optionsType = 'radio' // 默认单选
  let preambleLines = []
  let postambleLines = []
  let foundOptionsEnd = false

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim()
    
    // 检测选择题引导语
    if (/(?:请选择|你想|您想|你想选|请选择以下|可以选择|请挑选)/.test(line)) {
      inOptions = true
      optionsLabel = line
      continue
    }

    // 检测选项行 (1. xxx / - xxx / * xxx)
    const optionMatch = line.match(/^(\d+)[.)、]\s+(.+)/)
    const bulletMatch = line.match(/^[-*•]\s+(.+)/)

    if (inOptions && (optionMatch || bulletMatch)) {
      const text = optionMatch ? optionMatch[2].trim() : bulletMatch[1].trim()
      optionLines.push(text)
      continue
    }

    // 如果已经找到选项并且当前行不是选项行且不是空行，说明选项部分结束
    if (inOptions && optionLines.length > 0 && line !== '' && !optionMatch && !bulletMatch) {
      foundOptionsEnd = true
      inOptions = false
      postambleLines.push(line)
      continue
    }

    if (!inOptions && !foundOptionsEnd) {
      preambleLines.push(line)
    } else if (foundOptionsEnd) {
      postambleLines.push(line)
    }
  }

  // 检查是否有多选框的关键词
  if (/(?:多选|多项|勾选|复选)/.test(content)) {
    optionsType = 'checkbox'
  }

  if (optionLines.length >= 2 && optionLines.length <= 6) {
    console.log('[Chat][日志] 检测到交互选项:', optionLines.length, '个, 类型=', optionsType)
    msg.interactiveOptions = optionLines
    msg.interactiveOptionsLabel = optionsLabel
    msg.interactiveOptionsType = optionsType
    msg.selectedOption = null
    msg.selectedOptions = []
    msg.renderedContentBeforeOptions = preambleLines.length > 0 ? md.render(preambleLines.join('\n')) : ''
    msg.renderedContentAfterOptions = postambleLines.length > 0 ? md.render(postambleLines.join('\n')) : ''
  }
}

function hasOptionSelected(msg) {
  if (msg.interactiveOptionsType === 'radio') {
    return msg.selectedOption !== null && msg.selectedOption !== undefined && msg.selectedOption !== ''
  }
  return msg.selectedOptions && msg.selectedOptions.length > 0
}

function onOptionSelected(msg) {
  console.log('[Chat][日志] 用户单选选项:', msg.interactiveOptions[msg.selectedOption])
}

function onMultiOptionSelected(msg) {
  console.log('[Chat][日志] 用户多选选项:', msg.selectedOptions.map(i => msg.interactiveOptions[i]))
}

function confirmOptions(msg, idx) {
  let choiceText = ''
  if (msg.interactiveOptionsType === 'radio') {
    choiceText = msg.interactiveOptions[msg.selectedOption]
    console.log('[Chat][日志] 用户确认单选:', choiceText)
  } else {
    choiceText = msg.selectedOptions.map(i => msg.interactiveOptions[i]).join('、')
    console.log('[Chat][日志] 用户确认多选:', choiceText)
  }

  // 清除交互选项，恢复为普通内容
  msg.interactiveOptions = []
  msg.interactiveOptionsLabel = ''
  msg.renderedContentBeforeOptions = ''
  msg.renderedContentAfterOptions = ''

  // 自动发送用户选择
  inputMessage.value = choiceText
  nextTick(() => handleSend())
}

// ====== 文件上传 ======
function triggerUpload() {
  uploadDialogVisible.value = true
  pendingFile.value = null
  console.log('[Chat][日志] 打开上传弹窗')
}

function handleFileSelected(e) {
  const file = e.target.files[0]
  if (file) uploadFile(file)
}

function handleDialogFileSelected(file) {
  pendingFile.value = file.raw
  console.log('[Chat][日志] 文件已选择:', file.name)
}

async function confirmUpload() {
  if (!pendingFile.value) return
  console.log('[Chat][日志] 确认上传文件:', pendingFile.value.name)
  await uploadFile(pendingFile.value)
  uploadDialogVisible.value = false
  pendingFile.value = null
}

async function uploadFile(file) {
  try {
    const conv = conversations.value.find(c => c.id === activeConversationId.value)
    const threadId = conv ? conv.threadId : 'default'
    currentThreadId.value = threadId
    console.log('[Chat][日志] 开始上传文件:', file.name, 'threadId=', threadId)
    const res = await api.uploadFile(file, threadId)
    if (res.data.success) {
      uploadedFile.value = res.data.file_name
      console.log('[Chat][日志] 文件上传成功:', res.data.file_name,
        '文本长度=', res.data.resume_data ? res.data.resume_data.length : 0)

      ElMessage.success('简历上传成功！可以通过"匹配我的简历"或"分析简历"来使用')

      // 功能1: 存储简历信息用于 iframe 分屏预览
      if (res.data.resume_data && res.data.resume_data.text) {
        resumeOriginalText.value = res.data.resume_data.text
      }
      resumeOriginalFile.value = res.data.file_name
      resumeFileName.value = res.data.file_name
      resumeActiveTab.value = 'original'
      resumePanelVisible.value = true
      resumeIframeLoading.value = true
      console.log('[Chat][日志] 简历预览面板已更新, iframe URL=', originalPreviewUrl.value)

      // 告知 Agent
      messages.value.push({ role: 'user', content: `我已上传简历: ${res.data.file_name}` })
      scrollToBottom()
    }
  } catch (e) {
    console.error('[Chat][日志] 文件上传失败:', e)
    ElMessage.error('文件上传失败: ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(() => {
  isLoading.value = false
  abortController.value = null
  console.log('[Chat][日志] 组件已挂载')
  loadConversations()
  loadStatus()
})
</script>
