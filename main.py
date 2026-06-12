async def download_instagram_media(url: str, post_id: str) -> list[tuple[str, str]]:
    output_tmpl = os.path.join(DOWNLOADS_DIR, f"{post_id}_%(playlist_index)s.%(ext)s")

    ydl_opts = {
        'format': 'best[ext=mp4]/best',           # ← Главное изменение
        'outtmpl': output_tmpl,
        'quiet': True,
        'no_warnings': True,
        'http_headers': {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X)'}
    }

    loop = asyncio.get_running_loop()
    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            files = []
            if 'entries' in info and info['entries']:
                for entry in info['entries']:
                    if entry:
                        filepath = entry.get('filepath') or ydl.prepare_filename(entry)
                        if os.path.exists(filepath):
                            mtype = 'video' if filepath.lower().endswith(('.mp4', '.mov', '.webm')) else 'photo'
                            files.append((filepath, mtype))
            else:
                filepath = info.get('filepath') or ydl.prepare_filename(info)
                if os.path.exists(filepath):
                    mtype = 'video' if filepath.lower().endswith(('.mp4', '.mov', '.webm')) else 'photo'
                    files.append((filepath, mtype))
            return files
    return await loop.run_in_executor(None, _download)


async def download_generic_media(url: str) -> list[tuple[str, str]]:
    output_tmpl = os.path.join(DOWNLOADS_DIR, "%(title).80s_%(id)s.%(ext)s")

    ydl_opts = {
        'format': 'best[ext=mp4]/best',           # ← Главное изменение
        'outtmpl': output_tmpl,
        'quiet': True,
        'no_warnings': True,
    }

    loop = asyncio.get_running_loop()
    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            files = []
            if 'entries' in info and info['entries']:
                for entry in info['entries']:
                    if entry:
                        filepath = entry.get('filepath') or ydl.prepare_filename(entry)
                        if os.path.exists(filepath):
                            mtype = 'video' if filepath.lower().endswith(('.mp4', '.mov', '.webm')) else 'photo'
                            files.append((filepath, mtype))
            else:
                filepath = info.get('filepath') or ydl.prepare_filename(info)
                if os.path.exists(filepath):
                    mtype = 'video' if filepath.lower().endswith(('.mp4', '.mov', '.webm')) else 'photo'
                    files.append((filepath, mtype))
            return files
    return await loop.run_in_executor(None, _download)
