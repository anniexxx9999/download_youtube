from fastapi import FastAPI, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse
import yt_dlp
import asyncio
import os
import json
from datetime import datetime
from pathlib import Path
import logging
import traceback
from typing import Optional
import shutil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/downloads", StaticFiles(directory="downloads"), name="downloads")

DOWNLOAD_DIR = "downloads"

# 存储下载任务信息
downloads = {}

def get_video_info(url):
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            },
            'nocheckcertificate': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            for f in info.get('formats', []):
                if f.get('vcodec', 'none') != 'none':
                    formats.append({
                        'format_id': f.get('format_id', ''),
                        'ext': f.get('ext', ''),
                        'quality': f.get('quality', 0),
                        'resolution': f.get('resolution', 'unknown'),
                        'filesize': f.get('filesize', 0),
                        'vcodec': f.get('vcodec', ''),
                        'acodec': f.get('acodec', ''),
                    })
            
            return {
                'title': info['title'],
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'description': info.get('description', ''),
                'thumbnail': info.get('thumbnail', ''),
                'formats': formats
            }
    except Exception as e:
        logger.error(f"Error getting video info: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

def clean_progress_string(progress_str):
    """清理进度字符串中的 ANSI 转义序列"""
    import re
    # 移除 ANSI 转义序列
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    cleaned = ansi_escape.sub('', progress_str)
    try:
        # 提取数字
        number = float(re.search(r'[\d.]+', cleaned).group())
        return number
    except (AttributeError, ValueError):
        return 0.0

async def download_video(url, video_id, format_id='best'):
    download_path = os.path.join(DOWNLOAD_DIR, f"{video_id}")
    os.makedirs(download_path, exist_ok=True)
    
    def progress_hook(d):
        try:
            if downloads[video_id]['status'] == 'paused':
                raise Exception("Download paused")
            if d['status'] == 'downloading':
                progress_str = d.get('_percent_str', '0%')
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
                speed = d.get('speed', 0)
                
                logger.info(f"Downloading progress: {progress_str}")
                downloads[video_id].update({
                    'progress': clean_progress_string(progress_str),
                    'downloaded': downloaded,
                    'total': total,
                    'speed': speed,
                    'eta': d.get('eta', 0)
                })
            elif d['status'] == 'finished':
                logger.info(f"Download finished: {d.get('filename', '')}")
                downloads[video_id].update({
                    'status': 'completed',
                    'file_path': d.get('filename', ''),
                    'downloaded': d.get('total_bytes', 0),
                    'total': d.get('total_bytes', 0),
                    'speed': 0,
                    'eta': 0,
                    'completed_time': datetime.now().isoformat()
                })
            elif d['status'] == 'error':
                logger.error(f"Download error: {str(d.get('error', 'Unknown error'))}")
                downloads[video_id]['status'] = 'error'
                downloads[video_id]['error'] = str(d.get('error', 'Unknown error'))
        except Exception as e:
            logger.error(f"Error in progress_hook: {str(e)}\n{traceback.format_exc()}")
            downloads[video_id]['status'] = 'error'
            downloads[video_id]['error'] = str(e)
    
    ydl_opts = {
        'format': format_id,
        'outtmpl': f'{download_path}/%(title)s.%(ext)s',
        'progress_hooks': [progress_hook],
        'verbose': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        },
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'no_warnings': False,
        'geo_bypass': True,
        'geo_bypass_country': 'US',
        'socket_timeout': 30,
        'legacy_server_connect': True,
        'no_color': True
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(f"Starting download for video {video_id} with format {format_id}")
            await asyncio.get_event_loop().run_in_executor(None, ydl.download, [url])
    except Exception as e:
        logger.error(f"Download failed: {str(e)}\n{traceback.format_exc()}")
        downloads[video_id]['status'] = 'error'
        downloads[video_id]['error'] = str(e)

@app.get("/")
async def home(request: Request):
    try:
        videos = []
        for video_id, info in downloads.items():
            if info['status'] == 'completed':
                # 处理文件路径，移除 downloads 目录前缀
                if 'file_path' in info:
                    file_path = info['file_path']
                    # 移除 downloads/video_id 前缀
                    relative_path = os.path.relpath(file_path, os.path.join(DOWNLOAD_DIR, video_id))
                    info['relative_path'] = relative_path
                    
                    # 获取文件大小
                    try:
                        file_size = os.path.getsize(file_path)
                        # 转换为 MB
                        info['file_size'] = f"{(file_size / 1024 / 1024):.1f} MB"
                    except Exception as e:
                        info['file_size'] = "未知"

                # 添加下载完成时间
                info['completed_time'] = info.get('completed_time', datetime.now().isoformat())
                videos.append({
                    'id': video_id,
                    'info': info
                })
        
        # 按完成时间倒序排序
        videos.sort(key=lambda x: x['info']['completed_time'], reverse=True)
        
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "videos": videos,
            "downloads": DOWNLOAD_DIR
        })
    except Exception as e:
        logger.error(f"Error in home route: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/download")
async def start_download(request: Request):
    try:
        data = await request.json()
        url = data['url']
        
        # 如果只是获取信息，直接返回视频信息
        if data.get('get_info', False):
            video_info = get_video_info(url)
            return {
                "info": video_info
            }
        
        # 否则开始下载
        format_id = data.get('format_id', 'best')
        video_id = datetime.now().strftime('%Y%m%d%H%M%S')
        
        video_info = get_video_info(url)
        
        downloads[video_id] = {
            'url': url,
            'info': video_info,
            'status': 'downloading',
            'progress': 0,
            'format_id': format_id,
            'start_time': datetime.now().isoformat()
        }
        
        asyncio.create_task(download_video(url, video_id, format_id))
        
        return {"video_id": video_id}
    except Exception as e:
        logger.error(f"Error in download route: {str(e)}\n{traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.get("/progress/{video_id}")
async def get_progress(video_id: str):
    try:
        if video_id in downloads:
            return downloads[video_id]
        return {"error": "Download not found"}
    except Exception as e:
        logger.error(f"Error in progress route: {str(e)}\n{traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {str(exc)}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"error": str(exc)}
    )

@app.post("/pause/{video_id}")
async def pause_download(video_id: str):
    try:
        if video_id in downloads:
            if downloads[video_id]['status'] == 'downloading':
                downloads[video_id]['status'] = 'paused'
                return {"status": "paused"}
            elif downloads[video_id]['status'] == 'paused':
                downloads[video_id]['status'] = 'downloading'
                return {"status": "resumed"}
        return {"error": "Download not found"}
    except Exception as e:
        logger.error(f"Error in pause route: {str(e)}\n{traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.delete("/download/{video_id}")
async def delete_download(video_id: str):
    try:
        if video_id in downloads:
            # 删除下载目录
            download_path = os.path.join(DOWNLOAD_DIR, f"{video_id}")
            if os.path.exists(download_path):
                shutil.rmtree(download_path)
            
            # 从下载列表中移除
            downloads.pop(video_id)
            return {"status": "deleted"}
        return {"error": "Download not found"}
    except Exception as e:
        logger.error(f"Error in delete route: {str(e)}\n{traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )