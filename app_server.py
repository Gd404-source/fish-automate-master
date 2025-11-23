import os
import json
import socket
import requests
import asyncio
import aiohttp
from aiohttp import ClientTimeout
from flask import Flask, jsonify, request, send_from_directory
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask_cors import CORS
import websocket
import threading
import time

app = Flask(__name__)
CORS(app)

# 性能监控
try:
    from performance_monitor import monitor
    PERFORMANCE_MONITORING = True
except ImportError:
    PERFORMANCE_MONITORING = False
    monitor = None

@app.before_request
def before_request():
    """请求前处理：记录开始时间"""
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

# 文件存储路径
IPS_FILE = "ips.json"

# 用于存储目标 IP 地址及对应的 PC 名称的列表
# 每个列表元素为一个字典，例如: {"ip": "192.168.0.123", "pc_name": "PC_A"}
ip_list = []

def save_ips_to_file():
    """保存 ip_list 到文件中"""
    with open(IPS_FILE, "w", encoding="utf-8") as f:
        json.dump(ip_list, f, ensure_ascii=False, indent=2)

def load_ips_from_file():
    """从文件加载 ip_list，如果文件不存在，则初始化为空列表"""
    global ip_list
    if os.path.exists(IPS_FILE):
        with open(IPS_FILE, "r", encoding="utf-8") as f:
            ip_list = json.load(f)
    else:
        ip_list = []

# 启动时加载 IP 列表
load_ips_from_file()

@app.route('/')
def index():
    """
    提供前端页面
    """
    return send_from_directory(os.path.dirname(__file__), 'index.html')

@app.route('/api/get_json_ips', methods=['GET'])
def get_ips_list():
    """
    获取IPs List
    """
    return jsonify({"status": "success", "ips": ip_list})

@app.route('/api/ips', methods=['GET'])
def get_ips():
    """
    获取当前所有 IP 地址及对应的 PC 名称
    """
    return jsonify(ip_list)

@app.route('/api/ips', methods=['POST'])
def add_ip():
    """
    添加 IP 地址和 PC 名称
    """
    data = request.get_json() or {}
    new_ip = data.get('ip')
    pc_name = data.get('pc_name', 'Unknown')
    
    # 验证IP格式
    if not new_ip:
        return jsonify({"status": "error", "message": "IP address is required"}), 400
    
    # 简单的IP格式验证
    try:
        parts = new_ip.split('.')
        if len(parts) != 4 or not all(0 <= int(p) <= 255 for p in parts):
            return jsonify({"status": "error", "message": "Invalid IP format"}), 400
    except:
        return jsonify({"status": "error", "message": "Invalid IP format"}), 400
    
    # 如果 ip_list 中不存在该 IP，则添加新的记录
    if not any(entry['ip'] == new_ip for entry in ip_list):
        ip_list.append({'ip': new_ip, 'pc_name': pc_name})
        save_ips_to_file()
    
    return jsonify({"status": "success", "ips": ip_list})

@app.route('/api/ips/<ip>', methods=['DELETE'])
def delete_ip(ip):
    """
    删除指定 IP 地址及对应的信息
    """
    global ip_list
    ip_list = [entry for entry in ip_list if entry['ip'] != ip]
    save_ips_to_file()
    return jsonify({"status": "success", "ips": ip_list})

def send_post_request(ip, key='f7'):
    """
    发送 POST 请求到指定 IP 的 /run 接口，携带按键参数，带超时和错误处理
    （保留同步版本用于单个发送）
    """
    try:
        response = requests.post(f'http://{ip}:5000/run', json={"key": key}, timeout=3)
        return {"ip": ip, "status": "success", "response": response.text}
    except requests.exceptions.Timeout:
        return {"ip": ip, "status": "error", "message": "Request timed out"}
    except requests.exceptions.ConnectionError:
        return {"ip": ip, "status": "error", "message": "Connection error"}
    except requests.exceptions.RequestException as e:
        return {"ip": ip, "status": "error", "message": f"Unexpected error: {str(e)}"}

# ==================== 异步高性能发送实现 ====================

async def _send_one_with_retry(session, semaphore, ip, key, max_retries=3):
    """
    带重试机制的异步发送单个指令
    参数:
        session: aiohttp会话
        semaphore: 并发控制信号量
        ip: 目标IP
        key: 按键
        max_retries: 最大重试次数
    """
    for attempt in range(max_retries):
        try:
            async with semaphore:
                async with session.post(
                    f'http://{ip}:5000/run',
                    json={"key": key},
                    timeout=ClientTimeout(total=5, connect=2)
                ) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        try:
                            data = json.loads(text)
                            return {
                                "ip": ip,
                                "status": "success",
                                "response": data,
                                "attempt": attempt + 1,
                                "timestamp": time.time()
                            }
                        except:
                            return {
                                "ip": ip,
                                "status": "success",
                                "response": text,
                                "attempt": attempt + 1,
                                "timestamp": time.time()
                            }
                    else:
                        if attempt < max_retries - 1:
                            await asyncio.sleep(0.1 * (attempt + 1))
                            continue
                        return {
                            "ip": ip,
                            "status": "error",
                            "message": f"HTTP {resp.status}",
                            "attempt": attempt + 1
                        }
        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                await asyncio.sleep(0.1 * (attempt + 1))  # 递增延迟
                continue
            return {
                "ip": ip,
                "status": "error",
                "message": "Request timed out after retries",
                "attempt": attempt + 1
            }
        except aiohttp.ClientConnectionError as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(0.1 * (attempt + 1))
                continue
            return {
                "ip": ip,
                "status": "error",
                "message": f"Connection error: {str(e)}",
                "attempt": attempt + 1
            }
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(0.1 * (attempt + 1))
                continue
            return {
                "ip": ip,
                "status": "error",
                "message": str(e),
                "attempt": attempt + 1
            }
    
    return {
        "ip": ip,
        "status": "error",
        "message": "Max retries exceeded"
    }

async def _send_all_async(ip_snapshot, key):
    """
    异步批量发送指令到所有客户端
    支持大量客户端，动态调整并发数，使用连接池提高效率
    """
    if not ip_snapshot:
        return []
    
    # 动态并发数：根据客户端数量调整，最多500个并发
    # 小规模（<50）：使用实际数量
    # 中等规模（50-200）：使用200
    # 大规模（>200）：使用500
    client_count = len(ip_snapshot)
    if client_count < 50:
        concurrency = client_count
    elif client_count < 200:
        concurrency = 200
    else:
        concurrency = 500
    
    semaphore = asyncio.Semaphore(concurrency)
    
    # 使用连接池，提高效率
    connector = aiohttp.TCPConnector(
        limit=concurrency,
        limit_per_host=20,  # 每个主机最多20个连接
        ttl_dns_cache=300,   # DNS缓存5分钟
        force_close=False,  # 保持连接复用
        enable_cleanup_closed=True
    )
    
    timeout = ClientTimeout(total=5, connect=2)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        tasks = [_send_one_with_retry(session, semaphore, entry['ip'], key) for entry in ip_snapshot]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        processed_results = []
        for result in results:
            if isinstance(result, Exception):
                processed_results.append({
                    "ip": "unknown",
                    "status": "error",
                    "message": str(result)
                })
            else:
                processed_results.append(result)
        
        return processed_results

@app.route('/api/send/<ip>', methods=['POST'])
def send_request(ip):
    """
    发送 POST 请求到指定 IP 的 /run 接口，同时传递用户选择的按键
    """
    data = request.get_json() or {}
    key = data.get("key", "f7")
    result = send_post_request(ip, key)
    if result["status"] == "success":
        return jsonify(result), 200
    else:
        return jsonify(result), 500

@app.route('/api/send_all', methods=['POST'])
def send_request_all():
    """
    向所有 IP 地址发送 POST 请求到 /run 接口
    使用异步高性能实现，支持大量客户端快速响应
    """
    data = request.get_json() or {}
    key = data.get("key", "f7")
    snapshot = list(ip_list)  # 快照，避免并发修改
    
    if not snapshot:
        return jsonify([]), 200
    
    start_time = time.time()
    
    # 使用异步执行
    try:
        results = asyncio.run(_send_all_async(snapshot, key))
        elapsed_time = time.time() - start_time
        
        # 统计结果
        success_count = sum(1 for r in results if r.get("status") == "success")
        error_count = len(results) - success_count
        
        print(f"批量发送完成: {len(results)}个客户端, 成功: {success_count}, 失败: {error_count}, 耗时: {elapsed_time:.2f}秒")
        
        return jsonify({
            "results": results,
            "summary": {
                "total": len(results),
                "success": success_count,
                "error": error_count,
                "elapsed_time": round(elapsed_time, 2)
            }
        })
    except Exception as e:
        print(f"批量发送出错: {str(e)}")
        return jsonify({
            "error": str(e),
            "results": []
        }), 500

# ----------------------- 新增测试连接功能 -----------------------

def send_test_request(ip):
    """
    发送 GET 请求到指定 IP 的 /test 接口，用于测试连接
    """
    try:
        response = requests.get(f'http://{ip}:5000/test', timeout=1)
        return {"ip": ip, "status": "success", "response": response.text}
    except requests.exceptions.Timeout:
        return {"ip": ip, "status": "error", "message": "Request timed out"}
    except requests.exceptions.ConnectionError:
        return {"ip": ip, "status": "error", "message": "Connection error"}
    except requests.exceptions.RequestException as e:
        return {"ip": ip, "status": "error", "message": f"Unexpected error: {str(e)}"}

@app.route('/api/test/<ip>', methods=['GET'])
def test_request(ip):
    """
    测试指定 IP 的连接
    """
    result = send_test_request(ip)
    if result["status"] == "success":
        return jsonify(result), 200
    else:
        return jsonify(result), 500

@app.route('/api/test_all', methods=['GET'])
def test_request_all():
    """
    测试所有 IP 地址的连接（异步版本）
    """
    async def _test_all_async(ip_snapshot):
        """异步测试所有连接"""
        if not ip_snapshot:
            return []
        
        concurrency = min(len(ip_snapshot), 200)
        semaphore = asyncio.Semaphore(concurrency)
        connector = aiohttp.TCPConnector(limit=concurrency, force_close=False)
        timeout = ClientTimeout(total=3, connect=1)
        
        async def test_one(session, sem, entry_ip):
            async with sem:
                try:
                    async with session.get(f'http://{entry_ip}:5000/test', timeout=timeout) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            return {"ip": entry_ip, "status": "success", "response": text}
                        else:
                            return {"ip": entry_ip, "status": "error", "message": f"HTTP {resp.status}"}
                except asyncio.TimeoutError:
                    return {"ip": entry_ip, "status": "error", "message": "Request timed out"}
                except Exception as e:
                    return {"ip": entry_ip, "status": "error", "message": str(e)}
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            tasks = [test_one(session, semaphore, entry['ip']) for entry in ip_snapshot]
            return await asyncio.gather(*tasks, return_exceptions=True)
    
    snapshot = list(ip_list)
    try:
        results = asyncio.run(_test_all_async(snapshot))
        processed_results = []
        for result in results:
            if isinstance(result, Exception):
                processed_results.append({"ip": "unknown", "status": "error", "message": str(result)})
            else:
                processed_results.append(result)
        return jsonify(processed_results)
    except Exception as e:
        return jsonify([{"ip": "error", "status": "error", "message": str(e)}]), 500

# ==================== 心跳检测功能 ====================

# 存储客户端心跳信息
client_heartbeats = {}

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    """
    接收客户端心跳，用于检测客户端在线状态
    优化：快速处理，减少延迟
    """
    data = request.get_json() or {}
    client_ip = data.get('ip')
    pc_name = data.get('pc_name', 'Unknown')
    
    if not client_ip:
        return jsonify({"status": "error", "message": "No IP provided"}), 400
    
    # 快速更新心跳信息
    current_time = time.time()
    client_heartbeats[client_ip] = {
        'ip': client_ip,
        'pc_name': pc_name,
        'last_heartbeat': current_time,
        'status': 'online'
    }
    
    return jsonify({"status": "success"}), 200

@app.route('/api/client_status', methods=['GET'])
def client_status():
    """
    获取所有客户端在线状态
    优化：更精确的超时检测和状态更新
    """
    current_time = time.time()
    HEARTBEAT_TIMEOUT = 30  # 30秒超时
    status_list = []
    
    # 检查心跳超时（30秒未收到心跳视为离线）
    for ip, info in client_heartbeats.items():
        time_since_heartbeat = current_time - info['last_heartbeat']
        if time_since_heartbeat > HEARTBEAT_TIMEOUT:
            info['status'] = 'offline'
        else:
            info['status'] = 'online'
        
        # 添加额外信息
        status_info = info.copy()
        status_info['time_since_heartbeat'] = round(time_since_heartbeat, 2)
        status_list.append(status_info)
    
    # 按状态排序：在线在前
    status_list.sort(key=lambda x: (x['status'] != 'online', x.get('time_since_heartbeat', 0)))
    
    return jsonify(status_list)

# ----------------------- 结束新增 -----------------------

def get_host_ips():
    host_name = socket.gethostname()
    try:
        host_ips = socket.gethostbyname_ex(host_name)[2]
    except socket.error:
        host_ips = ['127.0.0.1']
    return host_ips

@app.route('/api/server_info', methods=['GET'])
def server_info():
    """
    提供服务器的 IP 信息，并检查是否为预期的 192.168.0.254
    """
    host_ips = get_host_ips()
    is_correct = "192.168.0.254" in host_ips
    return jsonify({"server_ips": host_ips, "is_correct": is_correct})

@app.route('/api/health', methods=['GET'])
def health_check():
    """
    健康检查端点，返回系统状态和性能信息
    """
    health_status = {
        'status': 'healthy',
        'timestamp': time.time(),
        'client_count': len(ip_list),
        'online_clients': len([h for h in client_heartbeats.values() if h.get('status') == 'online'])
    }
    
    if PERFORMANCE_MONITORING:
        health_status['performance'] = monitor.get_stats()
        health_status['system'] = monitor.get_system_info()
    
    return jsonify(health_status), 200

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """
    获取性能统计信息
    """
    if not PERFORMANCE_MONITORING:
        return jsonify({'error': 'Performance monitoring not available'}), 503
    
    return jsonify(monitor.get_stats()), 200

@app.route('/api/stats/reset', methods=['POST'])
def reset_stats():
    """
    重置性能统计
    """
    if not PERFORMANCE_MONITORING:
        return jsonify({'error': 'Performance monitoring not available'}), 503
    
    monitor.reset_stats()
    return jsonify({'status': 'success', 'message': 'Statistics reset'}), 200


# ------------------------ WebSocket 连接到云端（可选功能） ------------------------
# 注意：这是可选功能，用于从云端接收远程指令
# 即使WebSocket断开或很慢，也不影响内网通信功能
# 内网通信（客户端注册、发送指令）完全独立运行，不受互联网速度影响

# 是否启用WebSocket云端连接（设置为False可完全禁用，只使用内网通信）
ENABLE_CLOUD_WEBSOCKET = False  # 默认禁用，如需启用请设置为True

CLOUD_WS_URL = "wss://mserver-production-14ce.up.railway.app/ws"  # 替换成你的云端 WebSocket 地址

def on_message(ws, message):
    print("收到云端推送的指令：", message)
    try:
        data = json.loads(message)
        # 发送POST请求到本地接口（使用内网地址127.0.0.1，不经过互联网）
        resp = requests.post('http://127.0.0.1:5000/api/send_all', json=data, timeout=5)
        print("本地接口返回：", resp.status_code, resp.text)
    except Exception as e:
        print("处理指令时出错：", e)

def on_error(ws, error):
    print("WebSocket连接出错（不影响内网通信）:", error)

def on_close(ws, close_status_code, close_msg):
    if ENABLE_CLOUD_WEBSOCKET:
        print("WebSocket连接关闭,5秒后重连（不影响内网通信）...")
        threading.Timer(5, connect_to_cloud).start()

def on_open(ws):
    print("WebSocket云端连接成功（内网通信始终可用）")

def connect_to_cloud():
    """连接到云端WebSocket（可选功能，不影响内网通信）"""
    if not ENABLE_CLOUD_WEBSOCKET:
        return
    try:
        ws = websocket.WebSocketApp(
            CLOUD_WS_URL,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )
        ws.run_forever()
    except Exception as e:
        print(f"WebSocket连接失败（不影响内网通信）: {e}")
        if ENABLE_CLOUD_WEBSOCKET:
            threading.Timer(5, connect_to_cloud).start()

# ------------------------ WebSocket结束 ------------------------


if __name__ == '__main__':
    # 导入清理工具（主服务器也需要清理功能）
    try:
        from cleanup_utils import start_cleanup_thread
        # 启动自动清理任务（每6小时清理一次）
        start_cleanup_thread(interval_hours=6)
    except ImportError:
        print("警告: 清理工具模块未找到，跳过自动清理功能")
    
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' and ENABLE_CLOUD_WEBSOCKET:
        # 只有在真正的主进程里且启用WebSocket时才启动云端连接
        # 注意：内网通信功能不受此影响，始终可用
        threading.Thread(target=connect_to_cloud, daemon=True).start()
        print("已启用WebSocket云端连接（可选功能，不影响内网通信）")
    else:
        print("WebSocket云端连接已禁用，仅使用内网通信（更快、更稳定）")
    
    # 启用多线程模式，支持高并发处理
    # debug=False 提高生产环境性能
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)

