from fastapi import FastAPI, Query, BackgroundTasks
from fastapi.responses import FileResponse
import yt_dlp
import uuid
import os
import shutil
from datetime import datetime

app = FastAPI()

BASE_DOWNLOAD_DIR = "downloads"
os.makedirs(BASE_DOWNLOAD_DIR, exist_ok=True)

LOG_FILE = "download_logs.txt"
FFMPEG_PATH = shutil.which("ffmpeg")
COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")


def cleanup_dir(path: str):
    try:
        shutil.rmtree(path)
    except Exception as e:
        print(f"Gagal hapus folder: {path} | Error: {e}")


@app.get("/")
def root():
    return {"message": "YouTube Downloader API is running"}


@app.get("/download")
def download_video(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    format: str = Query("mp4"),
    start: str = Query(None, description="Start time in HH:MM:SS or MM:SS"),
    end: str = Query(None, description="End time in HH:MM:SS or MM:SS"),
):
    session_id = str(uuid.uuid4())
    download_dir = os.path.join(BASE_DOWNLOAD_DIR, session_id)
    os.makedirs(download_dir, exist_ok=True)

    outtmpl = os.path.join(download_dir, f"{session_id}.%(ext)s")
    download_sections = f"*{start}-{end}" if start and end else None

    ydl_opts = {
        'outtmpl': outtmpl,
        'format': 'bestaudio/best' if format == "mp3" else 'bestvideo+bestaudio/best',
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

                # ✅ Tulis log download
                with open(LOG_FILE, "a", encoding="utf-8") as log_file:
                    log_file.write(f"{datetime.now().isoformat()} | {url} | {format} | {file}\n")

                # ✅ Tambah tugas background untuk hapus folder
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

@app.get("/info")
def video_info(url: str = Query(...), format: str = Query("mp4")):
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'simulate': True,
        'forcejson': True,
        'format': 'bestaudio/best' if format == "mp3" else 'bestvideo+bestaudio/best',
        'cookiefile': COOKIES_PATH
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Tidak diketahui')
            filesize = 0

            # Coba ambil ukuran file dari entry format
            formats = info.get('formats', [])
            if formats:
                # Filter formats untuk hanya yang memiliki filesize atau filesize_approx yang valid
                valid_formats = [
                    f for f in formats
                    if f.get('filesize') is not None or f.get('filesize_approx') is not None
                ]

                if valid_formats:
                    # Pilih format dengan filesize terbesar
                    best_format = max(
                        valid_formats,
                        key=lambda f: (f.get('filesize', 0) or f.get('filesize_approx', 0))
                    )
                    filesize = best_format.get('filesize') or best_format.get('filesize_approx', 0)

            return {
                "title": title,
                "filesize": filesize
            }
    except Exception as e:
        return {"error": f"Gagal mengambil info video: {str(e)}"}


