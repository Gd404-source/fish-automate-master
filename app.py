import os
import json
import socket
import asyncio
import aiohttp
import requests
from aiohttp import ClientTimeout
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
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

IPS_FILE = "ips.json"
ip_list = []

def load_ips_from_file():
    global ip_list
    if os.path.exists(IPS_FILE):
        with open(IPS_FILE, "r", encoding="utf-8") as f:
            ip_list = json.load(f)
    else:
        ip_list = []

def save_ips_to_file():
    with open(IPS_FILE, "w", encoding="utf-8") as f:
        json.dump(ip_list, f, ensure_ascii=False, indent=2)

load_ips_from_file()

@app.route('/')
def index():
    return send_from_directory(os.path.dirname(__file__), 'index.html')

@app.route('/api/get_json_ips', methods=['GET'])
def get_json_ips():
    return jsonify({"status": "success", "ips": ip_list})

@app.route('/api/ips', methods=['GET'])
def get_ips():
    return jsonify(ip_list)

@app.route('/api/ips', methods=['POST'])
def add_ip():
    data = request.get_json() or {}
    new_ip = data.get('ip')
    pc_name = data.get('pc_name')
    global ip_list

    # 验证IP格式
    if not new_ip:
        return jsonify({"status": "error", "message": "IP address is required"}), 400
    
    # 简单的IP格式验证
    try:
        parts = new_ip.split('.')
        if len(parts) != 4 or not all(0 <= int(p) <= 255 for p in parts):
            return jsonify({"status": "error", "message": "Invalid IP format"}), 400
    except (ValueError, AttributeError):
        return jsonify({"status": "error", "message": "Invalid IP format"}), 400

    # 如果已有相同的 pc_name，就先把旧记录删掉
    ip_list = [e for e in ip_list if e.get('pc_name') != pc_name]

    # 新增 IP
    if new_ip:
        ip_list.append({'ip': new_ip, 'pc_name': pc_name})
        save_ips_to_file()

    return jsonify({"status": "success", "ips": ip_list})

@app.route('/api/ips/<ip>', methods=['DELETE'])
def delete_ip(ip):
    global ip_list
    ip_list = [e for e in ip_list if e['ip'] != ip]
    save_ips_to_file()
    return jsonify({"status": "success", "ips": ip_list})

def send_post_request(ip, key='f7'):
    try:
        resp = requests.post(f'http://{ip}:5000/run', json={"key": key}, timeout=1)
        return {"ip": ip, "status": "success", "response": resp.text}
    except requests.exceptions.Timeout:
        return {"ip": ip, "status": "error", "message": "Request timed out"}
    except requests.exceptions.ConnectionError as e:
        return {"ip": ip, "status": "error", "message": f"Connection error: {e}"}
    except Exception as e:
        return {"ip": ip, "status": "error", "message": str(e)}

@app.route('/api/send/<ip>', methods=['POST'])
def send_request(ip):
    key = (request.get_json() or {}).get("key", "f7")
    result = send_post_request(ip, key)
    return jsonify(result), (200 if result["status"]=="success" else 500)

# 异步并发方案
async def _send_one(session, semaphore, ip, key):
    async with semaphore:
        try:
            async with session.post(f'http://{ip}:5000/run', json={"key": key}, timeout=5) as resp:
                text = await resp.text()
                return {"ip": ip, "status": "success", "response": text}
        except asyncio.TimeoutError:
            return {"ip": ip, "status": "error", "message": "Request timed out"}
        except aiohttp.ClientConnectionError as e:
            return {"ip": ip, "status": "error", "message": f"Connection error: {e}"}
        except Exception as e:
            return {"ip": ip, "status": "error", "message": str(e)}

async def _send_all(ip_snapshot, key):
    # 动态并发数
    concurrency = max(1, min(len(ip_snapshot), 200))
    semaphore = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=concurrency)
    timeout   = aiohttp.ClientTimeout(total=None)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        tasks = [_send_one(session, semaphore, entry['ip'], key) for entry in ip_snapshot]
        return await asyncio.gather(*tasks)

@app.route('/api/send_all', methods=['POST'])
def send_request_all():
    data = request.get_json() or {}
    key = data.get("key", "f7")
    snapshot = list(ip_list)
    results = asyncio.run(_send_all(snapshot, key))
    return jsonify(results)

@app.route('/api/test/<ip>', methods=['GET'])
def test_request(ip):
    try:
        resp = requests.get(f'http://{ip}:5000/test', timeout=1)
        return jsonify({"ip": ip, "status": "success", "response": resp.text}), 200
    except Exception as e:
        return jsonify({"ip": ip, "status": "error", "message": str(e)}), 500

@app.route('/api/test_all', methods=['GET'])
def test_request_all():
    results = [ test_request(e['ip'])[0].get_json() for e in ip_list ]
    return jsonify(results)

@app.route('/api/server_info', methods=['GET'])
def server_info():
    host_ips = socket.gethostbyname_ex(socket.gethostname())[2]
    return jsonify({"server_ips": host_ips, "is_correct": "192.168.0.254" in host_ips})

@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查端点，返回系统状态和性能数据"""
    health_status = {
        'status': 'healthy',
        'timestamp': time.time(),
        'server_name': socket.gethostname(),
        'server_ips': socket.gethostbyname_ex(socket.gethostname())[2],
        'client_count': len(ip_list)
    }
    if PERFORMANCE_MONITORING:
        health_status['performance'] = monitor.get_stats()
        health_status['system'] = monitor.get_system_info()
    return jsonify(health_status), 200

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """获取性能统计数据"""
    if not PERFORMANCE_MONITORING:
        return jsonify({"error": "Performance monitoring is not enabled."}), 503
    return jsonify(monitor.get_stats()), 200

@app.route('/api/stats/reset', methods=['POST'])
def reset_stats():
    """重置性能统计数据"""
    if not PERFORMANCE_MONITORING:
        return jsonify({"error": "Performance monitoring is not enabled."}), 503
    monitor.reset_stats()
    return jsonify({"status": "success", "message": "Performance stats reset."}), 200

if __name__ == '__main__':
    # 启动自动清理任务
    try:
        from cleanup_utils import setup_periodic_cleanup
        setup_periodic_cleanup(log_dir="logs", screenshot_dir="screenshots", debug_dir="screenshots")
    except ImportError:
        print("警告: 清理工具模块未找到，跳过自动清理功能")
    
    # 启用多线程模式，支持高并发处理
    # debug=False 提高生产环境性能
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)
