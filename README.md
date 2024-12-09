# YouTube 视频下载器

一个简单的 YouTube 视频下载网站，使用 FastAPI + Jinja2 + yt-dlp + TailwindCSS 构建。

## 功能特点

- 支持输入 YouTube 视频链接进行下载
- 异步下载处理，避免阻塞
- 实时显示下载状态
- 支持视频预览播放
- 显示视频详细信息（标题、时长、作者等）
- 本地视频管理

## 安装说明

1. 克隆项目到本地：
```bash
git clone [项目地址]
cd [项目目录]
```

2. 创建并激活虚拟环境（可选但推荐）：
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
.\venv\Scripts\activate  # Windows
```

3. 安装依赖：
```bash
pip install -r requirements.txt
```

## 运行说明

1. 启动服务器：
```bash
uvicorn main:app --reload
```

2. 打开浏览器访问：
```
http://localhost:8000
```

## 使用说明

1. 在输入框中粘贴 YouTube 视频链接
2. 点击"开始下载"按钮
3. 等待下载完成
4. 在下方列表中查看和预览已下载的视频

## 目录结构

```
.
├── main.py              # 后端主程序
├── templates/           # ���端模板
│   └── index.html      # 主页面
├── downloads/          # 下载的视频存储目录
├── requirements.txt    # Python 依赖
└── README.md          # 项目说明
```

## 注意事项

- 确保有足够的磁盘空间存储下载的视频
- 下载大文件时可能需要等待较长时间
- 建议使用现代浏览器以获得最佳体验 