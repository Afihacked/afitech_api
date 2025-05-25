from fastapi import FastAPI, Query, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import yt_dlp
import uuid
import os
import shutil
import requests
from datetime import datetime

app = FastAPI()

BASE_DOWNLOAD_DIR = "downloads"
os.makedirs(BASE_DOWNLOAD_DIR, exist_ok=True)

LOG_FILE = "download_logs.txt"
FFMPEG_PATH = shutil.which("ffmpeg")
COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")

app.mount("/static", StaticFiles(directory=BASE_DOWNLOAD_DIR), name="static")

def cleanup_dir(path: str):
    try:
        shutil.rmtree(path)
    except Exception as e:
        print(f"Failed to delete: {e}")

@app.get("/")
def root():
    return {"message": "YouTube Downloader API is running"}

@app.get("/download")
def download_video(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    format: str = Query("mp4"),
    start: str = Query(None),
    end: str = Query(None),
):
    session_id = str(uuid.uuid4())
    download_dir = os.path.join(BASE_DOWNLOAD_DIR, session_id)
    os.makedirs(download_dir, exist_ok=True)

    outtmpl = os.path.join(download_dir, f"{session_id}.%(ext)s")
    download_sections = f"*{start}-{end}" if start and end else None

    ydl_opts = {
        'outtmpl': outtmpl,
        'format': 'bv*+ba/bestvideo+bestaudio/best' if format == "mp4" else 'bestaudio/best',
        'ffmpeg_location': FFMPEG_PATH,
        'merge_output_format': format,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }] if format == "mp3" else [],
        'socket_timeout': 3600,
        'noplaylist': True,
        'cookiefile': COOKIES_PATH
    }

    if download_sections:
        ydl_opts['download_sections'] = download_sections

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        for file in os.listdir(download_dir):
            if file.startswith(session_id) and file.endswith(f".{format}"):
                filepath = os.path.join(download_dir, file)

                with open(LOG_FILE, "a", encoding="utf-8") as log_file:
                    log_file.write(f"{datetime.now().isoformat()} | {url} | {format} | {file}\n")

                background_tasks.add_task(cleanup_dir, download_dir)

                return FileResponse(
                    filepath,
                    media_type="application/octet-stream",
                    filename=file,
                    background=background_tasks
                )

        return {"error": f"File .{format} tidak ditemukan setelah download"}
    except Exception as e:
        shutil.rmtree(download_dir, ignore_errors=True)
        return {"error": f"Gagal mengunduh: {str(e)}"}

@app.get("/download/instagram")
def download_instagram(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
):
    session_id = str(uuid.uuid4())
    download_dir = os.path.join(BASE_DOWNLOAD_DIR, session_id)
    os.makedirs(download_dir, exist_ok=True)

    try:
        ydl_opts_info = {
            'quiet': True,
            'skip_download': True,
            'forcejson': True,
            'cookiefile': COOKIES_PATH,
        }

        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)

        image_urls = []
        video_url = None

        entries = info.get("entries", [info])
        for entry in entries:
            ext = entry.get("ext")
            if ext in ["jpg", "jpeg", "png", "webp"]:
                image_urls.append(entry.get("url"))
            elif ext == "mp4":
                video_url = entry.get("url")

        if image_urls:
            downloaded_files = []
            for idx, img_url in enumerate(image_urls):
                ext = os.path.splitext(img_url)[-1]
                path = os.path.join(download_dir, f"{session_id}_{idx}{ext}")
                r = requests.get(img_url, stream=True)
                with open(path, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                downloaded_files.append(path)

            if len(downloaded_files) == 1:
                background_tasks.add_task(cleanup_dir, download_dir)
                return FileResponse(
                    downloaded_files[0],
                    filename=os.path.basename(downloaded_files[0]),
                    media_type="image/jpeg"
                )
            else:
                urls = [
                    f"/static/{session_id}/{os.path.basename(f)}"
                    for f in downloaded_files
                ]
                background_tasks.add_task(cleanup_dir, download_dir)
                return {
                    "message": "Beberapa gambar berhasil diunduh",
                    "files": urls
                }

        elif video_url:
            outtmpl = os.path.join(download_dir, f"{session_id}_%(title).70s.%(ext)s")
            ydl_opts = {
                'outtmpl': outtmpl,
                'format': 'best',
                'ffmpeg_location': FFMPEG_PATH,
                'cookiefile': COOKIES_PATH,
                'noplaylist': False,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            video_files = [
                os.path.join(download_dir, f)
                for f in os.listdir(download_dir)
                if f.endswith(".mp4")
            ]

            if not video_files:
                return {"error": "Video tidak ditemukan"}

            background_tasks.add_task(cleanup_dir, download_dir)
            return FileResponse(
                path=video_files[0],
                filename=os.path.basename(video_files[0]),
                media_type="video/mp4"
            )

        else:
            return {"error": "Tidak ada media ditemukan"}

    except Exception as e:
        shutil.rmtree(download_dir, ignore_errors=True)
        return {"error": f"Gagal mengunduh: {str(e)}"}

@app.get("/info")
def video_info(url: str = Query(...)):
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'forcejson': True,
        'noplaylist': True,
        'cookiefile': COOKIES_PATH,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        title = info.get("title", "Tidak diketahui")
        video_url = None
        images = []

        entries = info.get("entries", [info])
        for entry in entries:
            ext = entry.get("ext")
            if ext == "mp4":
                video_url = entry.get("url")
            elif ext in ["jpg", "jpeg", "png", "webp"]:
                images.append(entry.get("url"))
            elif entry.get("thumbnails"):
                thumbs_sorted = sorted(entry["thumbnails"], key=lambda x: x.get("height", 0), reverse=True)
                if thumbs_sorted:
                    images.append(thumbs_sorted[0].get("url"))

        return {
            "title": title,
            "video": video_url,
            "images": images
        }

    except Exception as e:
        return {"error": f"Gagal mengambil info: {str(e)}"}
