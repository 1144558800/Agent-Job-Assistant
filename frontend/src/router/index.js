import { createRouter, createWebHistory } from 'vue-router'
import Chat from '../views/Chat.vue'

const routes = [
  { path: '/', name: 'Chat', component: Chat },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
