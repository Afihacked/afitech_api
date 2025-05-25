FROM python:3.11-slim

ARG PORT
ENV PORT=${PORT}

RUN apt-get update && apt-get install -y ffmpeg curl

# ⬇️ Download yt-dlp terbaru langsung dari GitHub
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp \
 && chmod a+rx /usr/local/bin/yt-dlp

WORKDIR /app
COPY . /app

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

CMD uvicorn main:app --host 0.0.0.0 --port $PORT
