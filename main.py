import os
import re
import time
import asyncio
import logging
import tempfile
import shutil
import urllib.request
import urllib.error
from typing import Dict, List, Tuple, Optional

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, InputMediaPhoto, InputMediaVideo
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import yt_dlp

# Load environment variables
if os.path.exists(".env"):
    load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    logger.error("BOT_TOKEN is not defined in the environment or .env file!")
    raise ValueError("BOT_TOKEN must be specified in the environment variables.")

# Create temporary download directory if it doesn't exist
DOWNLOADS_DIR = os.path.join(tempfile.gettempdir(), "instabot_downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Initialize Bot and Dispatcher
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# In-memory rate limiting dictionary: {user_id: last_download_timestamp}
rate_limit_db: Dict[int, float] = {}
RATE_LIMIT_SECONDS = 10

# Regular expressions for detecting Instagram URLs
SUPPORTED_LINK_REGEX = re.compile(
    r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/([a-zA-Z0-9_-]+)',
    re.IGNORECASE
)
INSTAGRAM_STORY_REGEX = re.compile(
    r'https?://(?:www\.)?instagram\.com/stories/([a-zA-Z0-9\._-]+)',
    re.IGNORECASE
)


def download_file(url: str, output_path: str):
    """
    Synchronous helper to download media (photo/video) directly from Instagram's CDN URL
    using python's built-in urllib module with custom browser headers.
    """
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,video/mp4,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        }
    )
    with urllib.request.urlopen(req, timeout=30) as response, open(output_path, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)


async def download_instagram_media(url: str, post_id: str) -> List[Tuple[str, str]]:
    """
    Downloads media files (photos, videos, or mixed carousel slider albums) from Instagram.
    Uses yt-dlp to extract high-res direct URLs asynchronously, and then downloads each asset.
    Returns: a list of tuples containing (filepath, media_type viz. 'photo' or 'video')
    """
    # options for extraction only, bypassing yt-dlp local downloader to download images and videos reliably
    ydl_opts = {
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

    def _extract_and_download() -> List[Tuple[str, str]]:
        files = []
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                # download=False only extracts metadata- avoids Failures on image assets
                info = ydl.extract_info(url, download=False)
            except Exception as e:
                logger.error(f"Error extracting metadata for URL: {url} - {e}")
                return files

            if info is None:
                return files

            # Check if it's a carousel list of items
            entries = info.get('entries')
            if not entries:
                # Single item post
                entries = [info]

            for index, entry in enumerate(entries):
                if not entry:
                    continue

                # Get direct URL
                direct_url = entry.get('url')
                ext = (entry.get('ext') or '').lower()

                # If no direct url is found, parse formats list (normally found for videos)
                formats = entry.get('formats', [])
                if formats:
                    best_format = formats[-1]
                    if not direct_url:
                        direct_url = best_format.get('url')
                    if not ext:
                        ext = (best_format.get('ext') or '').lower()

                # If still no direct link, fallback to thumbnails/images if present
                if not direct_url:
                    direct_url = entry.get('thumbnail')
                    if not ext:
                        ext = 'jpg'

                if not direct_url:
                    continue

                # Classify media type: video or photo
                is_video = False
                vcodec = entry.get('vcodec') or ''
                if vcodec and vcodec != 'none':
                    is_video = True
                elif ext in ['mp4', 'mov', 'webm', 'mkv', '3gp']:
                    is_video = True
                elif 'mp4' in direct_url or '/v/' in direct_url:
                    is_video = True

                media_type = 'video' if is_video else 'photo'
                file_ext = 'mp4' if is_video else ('jpg' if ext not in ['jpg', 'jpeg', 'png', 'webp'] else ext)

                # Prepare safe filename
                filepath = os.path.join(DOWNLOADS_DIR, f"{post_id}_{index + 1}.{file_ext}")

                logger.info(f"Downloading direct URL ({media_type}): {direct_url[:50]}... to {filepath}")

                try:
                    download_file(direct_url, filepath)
                    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                        files.append((filepath, media_type))
                except Exception as dl_err:
                    logger.error(f"Failed to download media item {index + 1} from direct URL: {dl_err}")

            return files

    return await loop.run_in_executor(None, _extract_and_download)


# Handler for /start command
@dp.message(Command("start"))
async def cmd_start(message: Message):
    welcome_text = (
        "👋 <b>Привет! Я бот для скачивания медиафайлов из Instagram!</b>\n\n"
        "Отправьте мне ссылку на любой <b>Reel, видео или фото-пост (включая карусели)</b> из Instagram, "
        "и я скачаю его для вас в максимальном качестве!\n\n"
        "✨ <b> Особенности бота:</b>\n"
        "• 🎞 Скачивает Reels и стандартные видео\n"
        "• 📸 Скачивает фотографии и полные карусели из постов\n"
        "• ⚡️ Максимально быстрая скорость загрузки\n\n"
        "👉 Просто отправьте мне ссылку!"
    )
    await message.reply(welcome_text)


# Handler for /help command
@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "🤖 <b>Справка по использованию бота</b>\n\n"
        "<b>Как скачивать медиа:</b>\n"
        "Просто отправьте текстовое сообщение со ссылкой на пост или Reel из Instagram. Бот сам найдет ссылку и начнет загрузку.\n\n"
        "⚠️ <b>Ограничения:</b>\n"
        "1. <b>Лимит частоты:</b> Запускать скачивание можно раз в 10 секунд во избежание блокировок.\n"
        "2. <b>Размер файла:</b> Телеграм-боты ограничены отправкой файлов до 50 МБ. Очень большие видео могут не отправиться.\n"
        "3. <b>Stories:</b> Скачивание временных Историй не поддерживается напрямую, так как они требуют активную сессию авторизации."
    )
    await message.reply(help_text)


# Handler for stories links
@dp.message(F.text.regexp(INSTAGRAM_STORY_REGEX))
async def handle_stories_link(message: Message):
    story_warning = (
        "💡 <b>Скачивание Историй (Stories) временно не поддерживается.</b>\n\n"
        "Для безопасного скачивания приватных историй требуются файлы сессии авторизованного аккаунта. "
        "По соображениям безопасности мы поддерживаем загрузку только из открытых "
        "источников: обычных публикаций (posts), фотографий и рилсов (reels)."
    )
    await message.reply(story_warning)


# Main handler for Instagram links
@dp.message(lambda msg: msg.text and SUPPORTED_LINK_REGEX.search(msg.text))
async def handle_instagram_download(message: Message):
    user_id = message.from_user.id
    current_time = time.time()

    # Rate limiting check
    last_use = rate_limit_db.get(user_id, 0)
    if current_time - last_use < RATE_LIMIT_SECONDS:
        seconds_left = int(RATE_LIMIT_SECONDS - (current_time - last_use))
        await message.reply(f"⏳ Пожалуйста подождите {seconds_left} сек.")
        return

    # Extract clean URL and ID
    match = SUPPORTED_LINK_REGEX.search(message.text)
    if not match:
        await message.reply("Не удалось распознать ссылку на Instagram в вашем сообщении.")
        return

    url = match.group(0)
    post_id = match.group(1)
    
    # Save rate limit timestamp
    rate_limit_db[user_id] = current_time

    status_msg = await message.reply("⏳ <b>Скачиваю файлы из Instagram, пожалуйста, подождите...</b>")

    try:
        # Download photos and videos
        media_files = await download_instagram_media(url, post_id)

        if not media_files:
            # Reset rate limit to let user try immediately with next correct URL
            rate_limit_db[user_id] = 0
            await status_msg.edit_text("❌ <b>Не удалось скачать медиа файлы.</b>\n\nПожалуйста, убедитесь, что профиль автора открытый (не приватный) и ссылка верна.")
            return

        # Delete waiting message
        await bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)

        # Send media group up to 10 files per album chunk (Telegram bulk message limit)
        for i in range(0, len(media_files), 10):
            chunk = media_files[i:i + 10]
            media_group = []

            for file_path, media_type in chunk:
                try:
                    if os.path.exists(file_path):
                        # Filter out file sizes to meet 50MB telegram limits safely
                        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
                        if file_size_mb > 49.5:
                            logger.warning(f"File {file_path} is too large ({file_size_mb:.2f} MB), skipping.")
                            continue

                        # Add FSInputFile
                        input_file = FSInputFile(file_path)
                        if media_type == 'video':
                            media_group.append(InputMediaVideo(media=input_file))
                        else:
                            media_group.append(InputMediaPhoto(media=input_file))
                except Exception as prep_err:
                    logger.warning(f"Failed to prepare asset {file_path}: {prep_err}")

            if media_group:
                # Attach caption to the first item of the album
                if hasattr(media_group[0], 'caption'):
                    media_group[0].caption = "✅ <b>Ваши файлы успешно скачаны!</b>\n\n🦾 Скачано с помощью @InstagramDownloaderBot"
                try:
                    await message.reply_media_group(media=media_group)
                except Exception as group_err:
                    logger.error(f"Error sending media group: {group_err}")
                    # If media group failed (e.g. timeout), try sending files individually
                    for file_path, media_type in chunk:
                        try:
                            if media_type == 'video':
                                await message.reply_video(video=FSInputFile(file_path))
                            else:
                                await message.reply_photo(photo=FSInputFile(file_path))
                        except Exception as single_err:
                            logger.error(f"Failed sending single element: {single_err}")

        logger.info(f"Successfully sent all Instagram media files ({len(media_files)}) to user {user_id}")

    except Exception as e:
        rate_limit_db[user_id] = 0
        logger.exception(f"Unexpected error in Instagram handler: {e}")
        try:
            await status_msg.edit_text("❌ Произошла ошибка во время скачивания. Пожалуйста, попробуйте другую ссылку.")
        except Exception:
            pass

    finally:
        # Secure cleanup under finally block to clear temporary disks
        for file_path, _ in media_files if 'media_files' in locals() and media_files else []:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Cleaned up temporary file: {file_path}")
                except Exception as cleanup_err:
                    logger.error(f"Failed to delete {file_path}: {cleanup_err}")


# Catchall handler for plain text
@dp.message(F.text)
async def handle_unknown_text(message: Message):
    if message.chat.type != "private":
        return
    await message.reply(
        "🧐 <b>Режим ожидания ссылки!</b>\n\n"
        "Отправьте мне сообщение, содержащее ссылку на Instagram Reel, видео-публикацию или фото-пост.\n\n"
        "Пример: <code>https://www.instagram.com/p/C8F.../</code>"
    )


# Start long polling
async def main():
    logger.info("Initializing Instagram post & media Downloader Bot...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot execution finished.")
