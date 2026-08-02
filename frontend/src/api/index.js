import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 300000,  // 5分钟超时（Agent 可能耗时较长）
})

export default {
  // 发送消息（SSE 流式），支持 AbortController 终止
  chatStream(message, threadId = 'default', signal = null) {
    return fetch(`/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, thread_id: threadId }),
      signal,
    })
  },

  // 上传文件
  uploadFile(file, threadId) {
    const formData = new FormData()
    formData.append('file', file)
    const params = threadId ? { thread_id: threadId } : {}
    return api.post('/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params,
    })
  },

  // 获取系统状态
  getStatus() {
    return api.get('/status')
  },

  // 检查 Cookie 状态
  checkCookies(platform) {
    return api.get(`/cookies/${platform}`)
  },

  // 触发登录
  triggerLogin(platform) {
    return api.post(`/login/${platform}`)
  },

  // 获取定时任务列表
  getSchedules() {
    return api.get('/schedules')
  },

  // 删除定时任务
  deleteSchedule(jobId) {
    return api.delete(`/schedules/${jobId}`)
  },
}
