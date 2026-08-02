# -*- coding: utf-8 -*-
"""项目启动器 - 带守护进程，后端崩溃自动重启"""
import subprocess
import sys
import os
import time
import webbrowser
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IS_WIN = sys.platform == "win32"

print("=" * 50)
print("  Agent 求职筛选助手 - 启动中（守护模式）")
print("=" * 50)
print()

# ---- 配置 ----
BACKEND_PORT = 8001
FRONTEND_PORT = 3001
BACKEND_HEALTH_URL = "http://localhost:{}/api/status".format(BACKEND_PORT)
FRONTEND_HEALTH_URL = "http://localhost:{}".format(FRONTEND_PORT)
MAX_RESTART = 5        # 最大自动重启次数
HEALTH_CHECK_INTERVAL = 10   # 健康检查间隔（秒）
RESTART_COOLDOWN = 3    # 重启前等待（秒）


def check_health(url, timeout=3):
    """检查服务是否存活"""
    try:
        req = urllib.request.Request(url)
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False


def start_backend():
    """启动后端服务，返回 Popen 对象"""
    backend_py = os.path.join(BASE_DIR, "backend", "run_server.py")
    if not os.path.exists(backend_py):
        print("[致命错误] 找不到后端入口: {}".format(backend_py))
        return None

    print("[后端] 启动中...")
    proc = subprocess.Popen(
        [sys.executable, backend_py],
        cwd=os.path.join(BASE_DIR, "backend"),
        creationflags=subprocess.CREATE_NEW_CONSOLE if IS_WIN else 0,
    )
    return proc


def start_frontend():
    """启动前端服务，返回 Popen 对象"""
    frontend_dir = os.path.join(BASE_DIR, "frontend")
    if not os.path.exists(frontend_dir):
        print("[致命错误] 找不到前端目录: {}".format(frontend_dir))
        return None

    print("[前端] 启动中...")
    if IS_WIN:
        args = "npx vite --port {}".format(FRONTEND_PORT)
    else:
        args = ["npx", "vite", "--port", str(FRONTEND_PORT)]

    try:
        proc = subprocess.Popen(
            args,
            cwd=frontend_dir,
            creationflags=subprocess.CREATE_NEW_CONSOLE if IS_WIN else 0,
            shell=IS_WIN,
        )
        return proc
    except (FileNotFoundError, OSError) as e:
        print("[错误] 启动前端失败: {}".format(e))
        print("请确认 Node.js 已安装: https://nodejs.org")
        return None


def wait_service(label, url, timeout=90):
    """等待服务就绪"""
    print("[{}] 等待就绪...".format(label))
    for i in range(timeout // 2):
        if check_health(url, timeout=2):
            print("[{}] 已就绪!".format(label))
            return True
        if i % 5 == 0 and i > 0:
            print("[{}]   等待中... ({}/{})".format(label, i * 2, timeout))
        time.sleep(2)
    print("[{}] 启动超时".format(label))
    return False


# ========== 主流程 ==========

# 1. 启动后端
backend = start_backend()
if backend is None:
    input("按任意键退出...")
    sys.exit(1)

# 2. 等待后端
if not wait_service("后端", BACKEND_HEALTH_URL, 90):
    print("[警告] 后端启动超时，继续启动前端...")

# 3. 启动前端
frontend = start_frontend()
if frontend is None:
    backend.terminate()
    input("按任意键退出...")
    sys.exit(1)

# 4. 等待前端
wait_service("前端", FRONTEND_HEALTH_URL, 60)

print()
print("=" * 50)
print("  启动完成！")
print("  后端: http://localhost:{}".format(BACKEND_PORT))
print("  前端: http://localhost:{}".format(FRONTEND_PORT))
print("=" * 50)
print()
print("守护模式已启用：后端崩溃将自动重启（最多{}次）".format(MAX_RESTART))
print("关闭此窗口或按 Ctrl+C 停止所有服务")
print()

# 打开浏览器
webbrowser.open("http://localhost:{}".format(FRONTEND_PORT))

# ========== 守护循环 ==========
restart_count = 0
first_check = True

try:
    while True:
        time.sleep(HEALTH_CHECK_INTERVAL)

        # 检查后端
        if not check_health(BACKEND_HEALTH_URL):
            print()
            print("[守护] {} 后端服务无响应！".format(
                time.strftime("%H:%M:%S")))

            if restart_count >= MAX_RESTART:
                print("[守护] 已达最大重启次数({})，不再自动重启".format(MAX_RESTART))
                print("[守护] 请手动检查后端窗口的错误信息")
                continue

            # 杀掉旧进程
            try:
                backend.terminate()
                time.sleep(1)
                backend.kill()
            except Exception:
                pass

            restart_count += 1
            print("[守护] 第 {}/{} 次尝试重启后端...".format(
                restart_count, MAX_RESTART))
            time.sleep(RESTART_COOLDOWN)

            backend = start_backend()
            if backend is None:
                print("[守护] 后端启动失败！")
                continue

            if wait_service("后端", BACKEND_HEALTH_URL, 30):
                print("[守护] 后端恢复成功！")
            else:
                print("[守护] 后端恢复失败，请检查")

        # 检查前端
        if not check_health(FRONTEND_HEALTH_URL):
            print("[守护] {} 前端服务无响应！".format(
                time.strftime("%H:%M:%S")))
            # 前端不自动重启（npx 启动复杂），只提醒
            print("[守护] 请手动重启前端")

except KeyboardInterrupt:
    print()
    print("正在关闭服务...")
    backend.terminate()
    if frontend is not None:
        frontend.terminate()
    print("已停止")
    sys.exit(0)
