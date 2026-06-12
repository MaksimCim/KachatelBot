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

if os.path.exists(".env"):
    load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN must be set!")

DOWNLOADS_DIR = os.path.join(tempfile.gettempdir(), "instabot_downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

rate_limit_db: Dict[int, float] = {}
RATE_LIMIT_SECONDS = 5

SUPPORTED_LINK_REGEX = re.compile(
    r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/([a-zA-Z0-9_-]+)',
    re.IGNORECASE
)

INSTAGRAM_STORY_REGEX = re.compile(
    r'https?://(?:www\.)?instagram\.com/stories/([a-zA-Z0-9\._-]+)',
    re.IGNORECASE
)

async def download_instagram_media(url: str, post_id: str) -> list[tuple[str, str]]:
    output_tmpl = os.path.join(DOWNLOADS_DIR, f"{post_id}_%(playlist_index)s.%(ext)s")

    ydl_opts = {
        'format': 'best',
        'outtmpl': output_tmpl,
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'instagram': {'api_hostname': 'i.instagram.com'}
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
        }
    }

    loop = asyncio.get_running_loop()

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            files = []

            if info is None:
                return files

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


@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.reply("Готов залить себе сперму? Кидай ссылку на Instagram — я вытащу видео или фото.")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.reply("Просто кинь ссылку на пост или Reel из Instagram.")


@dp.message(F.text.regexp(INSTAGRAM_STORY_REGEX))
async def handle_stories_link(message: Message):
    await message.reply("Истории не поддерживаются. Кидай обычный пост или рилс.")


@dp.message(lambda msg: msg.text and SUPPORTED_LINK_REGEX.search(msg.text))
async def handle_instagram_download(message: Message):
    user_id = message.from_user.id
    current_time = time.time()

    if current_time - rate_limit_db.get(user_id, 0) < RATE_LIMIT_SECONDS:
        seconds_left = int(RATE_LIMIT_SECONDS - (current_time - rate_limit_db.get(user_id, 0)))
        await message.reply(f"⏳ Подожди {seconds_left} сек.")
        return

    url = SUPPORTED_LINK_REGEX.search(message.text).group(0)
    post_id = SUPPORTED_LINK_REGEX.search(message.text).group(1)
    rate_limit_db[user_id] = current_time

    status_msg = await message.reply("⏳ Скачиваю из Instagram...")

    try:
        media_files = await download_instagram_media(url, post_id)

        if not media_files:
            rate_limit_db[user_id] = 0
            await status_msg.edit_text("Не удалось скачать. Попробуй другую ссылку.")
            return

        await bot.delete_message(message.chat.id, status_msg.message_id)

        # Отправляем по 10 штук
        for i in range(0, len(media_files), 10):
            chunk = media_files[i:i + 10]
            media_group = []

            for file_path, media_type in chunk:
                try:
                    if media_type == 'video':
                        media_group.append(InputMediaVideo(media=FSInputFile(file_path)))
                    else:
                        media_group.append(InputMediaPhoto(media=FSInputFile(file_path)))
                except Exception as send_err:
                    logger.warning(f"Не удалось добавить файл в группу: {send_err}")

            if media_group:
                try:
                    await message.reply_media_group(media=media_group)
                except Exception as group_err:
                    logger.error(f"Ошибка при отправке медиа-группы: {group_err}")
                    await message.reply("Не удалось отправить медиа (таймаут). Попробуй позже.")

        # Чистим файлы
        for file_path, _ in media_files:
            try:
                os.remove(file_path)
            except:
                pass

    except Exception as e:
        rate_limit_db[user_id] = 0
        logger.exception(f"Ошибка Instagram: {e}")
        try:
            await status_msg.edit_text("Не удалось скачать из Instagram. Попробуй другую ссылку.")
        except:
            pass


@dp.message(F.text)
async def handle_unknown_text(message: Message):
    if message.chat.type != "private":
        return
    await message.reply("Кидай ссылку на пост или Reel из Instagram.")


async def main():
    logger.info("Бот запущен (фокус на Instagram)")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
