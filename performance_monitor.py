"""
性能监控模块
用于监控系统性能、请求统计、资源使用等
"""
import time
import threading
import os
from collections import defaultdict, deque
from datetime import datetime

# 尝试导入psutil，如果不存在则使用简化版本
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self):
        self.request_count = defaultdict(int)  # 请求计数
        self.response_times = defaultdict(list)  # 响应时间记录
        self.error_count = defaultdict(int)  # 错误计数
        self.last_reset_time = time.time()
        self.lock = threading.Lock()
        
        # 保留最近1000个响应时间记录
        self.max_records = 1000
        
    def record_request(self, endpoint, response_time=None, is_error=False):
        """记录请求"""
        with self.lock:
            self.request_count[endpoint] += 1
            if is_error:
                self.error_count[endpoint] += 1
            if response_time is not None:
                if endpoint not in self.response_times:
                    self.response_times[endpoint] = deque(maxlen=self.max_records)
                self.response_times[endpoint].append(response_time)
    
    def get_stats(self):
        """获取统计信息"""
        with self.lock:
            stats = {
                'request_count': dict(self.request_count),
                'error_count': dict(self.error_count),
                'avg_response_time': {},
                'min_response_time': {},
                'max_response_time': {},
                'uptime_seconds': time.time() - self.last_reset_time,
                'uptime_formatted': self._format_uptime(time.time() - self.last_reset_time)
            }
            
            for endpoint, times in self.response_times.items():
                if times:
                    stats['avg_response_time'][endpoint] = round(sum(times) / len(times), 3)
                    stats['min_response_time'][endpoint] = round(min(times), 3)
                    stats['max_response_time'][endpoint] = round(max(times), 3)
            
            return stats
    
    def _format_uptime(self, seconds):
        """格式化运行时间"""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{days}天 {hours}小时 {minutes}分钟 {secs}秒"
    
    def reset_stats(self):
        """重置统计"""
        with self.lock:
            self.request_count.clear()
            self.error_count.clear()
            self.response_times.clear()
            self.last_reset_time = time.time()
    
    def get_system_info(self):
        """获取系统信息"""
        if not PSUTIL_AVAILABLE:
            return {'error': 'psutil not available', 'note': 'Install psutil for system monitoring'}
        
        try:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            
            return {
                'cpu_percent': round(process.cpu_percent(interval=0.1), 2),
                'memory_mb': round(memory_info.rss / (1024 * 1024), 2),
                'memory_percent': round(process.memory_percent(), 2),
                'thread_count': threading.active_count(),
                'disk_usage': {
                    'total_gb': round(psutil.disk_usage('.').total / (1024**3), 2),
                    'used_gb': round(psutil.disk_usage('.').used / (1024**3), 2),
                    'free_gb': round(psutil.disk_usage('.').free / (1024**3), 2),
                    'percent': round(psutil.disk_usage('.').percent, 2)
                }
            }
        except Exception as e:
            return {'error': str(e)}

# 全局监控实例
monitor = PerformanceMonitor()

