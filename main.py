from fastapi import FastAPI, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
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
import uuid

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="YouTube 视频下载器",
    description="一个简单的YouTube视频下载工具",
    version="1.0.0"
)

# 添加 CORS 支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加 Gzip 压缩
app.add_middleware(GZipMiddleware, minimum_size=1000)

templates = Jinja2Templates(directory="templates")

# 在 Vercel 环境中使用 /tmp 目录
DOWNLOAD_DIR = "/tmp/downloads" if os.environ.get("VERCEL") else "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# 如果不在 Vercel 环境中，才挂载静态文件目录
if not os.environ.get("VERCEL"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.mount("/downloads", StaticFiles(directory="downloads"), name="downloads")

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
                    format_info = {
                        'format_id': str(f.get('format_id', '')),
                        'ext': str(f.get('ext', '')),
                        'quality': int(f.get('quality', 0)),
                        'resolution': str(f.get('resolution', 'unknown')),
                        'filesize': int(f.get('filesize', 0)),
                        'vcodec': str(f.get('vcodec', '')),
                        'acodec': str(f.get('acodec', ''))
                    }
                    formats.append(format_info)
            
            # 确保所有值都是可序列化的
            result = {
                'title': str(info.get('title', 'Unknown Title')),
                'duration': int(info.get('duration', 0)),
                'uploader': str(info.get('uploader', 'Unknown')),
                'description': str(info.get('description', '')),
                'thumbnail': str(info.get('thumbnail', '')),
                'formats': sorted(formats, key=lambda x: x.get('filesize', 0), reverse=True)
            }
            return result
    except Exception as e:
        logger.error(f"Error getting video info: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/")
async def home(request: Request):
    try:
        videos = []
        for video_id, info in downloads.items():
            if info['status'] == 'completed':
                if 'file_path' in info:
                    file_path = info['file_path']
                    relative_path = os.path.relpath(file_path, os.path.join(DOWNLOAD_DIR, video_id))
                    info['relative_path'] = relative_path
                    
                    try:
                        file_size = os.path.getsize(file_path)
                        info['file_size'] = f"{(file_size / 1024 / 1024):.1f} MB"
                    except Exception as e:
                        logger.error(f"Error getting file size: {str(e)}")
                        info['file_size'] = "未知"

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
            "downloads": DOWNLOAD_DIR,
            "is_vercel": bool(os.environ.get("VERCEL"))
        })
    except Exception as e:
        logger.error(f"Error in home route: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    logger.error(f"Global error: {str(exc)}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": "error"}
    )

@app.post("/download")
async def start_download(request: Request):
    try:
        data = await request.json()
        url = data.get('url')
        if not url:
            return JSONResponse(
                status_code=400,
                content={"error": "URL is required"}
            )

        # 如果只是获取信息
        if data.get('get_info'):
            try:
                info = get_video_info(url)
                return JSONResponse(content={"info": info})
            except Exception as e:
                logger.error(f"Error getting video info: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"获取视频信息失败: {str(e)}"}
                )

        # 在 Vercel 环境中，返回提示信息
        if os.environ.get("VERCEL"):
            return JSONResponse(
                status_code=200,
                content={
                    "error": "Vercel 环境不支持直接下载功能。请在本地环境运行此应用以使用完整功能。",
                    "type": "vercel_limitation",
                    "video_id": "demo-id"
                }
            )

        # 开始下载
        video_id = str(uuid.uuid4())
        format_id = data.get('format_id', 'best')
        
        try:
            video_info = get_video_info(url)
            downloads[video_id] = {
                'status': 'downloading',
                'progress': 0,
                'downloaded': 0,
                'total': 0,
                'speed': 0,
                'eta': 0,
                'info': video_info
            }
            
            # 启动下载任务
            asyncio.create_task(download_video(url, video_id, format_id))
            
            return JSONResponse(
                status_code=200,
                content={"video_id": video_id}
            )
        except Exception as e:
            logger.error(f"Error starting download: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"开始下载失败: {str(e)}"}
            )
            
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON format"}
        )
    except Exception as e:
        logger.error(f"Error in start_download: {str(e)}\n{traceback.format_exc()}")
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