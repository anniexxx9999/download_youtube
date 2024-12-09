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

def get_video_info(url: str) -> dict:
    """获取视频信息"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            for f in info.get('formats', []):
                if f.get('vcodec', 'none') != 'none':
                    formats.append({
                        'format_id': str(f.get('format_id', '')),
                        'ext': str(f.get('ext', '')),
                        'resolution': str(f.get('resolution', 'unknown')),
                        'filesize': int(f.get('filesize', 0))
                    })
            
            return {
                'title': str(info.get('title', 'Unknown Title')),
                'duration': int(info.get('duration', 0)),
                'uploader': str(info.get('uploader', 'Unknown')),
                'description': str(info.get('description', ''))[:200],
                'formats': sorted(formats, key=lambda x: x.get('filesize', 0), reverse=True)
            }
    except Exception as e:
        logger.error(f"Error getting video info: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def home(request: Request):
    """主页"""
    return templates.TemplateResponse("index.html", {
        "request": request,
        "videos": [],
        "is_vercel": bool(os.environ.get("VERCEL"))
    })

@app.post("/download")
async def start_download(request: Request):
    """处理下载请求"""
    try:
        # 添加请求超时处理
        try:
            data = await asyncio.wait_for(request.json(), timeout=5.0)
        except asyncio.TimeoutError:
            return JSONResponse(
                status_code=408,
                content={"error": "请求超时，请重试"}
            )

        url = data.get('url')
        if not url:
            return JSONResponse(
                status_code=400,
                content={"error": "请输入视频链接"}
            )

        # 获取视频信息
        if data.get('get_info'):
            try:
                info = get_video_info(url)
                return JSONResponse(
                    status_code=200,
                    content={"info": info}
                )
            except Exception as e:
                logger.error(f"Error getting video info: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"获取视频信息失败: {str(e)}"}
                )

        # Vercel 环境提示
        if os.environ.get("VERCEL"):
            demo_id = f"demo-{str(uuid.uuid4())}"
            return JSONResponse(
                status_code=200,
                content={
                    "error": "Vercel 环境不支持视频下载，请在本地运行此应用。",
                    "type": "vercel_limitation",
                    "video_id": demo_id
                }
            )

        # 本地环境处理下载
        try:
            video_id = str(uuid.uuid4())
            format_id = data.get('format_id', 'best')
            
            # 获取视频信息
            video_info = get_video_info(url)
            
            # 存储下载信息
            downloads[video_id] = {
                'status': 'downloading',
                'progress': 0,
                'info': video_info,
                'start_time': datetime.now().isoformat()
            }
            
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

    except json.JSONDecodeError:
        return JSONResponse(
            status_code=400,
            content={"error": "无效的请求数据格式"}
        )
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"服务器错误: {str(e)}"}
        )

@app.get("/progress/{video_id}")
async def get_progress(video_id: str):
    """获取下载进度"""
    if video_id.startswith('demo-'):
        return JSONResponse(content={
            "status": "demo",
            "progress": 0,
            "message": "演示模式"
        })
    
    if video_id not in downloads:
        raise HTTPException(status_code=404, detail="Download not found")
    
    return JSONResponse(content=downloads[video_id])