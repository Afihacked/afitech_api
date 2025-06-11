from fastapi import FastAPI, Query, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import requests
import yt_dlp
import uuid
import os
import shutil
import re
import instaloader
from datetime import datetime
from fastapi.routing import APIRoute
from urllib.parse import urlparse, urlunparse, parse_qs
from typing import Optional
import subprocess

app = FastAPI()


@app.get("/favicon.ico")
async def favicon():
    path = "static/favicon.ico"
    if os.path.exists(path):
        return FileResponse(path)
    return {}  # atau response kosong kalau file tidak ada

BASE_DOWNLOAD_DIR = "downloads"
os.makedirs(BASE_DOWNLOAD_DIR, exist_ok=True)

LOG_FILE = "download_logs.txt"
FFMPEG_PATH = shutil.which("ffmpeg")
COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")
IG_COOKIES_PATH = os.path.join(os.path.dirname(__file__), "ig_cookies.txt")
IG_SESSION_PATH = os.path.join(os.path.dirname(__file__), "session-afitechapi")

# Pastikan FFmpeg tersedia
if not FFMPEG_PATH:
    raise RuntimeError("FFmpeg tidak ditemukan. Pastikan sudah terinstall dan ada di PATH.")

app.mount("/static", StaticFiles(directory=BASE_DOWNLOAD_DIR), name="static")

def clean_instagram_url(url: str) -> str:
    parsed = urlparse(url)
    if "instagram.com" in parsed.netloc:
        cleaned = parsed._replace(query="", fragment="")
        return urlunparse(cleaned)
    return url

def cleanup_dir(path: str):
    try:
        shutil.rmtree(path)
    except Exception as e:
        print(f"Gagal hapus folder: {path} | Error: {e}")

def extract_shortcode_from_url(url: str) -> str:
    match = re.search(r"/p/([A-Za-z0-9_-]+)/", url)
    if not match:
        raise ValueError("Shortcode tidak ditemukan di URL Instagram.")
    return match.group(1)

def download_instagram_photo(url: str, download_dir: str, media_index: Optional[int] = None) -> str:
    loader = instaloader.Instaloader(
        dirname_pattern=download_dir,
        save_metadata=False,
        download_videos=False,
        download_comments=False
    )
    loader.load_session_from_file(username=None, filename=IG_SESSION_PATH)
    post = instaloader.Post.from_shortcode(loader.context, extract_shortcode_from_url(url))
    shortcode = post.shortcode
    nodes = post.get_sidecar_nodes() if post.typename == 'GraphSidecar' else [post]

    for idx, res in enumerate(nodes):
        if media_index is not None and idx != media_index:
            continue
        image_url = res.display_url if hasattr(res, "display_url") else post.url
        ext = "jpg"
        file_name = f"{shortcode}_{idx}.{ext}"
        file_path = os.path.join(download_dir, file_name)
        with open(file_path, "wb") as f:
            f.write(requests.get(image_url).content)
        break

    return shortcode


@app.get("/download/instagram-photo")
def download_instagram_photo_route(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    media: Optional[int] = Query(None)
):
    session_id = str(uuid.uuid4())
    download_dir = os.path.join(BASE_DOWNLOAD_DIR, session_id)
    os.makedirs(download_dir, exist_ok=True)

    try:
        shortcode = download_instagram_photo(url, download_dir, media)
        files = [f for f in os.listdir(download_dir) if shortcode in f and f.endswith((".jpg", ".jpeg", ".png"))]
        if not files:
            raise HTTPException(status_code=404, detail="Foto tidak ditemukan")
        photo_path = os.path.join(download_dir, sorted(files)[media or 0])
        background_tasks.add_task(cleanup_dir, download_dir)
        return FileResponse(photo_path, media_type="image/jpeg", filename=os.path.basename(photo_path))
    except Exception as e:
        shutil.rmtree(download_dir, ignore_errors=True)
        return JSONResponse(status_code=500, content={"error": f"Gagal unduh foto Instagram: {str(e)}"})


@app.get("/routes-debug")
def debug_routes():
    return [route.path for route in app.routes if isinstance(route, APIRoute)]

@app.get("/")
def root():
    return {"message": "Afitech Server Is Running Coyyy"}

def seconds_to_hhmmss(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02}:{m:02}:{s:02}"

def cut_media(input_path: str, output_path: str, start: str, end: str, is_audio: bool):
    from datetime import datetime

    def time_to_seconds(t: str) -> float:
        x = datetime.strptime(t, "%H:%M:%S")
        return x.hour * 3600 + x.minute * 60 + x.second

    duration = time_to_seconds(end) - time_to_seconds(start)
    if duration <= 0 or duration > 60:
        raise ValueError("Durasi harus antara 1–60 detik.")

    if is_audio:
        cmd = [
            FFMPEG_PATH,
            '-y',
            '-i', input_path,
            '-ss', start,          # seek akurat setelah -i
            '-t', str(duration),
            '-vn',
            '-acodec', 'libmp3lame',
            '-ab', '192k',
            '-avoid_negative_ts', '1',
            output_path
        ]
    else:
        cmd = [
            FFMPEG_PATH,
            '-y',
            '-i', input_path,
            '-ss', start,
            '-t', str(duration),
            '-c:v', 'libx264',
            '-preset', 'slow',         # lebih akurat frame
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            '-avoid_negative_ts', '1',
            output_path
        ]

    subprocess.run(cmd, check=True)

def get_clip_times(url: str) -> Optional[tuple[str, str]]:
    if "youtube.com/clip/" not in url:
        return None

    try:
        response = requests.get(url, allow_redirects=True, timeout=10)
        response.raise_for_status()

        redirected_url = response.url
        parsed = urlparse(redirected_url)
        query = parse_qs(parsed.query)
        start_sec = int(query.get("start", [0])[0])
        end_sec = int(query.get("end", [0])[0])
        return seconds_to_hhmmss(start_sec), seconds_to_hhmmss(end_sec)
    except:
        return None

@app.get("/download")
def download_video(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    format: str = Query("mp4"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None)
):
    session_id = str(uuid.uuid4())
    download_dir = os.path.join(BASE_DOWNLOAD_DIR, session_id)
    os.makedirs(download_dir, exist_ok=True)

    # Jika start & end kosong, cek apakah ini link clip
    if not start or not end:
        clip_times = get_clip_times(url)
        if clip_times:
            start, end = clip_times

    output_base = os.path.join(download_dir, session_id)
    temp_ext = "mp4" if format == "mp4" else "m4a"
    temp_path = f"{output_base}.{temp_ext}"
    final_path = f"{output_base}.{format}"

    ydl_opts = {
        'outtmpl': temp_path,
        'ffmpeg_location': FFMPEG_PATH,
        'format': 'bestaudio/best' if format == 'mp3' else 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
        'merge_output_format': temp_ext,
        'postprocessors': [],
        'socket_timeout': 3600,
        'noplaylist': True,
        'cookiefile': COOKIES_PATH,
        'quiet': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if start and end:
            cut_media(
                input_path=temp_path,
                output_path=final_path,
                start=start,
                end=end,
                is_audio=(format == "mp3")
            )
            os.remove(temp_path)
        else:
            final_path = temp_path

        filename = os.path.basename(final_path)
        with open(LOG_FILE, "a", encoding="utf-8") as log_file:
            log_file.write(f"{datetime.now().isoformat()} | {url} | {format} | {filename}\n")

        background_tasks.add_task(cleanup_dir, download_dir)
        return FileResponse(final_path, media_type="application/octet-stream", filename=filename)

    except Exception as e:
        shutil.rmtree(download_dir, ignore_errors=True)
        return JSONResponse(status_code=500, content={"error": f"Gagal mengunduh: {str(e)}"})

# (semua import tetap sama)

# ... kode sebelumnya tetap ...

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

    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    headers = {
        'User-Agent': user_agent,
        'Referer': 'https://www.instagram.com/',
    }

    common_opts = {
        'cookiefile': IG_COOKIES_PATH,
        'noplaylist': True,
        'quiet': True,
        'no_geo_bypass': True,
        'http_headers': headers,
    }

    info_opts = {
        **common_opts,
        'skip_download': True,
        'forcejson': True,
    }

    try:
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        entries = info.get("entries", [info])
        for entry in entries:
            ext = entry.get("ext", "")
            vcodec = entry.get("vcodec", "")
            media_url = entry.get("url")

            if not media_url:
                continue

            is_image = (vcodec == "none") or ext in ["jpg", "jpeg", "png", "webp"]

            if is_image:
                response = requests.get(media_url, stream=True, headers=headers)
                if response.status_code == 200:
                    file_ext = ext or "jpg"
                    filename = os.path.join(download_dir, f"{uuid.uuid4()}.{file_ext}")
                    with open(filename, "wb") as f:
                        shutil.copyfileobj(response.raw, f)
                    downloaded_files.append(filename)
            else:
                ydl_opts = {
                    **common_opts,
                    'outtmpl': os.path.join(download_dir, f"{session_id}_%(title).70s.%(ext)s"),
                    'format': 'bv*+ba/bestvideo+bestaudio/best',
                    'ffmpeg_location': FFMPEG_PATH,
                    'merge_output_format': format,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([entry.get("webpage_url", url)])

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
                downloaded_files[0],
                media_type=media_type,
                filename=os.path.basename(downloaded_files[0])
            )

        return JSONResponse({
            "status": "success",
            "files": [f"/static/{session_id}/{os.path.basename(f)}" for f in downloaded_files]
        })

    except Exception as e:
        shutil.rmtree(download_dir, ignore_errors=True)
        return JSONResponse(status_code=500, content={"error": f"Gagal unduh dari Instagram: {str(e)}"})




@app.get("/info")
def get_info(url: str, format: str = Query("mp4")):
    clean_url = clean_instagram_url(url)
    parsed_url = urlparse(clean_url)

    if "instagram.com" in parsed_url.netloc:
        # Proses sebagai Instagram
        shortcode_match = re.search(r'/(p|reel|tv)/([A-Za-z0-9_-]+)', clean_url + '/')
        if not shortcode_match:
            return JSONResponse(status_code=400, content={"error": "Invalid Instagram URL"})

        shortcode = shortcode_match.group(2)
        try:
            L = instaloader.Instaloader(
                download_pictures=False,
                download_videos=False,
                quiet=True
            )
            L.load_session_from_file(username="afitechapi", filename=IG_SESSION_PATH)
            post = instaloader.Post.from_shortcode(L.context, shortcode)

            result = {}
            if post.is_video:
                result["video"] = post.video_url
            elif post.typename == "GraphImage":
                result["images"] = [post.url]
            elif post.typename == "GraphSidecar":
                result["images"] = [node.display_url for node in post.get_sidecar_nodes()]
            else:
                result["images"] = []

            return result
        except Exception as e:
            print(f"[INFO fallback] Instaloader gagal: {e}")
            # lanjut ke yt-dlp fallback
    # Untuk selain Instagram (misalnya YouTube)
    try:
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'simulate': True,
            'forcejson': True,
            'format': 'bestaudio/best' if format == "mp3" else 'bestvideo+bestaudio/best',
            'cookiefile': COOKIES_PATH
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Tidak diketahui')
            formats = info.get('formats', [])
            filesize = 0
            valid_formats = [f for f in formats if f.get('filesize') or f.get('filesize_approx')]
            if valid_formats:
                best_format = max(valid_formats, key=lambda f: f.get('filesize', 0) or f.get('filesize_approx', 0))
                filesize = best_format.get('filesize') or best_format.get('filesize_approx', 0)
            return {"title": title, "filesize": filesize}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Gagal mengambil info video: {str(e)}"})
