import os
import re
import time
import asyncio
import logging
import tempfile
from typing import Dict
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, InputMediaPhoto, InputMediaVideo
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import yt_dlp

# === Настройка ===
if os.path.exists(".env"):
    load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN must be set in .env or environment variables.")

DOWNLOADS_DIR = os.path.join(tempfile.gettempdir(), "instabot_downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

rate_limit_db: Dict[int, float] = {}
RATE_LIMIT_SECONDS = 15

# === Regex ===
SUPPORTED_LINK_REGEX = re.compile(
    r'https?://(?:www\.)?'
    r'(?:instagram\.com|youtube\.com|youtu\.be|tiktok\.com|vt\.tiktok\.com|'
    r'pinterest\.com|pin\.it|vk\.com|vkvideo\.ru)'
    r'/[^\s]+',
    re.IGNORECASE
)

INSTAGRAM_STORY_REGEX = re.compile(
    r'https?://(?:www\.)?instagram\.com/stories/([a-zA-Z0-9\._-]+)',
    re.IGNORECASE
)

# === Функции скачивания ===

async def download_instagram_media(url: str, post_id: str) -> list[tuple[str, str]]:
    """Скачивает фото и видео из Instagram (включая карусели)"""
    output_tmpl = os.path.join(DOWNLOADS_DIR, f"{post_id}_%(playlist_index)s.%(ext)s")

    ydl_opts = {
        'format': 'bestvideo*+bestaudio/best',
        'outtmpl': output_tmpl,
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
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
    """Универсальная загрузка с TikTok, YouTube, Pinterest, VK"""
    output_tmpl = os.path.join(DOWNLOADS_DIR, "%(title).80s_%(id)s.%(ext)s")

    ydl_opts = {
        'format': 'bestvideo*+bestaudio/best',
        'outtmpl': output_tmpl,
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
        'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
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
                            mtype = 'video' if filepath.lower().endswith(('.mp4', '.webm', '.mov')) else 'photo'
                            files.append((filepath, mtype))
            else:
                filepath = info.get('filepath') or ydl.prepare_filename(info)
                if os.path.exists(filepath):
                    mtype = 'video' if filepath.lower().endswith(('.mp4', '.webm', '.mov')) else 'photo'
                    files.append((filepath, mtype))
            return files

    return await loop.run_in_executor(None, _download)


# === Обработчики ===

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.reply(
        "Ты пидрюга ебанный. Готовь свой задок, я сейчас буду заливать в тебя свою густую сперму прямо из инсты, тиктока и ютуба 🔥"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.reply(
        "Не еби мозги, просто кинь ссылку на видео или фото из Instagram, TikTok, YouTube, Pinterest или VK.\n"
        "Я вытащу всё и залью тебе сперму в чат, как положено."
    )


@dp.message(F.text.regexp(INSTAGRAM_STORY_REGEX))
async def handle_stories_link(message: Message):
    await message.reply("Истории не поддерживаются, пидор. Кидай обычный пост или рилс.")


@dp.message(lambda msg: msg.text and SUPPORTED_LINK_REGEX.search(msg.text))
async def handle_media_download(message: Message):
    user_id = message.from_user.id
    current_time = time.time()

    if current_time - rate_limit_db.get(user_id, 0) < RATE_LIMIT_SECONDS:
        seconds_left = int(RATE_LIMIT_SECONDS - (current_time - rate_limit_db.get(user_id, 0)))
        await message.reply(f"⏳ Подожди {seconds_left} сек., я ещё не успел кончить.")
        return

    url = SUPPORTED_LINK_REGEX.search(message.text).group(0)
    rate_limit_db[user_id] = current_time

    status_msg = await message.reply("⏳ Скачиваю твою сперму из интернета...")

    try:
        if 'instagram.com' in url:
            post_id = re.search(r'/([a-zA-Z0-9_-]+)', url).group(1)
            media_files = await download_instagram_media(url, post_id)
        else:
            media_files = await download_generic_media(url)

        if not media_files:
            await status_msg.edit_text("Не удалось вытащить сперму из этой ссылки.")
            return

        await bot.delete_message(message.chat.id, status_msg.message_id)

        # Отправляем по 10 штук
        for i in range(0, len(media_files), 10):
            chunk = media_files[i:i + 10]
            media_group = []

            for file_path, media_type in chunk:
                if media_type == 'video':
                    media_group.append(InputMediaVideo(media=FSInputFile(file_path)))
                else:
                    media_group.append(InputMediaPhoto(media=FSInputFile(file_path)))

            await message.reply_media_group(media=media_group)

        # Чистим файлы
        for file_path, _ in media_files:
            try:
                os.remove(file_path)
            except:
                pass

    except Exception as e:
        logger.exception(f"Ошибка: {e}")
        await status_msg.edit_text("Не удалось залить сперму. Попробуй другую ссылку.")


@dp.message(F.text)
async def handle_unknown_text(message: Message):
    if message.chat.type != "private":
        return

    await message.reply(
        "<b>Режим ожидания спермы!</b>\n\n"
        "Кидай ссылку на видео или фото из Instagram, TikTok, YouTube, Pinterest или VK — я всё вытащу и залью тебе в чат."
    )


# === Запуск ===

async def main():
    logger.info("Бот запущен и готов заливать сперму...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
    finally:
        print("=== Бот завершил работу ===")
        input("Нажми Enter, чтобы закрыть окно...")
