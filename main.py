from fastapi import FastAPI, Query, BackgroundTasks
from fastapi.responses import FileResponse
import yt_dlp
import uuid
import os
import shutil
import zipfile
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


def delete_file(path: str):
    try:
        os.remove(path)
    except Exception as e:
        print(f"Gagal hapus file: {path} | Error: {e}")


@app.get("/")
def root():
    return {"message": "Instagram Downloader API is running"}


@app.get("/download/instagram")
def download_instagram(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    format: str = Query("mp4")  # "mp4" untuk video, "mp3" untuk audio saja
):
    session_id = str(uuid.uuid4())
    download_dir = os.path.join(BASE_DOWNLOAD_DIR, session_id)
    os.makedirs(download_dir, exist_ok=True)

    outtmpl = os.path.join(download_dir, f"{session_id}_%(title).70s.%(ext)s")

    ydl_opts = {
        'outtmpl': outtmpl,
        'format': 'best' if format == "mp4" else 'bestaudio/best',
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

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        downloaded_files = [
            os.path.join(download_dir, f)
            for f in os.listdir(download_dir)
            if os.path.isfile(os.path.join(download_dir, f))
        ]

        if not downloaded_files:
            return {"error": f"Tidak ada file berhasil diunduh"}

        # Log unduhan
        with open(LOG_FILE, "a", encoding="utf-8") as log_file:
            for f in downloaded_files:
                log_file.write(f"{datetime.now().isoformat()} | {url} | {format} | {os.path.basename(f)}\n")

        background_tasks.add_task(cleanup_dir, download_dir)

        if len(downloaded_files) == 1:
            media_type = "video/mp4" if format == "mp4" else "audio/mpeg"
            return FileResponse(
                path=downloaded_files[0],
                filename=os.path.basename(downloaded_files[0]),
                media_type=media_type
            )
        else:
            zip_path = os.path.join(BASE_DOWNLOAD_DIR, f"{session_id}.zip")
            with zipfile.ZipFile(zip_path, "w") as zipf:
                for file in downloaded_files:
                    zipf.write(file, os.path.basename(file))

            background_tasks.add_task(delete_file, zip_path)

            return FileResponse(
                path=zip_path,
                filename=f"instagram_download_{session_id}.zip",
                media_type="application/zip"
            )

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

            formats = info.get('formats', [])
            valid_formats = [
                f for f in formats if f.get('filesize') or f.get('filesize_approx')
            ]

            if valid_formats:
                best_format = max(
                    valid_formats,
                    key=lambda f: f.get('filesize') or f.get('filesize_approx', 0)
                )
                filesize = best_format.get('filesize') or best_format.get('filesize_approx', 0)

            return {
                "title": title,
                "filesize": filesize
            }
    except Exception as e:
        return {"error": f"Gagal mengambil info video: {str(e)}"}
