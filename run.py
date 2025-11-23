import pyautogui
import time
import socket
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
from datetime import datetime
import logging
import logging.handlers
import os

app = Flask(__name__)
CORS(app)

# 日志目录与配置：同时写入日志文件和控制台，支持日志轮转
if not os.path.exists("logs"):
    os.makedirs("logs")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 使用RotatingFileHandler实现日志轮转：单个文件最大10MB，保留7个备份文件
file_handler = logging.handlers.RotatingFileHandler(
    "logs/app.log",
    maxBytes=10*1024*1024,  # 10MB
    backupCount=7,  # 保留7个备份文件
    encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# 性能监控
try:
    from performance_monitor import monitor
    PERFORMANCE_MONITORING = True
except ImportError:
    PERFORMANCE_MONITORING = False
    monitor = None

@app.before_request
def log_request_info():
    """记录请求信息并监控性能"""
    if PERFORMANCE_MONITORING:
        request.start_time = time.time()

@app.after_request
def after_request(response):
    """请求后处理：记录性能数据"""
    if PERFORMANCE_MONITORING and hasattr(request, 'start_time'):
        response_time = time.time() - request.start_time
        endpoint = f"{request.method} {request.path}"
        is_error = response.status_code >= 400
        monitor.record_request(endpoint, response_time, is_error)
    return response

def get_pc_name():
    """
    获取当前计算机的名称
    """
    return socket.gethostname()

def simulate_keypress(key='f7'):
    """
    模拟按下指定的键盘按键（默认 F7）
    """
    logger.info(f"Simulating pressing the '{key}' key...")
    pyautogui.press(key)
    logger.info(f"Key '{key}' pressed.")

@app.route('/run', methods=['POST'])
def run_script():
    """
    从请求中获取按键参数，并触发按键模拟
    """
    data = request.get_json() or {}
    key = data.get("key", "f7")
    simulate_keypress(key)
    return "Script executed on server", 200

@app.route('/test', methods=['GET'])
def test_connection():
    """
    用于测试连接的接口，不会执行任何操作，只返回连接成功的响应
    """
    return "Connected", 200

@app.route('/health', methods=['GET'])
def health_check():
    """
    健康检查端点，返回系统状态和性能数据
    """
    health_status = {
        'status': 'healthy',
        'timestamp': time.time(),
        'pc_name': get_pc_name(),
        'ip': get_client_ip()
    }
    if PERFORMANCE_MONITORING:
        health_status['performance'] = monitor.get_stats()
        health_status['system'] = monitor.get_system_info()
    return jsonify(health_status), 200

def get_ip_addresses():
    """
    获取本机所有 IP 地址
    """
    host_name = socket.gethostname()
    try:
        host_ips = socket.gethostbyname_ex(host_name)[2]
    except socket.error:
        host_ips = ['127.0.0.1']
    return host_ips

def get_client_ip():
    """
    从本机所有 IP 中选择一个符合 192.168.0.x 且不是 192.168.0.254 的 IP
    """
    ips = get_ip_addresses()
    for ip in ips:
        if (ip.startswith("192.168.0.") or ip.startswith("192.168.1.")) and ip != "192.168.0.254":
            return ip
    return None

# 创建全局Session用于连接池复用，减少连接开销
heartbeat_session = requests.Session()
heartbeat_session.headers.update({
    'Connection': 'keep-alive',
    'Keep-Alive': 'timeout=30, max=100'
})

def periodic_send_ip():
    """
    智能心跳机制：错峰发送 + 连接池复用 + 动态间隔调整
    1. 根据IP地址计算偏移时间，避免所有客户端同时发送
    2. 使用连接池复用TCP连接，减少连接建立时间
    3. 根据服务器响应时间动态调整心跳间隔
    """
    # 计算错峰偏移：根据IP地址最后一段计算0-4秒的偏移
    client_ip = get_client_ip()
    if client_ip:
        try:
            ip_last_octet = int(client_ip.split('.')[-1])
            offset = (ip_last_octet % 5)  # 0-4秒的偏移
        except:
            offset = 0
    else:
        offset = 0
    
    # 心跳间隔参数
    base_interval = 3  # 基础间隔3秒
    min_interval = 1   # 最小间隔1秒
    max_interval = 10  # 最大间隔10秒
    current_interval = base_interval + offset  # 初始间隔 = 基础间隔 + 偏移
    
    consecutive_success = 0
    consecutive_failures = 0
    
    while True:
        start_time = time.time()
        client_ip = get_client_ip()
        pc_name = get_pc_name()
        
        if client_ip:
            try:
                # 注册IP
                url = "http://192.168.0.254:5000/api/ips"
                payload = {"ip": client_ip, "pc_name": pc_name}
                response = heartbeat_session.post(url, json=payload, timeout=2)
                
                if response.status_code == 200:
                    elapsed = time.time() - start_time
                    consecutive_success += 1
                    consecutive_failures = 0
                    # 如果响应快（<100ms），可以缩短间隔
                    if elapsed < 0.1 and consecutive_success > 5:
                        current_interval = max(min_interval, current_interval - 0.5)
                    # 如果响应慢（>500ms），延长间隔
                    elif elapsed > 0.5:
                        current_interval = min(max_interval, current_interval + 1)
                    logger.info(f"Heartbeat sent. IP: {client_ip}, PC: {pc_name}, Interval: {current_interval:.1f}s, Elapsed: {elapsed:.2f}s")
                else:
                    consecutive_failures += 1
                    current_interval = min(max_interval, current_interval + 1)
                    logger.warning(f"IP registration failed (status {response.status_code}). IP: {client_ip}, PC: {pc_name}, Next interval: {current_interval:.1f}s")
                    
            except requests.exceptions.Timeout:
                consecutive_failures += 1
                current_interval = min(max_interval, current_interval + 1)
                logger.error(f"Heartbeat/IP registration timed out. IP: {client_ip}, PC: {pc_name}, Next interval: {current_interval:.1f}s")
            except Exception as e:
                consecutive_failures += 1
                current_interval = min(max_interval, current_interval + 1)
                logger.error(f"Error sending heartbeat/IP registration: {e}. IP: {client_ip}, PC: {pc_name}, Next interval: {current_interval:.1f}s")
        else:
            consecutive_failures += 1
            current_interval = min(max_interval, current_interval + 1)
            logger.warning(f"No valid client IP found. Next interval: {current_interval:.1f}s")
        
        time.sleep(current_interval)

if __name__ == "__main__":
    # 导入清理工具
    try:
        from cleanup_utils import setup_periodic_cleanup
        setup_periodic_cleanup(log_dir="logs", screenshot_dir="screenshots", debug_dir="screenshots")
    except ImportError:
        logger.warning("清理工具模块未找到，跳过自动清理功能")
    
    # 尝试自动发送本机 IP 到主机服务器
    # 启动后台线程定时发送 IP 和 PC 名称
    threading.Thread(target=periodic_send_ip, daemon=True).start()
    
    logger.info("Starting Flask server. Switch to the target application if needed.")

    # 打印所有本机 IP 地址
    ips = get_ip_addresses()
    logger.info("Server is available on the following IP addresses:")
    for ip in ips:
        logger.info(f" - {ip}:5000")
    
    # 启用多线程模式，支持并发处理心跳和指令请求
    app.run(host="0.0.0.0", port=5000, threaded=True)
