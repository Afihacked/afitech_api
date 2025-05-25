from fastapi import FastAPI, Query, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import requests
import yt_dlp
import uuid
import os
import shutil
from datetime import datetime
from fastapi.routing import APIRoute
from urllib.parse import urlparse, urlunparse

app = FastAPI()

BASE_DOWNLOAD_DIR = "downloads"
os.makedirs(BASE_DOWNLOAD_DIR, exist_ok=True)

LOG_FILE = "download_logs.txt"
FFMPEG_PATH = shutil.which("ffmpeg")
COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")

app.mount("/static", StaticFiles(directory=BASE_DOWNLOAD_DIR), name="static")

def clean_instagram_url(url: str) -> str:
    parsed = urlparse(url)
    if "instagram.com" in parsed.netloc:
        # Hilangkan parameter query dan fragment
        cleaned = parsed._replace(query="", fragment="")
        return urlunparse(cleaned)
    return url


def cleanup_dir(path: str):
    try:
        shutil.rmtree(path)
    except Exception as e:
        print(f"Gagal hapus folder: {path} | Error: {e}")


@app.get("/routes-debug")
def debug_routes():
    return [route.path for route in app.routes if isinstance(route, APIRoute)]


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
    format: str = Query("mp4")
):
    url = clean_instagram_url(url)
    session_id = str(uuid.uuid4())
    download_dir = os.path.join(BASE_DOWNLOAD_DIR, session_id)
    os.makedirs(download_dir, exist_ok=True)

    downloaded_files = []

    # Tahap 1: Ambil info
    info_opts = {
        'quiet': True,
        'skip_download': True,
        'forcejson': True,
        'cookiefile': COOKIES_PATH,
        'noplaylist': True,
    }

    try:
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        entries = info.get("entries", [info]) if "entries" in info else [info]

        for entry in entries:
            media_url = entry.get("url")
            if not media_url:
                continue  # Skip jika tidak ada URL

            ext = entry.get("ext") or (
                "jpg" if any(media_url.endswith(x) for x in [".jpg", ".jpeg", ".png", ".webp"]) else "mp4"
            )

            webpage_url = entry.get("webpage_url", url)

            # Download gambar secara manual
            if ext in ["jpg", "jpeg", "png", "webp"]:
                response = requests.get(media_url, stream=True)
                if response.status_code == 200:
                    filename = os.path.join(download_dir, f"{uuid.uuid4()}.{ext}")
                    with open(filename, "wb") as f:
                        shutil.copyfileobj(response.raw, f)
                    downloaded_files.append(filename)
            else:
                # Tahap 2: Download video pakai yt-dlp
                ydl_opts = {
                    'outtmpl': os.path.join(download_dir, f"{session_id}_%(title).70s.%(ext)s"),
                    'format': 'bv*+ba/bestvideo+bestaudio/best',
                    'ffmpeg_location': FFMPEG_PATH,
                    'merge_output_format': format,
                    'cookiefile': COOKIES_PATH,
                    'quiet': True,
                    'noplaylist': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([webpage_url])

        # Cari file hasil download
        for file in os.listdir(download_dir):
            full_path = os.path.join(download_dir, file)
            if os.path.isfile(full_path):
                downloaded_files.append(full_path)

        if not downloaded_files:
            raise HTTPException(status_code=404, detail="Tidak ada file berhasil diunduh.")

        with open(LOG_FILE, "a", encoding="utf-8") as log_file:
            for f in downloaded_files:
                log_file.write(f"{datetime.now().isoformat()} | {url} | {format} | {os.path.basename(f)}\n")

        background_tasks.add_task(cleanup_dir, download_dir)

        if len(downloaded_files) == 1:
            media_type = "video/mp4" if downloaded_files[0].endswith(".mp4") else "image/jpeg"
            return FileResponse(
                path=downloaded_files[0],
                filename=os.path.basename(downloaded_files[0]),
                media_type=media_type
            )
        else:
            return {
                "message": "Beberapa file berhasil diunduh",
                "files": [
                    f"/static/{session_id}/{os.path.basename(f)}" for f in downloaded_files
                ]
            }

    except Exception as e:
        shutil.rmtree(download_dir, ignore_errors=True)
        return {"error": f"Gagal mengunduh: {str(e)}"}

@app.get("/info")
def video_info(url: str = Query(...)):
    url = clean_instagram_url(url)

    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'forcejson': True,
        'cookiefile': COOKIES_PATH,
        'noplaylist': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            images = []
            video_url = None

            entries = info.get("entries", [info]) if "entries" in info else [info]

            for entry in entries:
                media_url = entry.get("url")
                if not media_url:
                    continue

                # Deteksi berdasarkan ekstensi atau mimetype
                if any(ext in media_url for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                    images.append(media_url)
                elif ".mp4" in media_url:
                    video_url = media_url

            return {
                "title": info.get("title", "Tidak diketahui"),
                "video": video_url,
                "images": images
            }

    except Exception as e:
        return {
            "error": f"Gagal mengambil info konten: {str(e)}"
        }


