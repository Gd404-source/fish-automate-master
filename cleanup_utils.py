"""
自动清理工具模块
用于定期清理日志、截图、调试文件等，防止磁盘空间被占满
"""
import os
import time
import shutil
import threading
from datetime import datetime, timedelta

def get_folder_size(folder_path):
    """计算文件夹大小（MB）"""
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.exists(filepath):
                    total_size += os.path.getsize(filepath)
    except:
        pass
    return total_size / (1024 * 1024)  # 转换为MB

def cleanup_old_files(folder_path, max_age_days=3, max_size_mb=1024):
    """
    清理旧文件
    参数:
        folder_path: 要清理的文件夹路径
        max_age_days: 文件最大保留天数
        max_size_mb: 文件夹最大大小（MB），超过则清理最旧的文件
    """
    if not os.path.exists(folder_path):
        return 0, 0
    
    deleted_count = 0
    freed_space_mb = 0
    current_time = time.time()
    max_age_seconds = max_age_days * 24 * 3600
    
    # 收集所有文件及其修改时间
    files_info = []
    for dirpath, dirnames, filenames in os.walk(folder_path):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            try:
                if os.path.exists(filepath):
                    mtime = os.path.getmtime(filepath)
                    size = os.path.getsize(filepath)
                    files_info.append((filepath, mtime, size))
            except:
                continue
    
    # 按修改时间排序（最旧的在前）
    files_info.sort(key=lambda x: x[1])
    
    # 先删除超过最大年龄的文件
    for filepath, mtime, size in files_info:
        if current_time - mtime > max_age_seconds:
            try:
                os.remove(filepath)
                deleted_count += 1
                freed_space_mb += size / (1024 * 1024)
            except:
                continue
    
    # 如果文件夹仍然太大，删除最旧的文件直到满足大小要求
    current_size_mb = get_folder_size(folder_path)
    if current_size_mb > max_size_mb:
        remaining_files = [(f, m, s) for f, m, s in files_info if os.path.exists(f)]
        remaining_files.sort(key=lambda x: x[1])  # 按时间排序
        
        for filepath, mtime, size in remaining_files:
            if current_size_mb <= max_size_mb:
                break
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    deleted_count += 1
                    freed_space_mb += size / (1024 * 1024)
                    current_size_mb -= size / (1024 * 1024)
            except:
                continue
    
    # 清理空目录
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path, topdown=False):
            if not dirnames and not filenames and dirpath != folder_path:
                try:
                    os.rmdir(dirpath)
                except:
                    pass
    except:
        pass
    
    return deleted_count, freed_space_mb

def cleanup_screenshots(max_age_days=3, max_size_mb=1024):
    """清理截图文件夹"""
    screenshots_dir = "screenshots"
    if not os.path.exists(screenshots_dir):
        return 0, 0
    
    deleted_count, freed_space_mb = cleanup_old_files(screenshots_dir, max_age_days, max_size_mb)
    
    if deleted_count > 0:
        print(f"清理截图: 删除 {deleted_count} 个文件，释放 {freed_space_mb:.2f} MB 空间")
    
    return deleted_count, freed_space_mb

def cleanup_debug_files(max_age_days=1, max_size_mb=500):
    """清理调试文件"""
    debug_dirs = []
    
    # 查找所有debug目录
    screenshots_dir = "screenshots"
    if os.path.exists(screenshots_dir):
        for item in os.listdir(screenshots_dir):
            if item.startswith("debug_"):
                debug_dirs.append(os.path.join(screenshots_dir, item))
    
    # 查找独立的debug目录
    if os.path.exists("debug"):
        debug_dirs.append("debug")
    
    total_deleted = 0
    total_freed = 0
    
    for debug_dir in debug_dirs:
        if os.path.exists(debug_dir):
            deleted_count, freed_space_mb = cleanup_old_files(debug_dir, max_age_days, max_size_mb)
            total_deleted += deleted_count
            total_freed += freed_space_mb
    
    if total_deleted > 0:
        print(f"清理调试文件: 删除 {total_deleted} 个文件，释放 {total_freed:.2f} MB 空间")
    
    return total_deleted, total_freed

def periodic_cleanup(interval_hours=6):
    """
    定期清理任务
    参数:
        interval_hours: 清理间隔（小时）
    """
    while True:
        try:
            # 清理截图（保留3天，最大1GB）
            cleanup_screenshots(max_age_days=3, max_size_mb=1024)
            
            # 清理调试文件（保留1天，最大500MB）
            cleanup_debug_files(max_age_days=1, max_size_mb=500)
            
        except Exception as e:
            print(f"清理任务出错: {e}")
        
        # 等待指定时间后再次清理
        time.sleep(interval_hours * 3600)

def start_cleanup_thread(interval_hours=6):
    """启动后台清理线程"""
    cleanup_thread = threading.Thread(target=periodic_cleanup, args=(interval_hours,), daemon=True)
    cleanup_thread.start()
    print(f"自动清理任务已启动，每 {interval_hours} 小时清理一次")

