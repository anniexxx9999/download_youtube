from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import yt_dlp
import os
import json
from datetime import datetime
from pathlib import Path
import asyncio
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="YouTube 下载器")

# 配置模板
templates = Jinja2Templates(directory="templates")

# 创建必要的目录
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# 配置静态文件
app.mount("/downloads", StaticFiles(directory="downloads"), name="downloads")

# 存储下载信息的文件
DOWNLOADS_INFO = DOWNLOAD_DIR / "info.json"
if not DOWNLOADS_INFO.exists():
    with open(DOWNLOADS_INFO, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False)

def load_downloads():
    try:
        with open(DOWNLOADS_INFO, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载下载历史失败: {e}")
        return []

def save_downloads(downloads):
    try:
        with open(DOWNLOADS_INFO, "w", encoding="utf-8") as f:
            json.dump(downloads, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存下载历史失败: {e}")

class DownloadProgress:
    def __init__(self):
        self.current = 0
        self.total = 0
        self.speed = ""
        self.eta = ""

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            self.current = d.get('downloaded_bytes', 0)
            self.total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
            self.speed = d.get('speed', 0)
            self.eta = d.get('eta', 0)

@app.get("/")
async def home(request: Request):
    """主页面"""
    downloads = load_downloads()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "downloads": downloads}
    )

@app.post("/download")
async def download_video(url: str, background_tasks: BackgroundTasks):
    """开始下载视频"""
    try:
        # 验证URL
        if not url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail="无效的URL格式")

        # 配置下载选项
        progress = DownloadProgress()
        ydl_opts = {
            'format': 'best',  # 最佳质量
            'outtmpl': str(DOWNLOAD_DIR / '%(title)s.%(ext)s'),
            'progress_hooks': [progress.progress_hook],
            'quiet': True,
            'no_warnings': True,
        }

        # 获取视频信息
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"获取视频信息失败: {str(e)}")

        # 准备下载信息
        download_info = {
            "id": info.get("id", ""),
            "title": info.get("title", "未知标题"),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", "未知上传者"),
            "description": info.get("description", ""),
            "thumbnail": info.get("thumbnail", ""),
            "url": url,
            "timestamp": datetime.now().isoformat(),
            "status": "downloading",
            "progress": 0,
            "speed": "",
            "eta": "",
            "local_path": "",
            "error": ""
        }

        # 更新下载列表
        downloads = load_downloads()
        downloads.append(download_info)
        save_downloads(downloads)

        # 在后台开始下载
        background_tasks.add_task(
            download_task,
            url=url,
            ydl_opts=ydl_opts,
            download_info=download_info,
            progress=progress
        )

        return JSONResponse(
            status_code=202,
            content={"status": "started", "info": download_info}
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"下载请求处理失败: {e}")
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")

async def download_task(url: str, ydl_opts: dict, download_info: dict, progress: DownloadProgress):
    """后台下载任务"""
    try:
        # 开始下载
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # 更新下载状态
        downloads = load_downloads()
        for d in downloads:
            if d["url"] == url:
                d["status"] = "completed"
                # 查找下载的文件
                for file in DOWNLOAD_DIR.glob("*"):
                    if download_info["title"] in file.name:
                        d["local_path"] = str(file.relative_to(DOWNLOAD_DIR))
                        d["file_size"] = file.stat().st_size
                        break
                break
        save_downloads(downloads)

    except Exception as e:
        logger.error(f"下载任务失败: {e}")
        # 更新错误状态
        downloads = load_downloads()
        for d in downloads:
            if d["url"] == url:
                d["status"] = "error"
                d["error"] = str(e)
                break
        save_downloads(downloads)

@app.get("/status")
async def get_status():
    """获取所有下载状态"""
    try:
        downloads = load_downloads()
        return JSONResponse(content=downloads)
    except Exception as e:
        logger.error(f"获取状态失败: {e}")
        raise HTTPException(status_code=500, detail="获取状态失败")

@app.delete("/downloads/{video_id}")
async def delete_download(video_id: str):
    """删除下载记录和文件"""
    try:
        downloads = load_downloads()
        for download in downloads:
            if download.get("id") == video_id:
                # 删除文件
                if download.get("local_path"):
                    file_path = DOWNLOAD_DIR / download["local_path"]
                    if file_path.exists():
                        file_path.unlink()
                # 删除记录
                downloads.remove(download)
                save_downloads(downloads)
                return JSONResponse(content={"status": "success"})
        raise HTTPException(status_code=404, detail="未找到该下载记录")
    except Exception as e:
        logger.error(f"删除下载记录失败: {e}")
        raise HTTPException(status_code=500, detail="删除下载记录失败") 