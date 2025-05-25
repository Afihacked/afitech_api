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
    session_id = str(uuid.uuid4())
    download_dir = os.path.join(BASE_DOWNLOAD_DIR, session_id)
    os.makedirs(download_dir, exist_ok=True)

    try:
        ydl_info_opts = {
            'quiet': True,
            'skip_download': True,
            'forcejson': True,
            'cookiefile': COOKIES_PATH,
        }

        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        entries = info.get("entries", [info]) if "entries" in info else [info]
        image_urls = []
        for entry in entries:
            if entry.get("ext") in ["jpg", "jpeg", "png", "webp"]:
                image_urls.append(entry.get("url"))

        if image_urls:
            downloaded_files = []
            for idx, img_url in enumerate(image_urls):
                ext = os.path.splitext(img_url)[1].split("?")[0] or ".jpg"
                filename = f"{session_id}_{idx}{ext}"
                path = os.path.join(download_dir, filename)

                response = requests.get(img_url, stream=True)
                with open(path, "wb") as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)

                downloaded_files.append(path)

            background_tasks.add_task(cleanup_dir, download_dir)

            if len(downloaded_files) == 1:
                return FileResponse(
                    path=downloaded_files[0],
                    filename=os.path.basename(downloaded_files[0]),
                    media_type="image/jpeg",
                    background=background_tasks
                )
            else:
                return JSONResponse(
                    content={
                        "message": "Beberapa gambar berhasil diunduh",
                        "files": [f"/static/{session_id}/{os.path.basename(f)}" for f in downloaded_files]
                    }
                )

        # Jika tidak ada gambar, lanjutkan dengan video
        outtmpl = os.path.join(download_dir, f"{session_id}_%(title).70s.%(ext)s")
        ydl_download_opts = {
            'outtmpl': outtmpl,
            'format': 'bv*+ba/bestvideo+bestaudio/best' if format == "mp4" else 'bestaudio/best',
            'ffmpeg_location': FFMPEG_PATH,
            'merge_output_format': format,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }] if format == "mp3" else [],
            'cookiefile': COOKIES_PATH,
            'noplaylist': False,
            'socket_timeout': 3600,
        }

        with yt_dlp.YoutubeDL(ydl_download_opts) as ydl:
            ydl.download([url])

        downloaded_files = [
            os.path.join(download_dir, f)
            for f in os.listdir(download_dir)
            if os.path.isfile(os.path.join(download_dir, f))
        ]

        if not downloaded_files:
            return {"error": "Tidak ada file berhasil diunduh"}

        background_tasks.add_task(cleanup_dir, download_dir)

        return FileResponse(
            path=downloaded_files[0],
            filename=os.path.basename(downloaded_files[0]),
            media_type="video/mp4" if format == "mp4" else "audio/mpeg"
        )

    except Exception as e:
        shutil.rmtree(download_dir, ignore_errors=True)
        return {"error": f"Gagal mengunduh: {str(e)}"}


@app.get("/info")
def video_info(url: str = Query(...)):
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'forcejson': True,
        'cookiefile': COOKIES_PATH,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            images = []
            videos = []

            entries = info.get("entries", [info]) if "entries" in info else [info]

            for entry in entries:
                ext = entry.get("ext")
                file_url = entry.get("url")

                if not file_url:
                    continue

                if ext in ["jpg", "jpeg", "png", "webp"]:
                    images.append(file_url)
                elif ext == "mp4":
                    videos.append(file_url)

            return {
                "title": info.get("title", "Tidak diketahui"),
                "videos": videos,
                "images": images
            }

    except Exception as e:
        return {
            "error": f"Gagal mengambil info konten: {str(e)}"
        }
