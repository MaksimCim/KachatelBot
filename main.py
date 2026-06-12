import os
import re
import time
import asyncio
import logging
import tempfile
import shutil
from typing import Dict, Optional

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import yt_dlp

# Load environment variables
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
RATE_LIMIT_SECONDS = 15

# Regular expressions for detecting Instagram URLs
INSTAGRAM_LINK_REGEX = re.compile(
    r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/([a-zA-Z0-9_-]+)',
    re.IGNORECASE
)
INSTAGRAM_STORY_REGEX = re.compile(
    r'https?://(?:www\.)?instagram\.com/stories/([a-zA-Z0-9\._-]+)',
    re.IGNORECASE
)

def run_yt_dlp(url: str, output_template: str) -> Optional[str]:
    """
    Synchronous function to run yt-dlp and download the video.
    Returns the absolute path of the downloaded file, or None if failed.
    """
    ydl_opts = {
        # Select best mp4 or default best back-up format
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        # Restrict download to 48MB so file fits nicely under Telegram's 50MB bot upload limit
        'max_filesize': 48 * 1024 * 1024,
        'nocheckcertificate': True,
        'socket_timeout': 30,
        # Emulate a real mobile client to minimize chance of being challenged
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            if info_dict is None:
                return None
            
            # Retrieve the file path of the downloaded file
            filename = ydl.prepare_filename(info_dict)
            
            # If the format was joined or converted, standard extension might change (e.g. from .mkv to .mp4)
            # Verify if file exists, or locate files starting with the same ID in the directory
            if os.path.exists(filename):
                return filename
            
            # Backup check if name changed slightly due to post-processing:
            base_name, _ = os.path.splitext(filename)
            for ext in ['.mp4', '.mkv', '.webm', '.3gp']:
                possible_file = base_name + ext
                if os.path.exists(possible_file):
                    return possible_file
                    
            return None
    except yt_dlp.utils.MaxDownloadsReached:
        logger.error("yt-dlp: Max downloads reached.")
        return None
    except yt_dlp.utils.DownloadError as de:
        logger.error(f"yt-dlp Download Error for URL {url}: {de}")
        # Check if the file is too big (yt-dlp raises error if max_filesize exceeded)
        if "File is larger than max-filesize" in str(de):
            raise ValueError("FILE_TOO_LARGE")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error running yt-dlp: {e}")
        return None

async def download_instagram_video(url: str, matched_id: str) -> str:
    """
    Asynchronous wrapper to download Instagram video securely in an executor.
    """
    output_tmpl = os.path.join(DOWNLOADS_DIR, f"{matched_id}_%(ext)s")
    
    # Run the synchronous yt-dlp in a thread pool to avoid blocking aiogram's event loop
    loop = asyncio.get_running_loop()
    filepath = await loop.run_in_executor(None, run_yt_dlp, url, output_tmpl)
    
    if not filepath:
        raise RuntimeError("Download failed")
        
    return filepath

# Handler for /start command
@dp.message(Command("start"))
async def cmd_start(message: Message):
    welcome_text = (
        "👋 <b>Привет! Я бот для скачивания Instagram REELS и Видео.</b>\n\n"
        "Отправьте мне любое сообщение, содержащее ссылку на Instagram <code>/reel/</code>, "
        "<code>/p/</code> (видео-пост) или <code>/tv/</code>, и я пришлю вам медиафайл!\n\n"
        "✨ <b> Особенности бота:</b>\n"
        "• Полностью автоматическое распознавание ссылок в тексте.\n"
        "• Высокое качество скачиваемых видео.\n"
        "• Ограничение на запросы: 1 скачивание в 15 секунд для стабильности.\n\n"
        "👉 Просто отправьте или перешлите мне ссылку!"
    )
    await message.reply(welcome_text)

# Handler for /help command
@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "🤖 <b>Справка по использованию бота</b>\n\n"
        "<b>Как скачивать видео:</b>\n"
        "Просто отправьте текстовое сообщение со ссылкой на пост или Reel из Instagram. Бот сам найдет ссылку и начнет загрузку.\n\n"
        "⚠️ <b>Ограничения:</b>\n"
        "1. <b>Лимит частоты:</b> Запускать скачивание можно раз в 15 секунд.\n"
        "2. <b>Размер файла:</b> Telegram-боты имеют жесткий лимит на отправку файлов до 50 МБ. Слишком длинные видео не скачаются.\n"
        "3. <b>Поддержка Stories:</b> Скачивание историй (Stories) не поддерживается напрямую, так как они требуют активную сессию (куки) вашего Instagram-аккаунта."
    )
    await message.reply(help_text)

# Handler for non-supported Instagram Stories
@dp.message(F.text.regexp(INSTAGRAM_STORY_REGEX))
async def handle_stories_link(message: Message):
    story_warning = (
        "💡 <b>Скачивание Историй (Stories) временно не поддерживается.</b>\n\n"
        "Для безопасного скачивания приватных историй требуются файлы cookie авторизованного аккаунта. "
        "По соображениям безопасности ваших аккаунтов мы поддерживаем загрузку только из открытых "
        "источников: обычных публикаций (posts) и рилсов (reels)."
    )
    await message.reply(story_warning)

# Main handler for Instagram post, reel, and IGTV links
@dp.message(lambda msg: msg.text and INSTAGRAM_LINK_REGEX.search(msg.text))
async def handle_instagram_download(message: Message):
    user_id = message.from_user.id
    current_time = time.time()
    
    # 1. Rate Limit Check
    last_use = rate_limit_db.get(user_id, 0)
    time_passed = current_time - last_use
    if time_passed < RATE_LIMIT_SECONDS:
        seconds_left = int(RATE_LIMIT_SECONDS - time_passed)
        await message.reply(
            f"⏳ Пожалуйста, подождите!\n"
            f"Вы сможете скачать следующее видео через {seconds_left} сек."
        )
        return

    # Extract clean URL and matched ID
    match = INSTAGRAM_LINK_REGEX.search(message.text)
    if not match:
        await message.reply("Не удалось распознать ссылку на Instagram в вашем сообщении. Пожалуйста, отправьте корректную ссылку.")
        return

    url = match.group(0)
    matched_id = match.group(1)
    
    # Update rate limit database immediately to prevent rapid successive double-handling
    rate_limit_db[user_id] = current_time
    
    # 2. Show progress message
    status_msg = await message.reply("⏳ <b>Скачиваю видео из Instagram, пожалуйста, подождите...</b>")
    
    # 3. Download the video and send it back
    downloaded_filepath = None
    try:
        downloaded_filepath = await download_instagram_video(url, matched_id)
        
        # Check if downloaded file is actually present and non-empty
        if not downloaded_filepath or not os.path.exists(downloaded_filepath):
            raise RuntimeError("Downloaded file not found on disk")
            
        file_size_mb = os.path.getsize(downloaded_filepath) / (1024 * 1024)
        if file_size_mb > 49.5: # Margin below 50MB
            raise ValueError("FILE_TOO_LARGE")

        # Send file using FSInputFile
        video_input = FSInputFile(downloaded_filepath)
        
        # Remove the progress/waiting message and send video
        await bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
        await message.reply_video(
            video=video_input,
            caption="✅ <b>Ваше видео успешно скачано!</b>\n\n🦾 Скачано с помощью @InstagramDownloaderBot",
            supports_streaming=True
        )
        logger.info(f"Successfully processed and sent Instagram reel/post {matched_id} to user {user_id}")
        
    except ValueError as ve:
        # Check for specific expected limits
        if str(ve) == "FILE_TOO_LARGE":
            await status_msg.edit_text(
                "❌ <b>Ошибка: Видео слишком большое!</b>\n\n"
                "Размер скачанного файла превышает лимит отправки для ботов (50 МБ). "
                "К сожалению, отправить его через Telegram невозможно."
            )
        else:
            await status_msg.edit_text(
                "❌ <b>Произошла ошибка при обработке видео.</b>\n"
                "Пожалуйста, попробуйте еще раз с другим видео."
            )
        logger.warning(f"File size limitation hit for URL {url}: {ve}")
        
    except Exception as e:
        logger.exception(f"Error handling download for URL {url}: {e}")
        await status_msg.edit_text(
            "❌ <b>Не удалось скачать видео.</b>\n\n"
            "Возможные причины:\n"
            "• Профиль автора закрыт или является приватным.\n"
            "• Ссылка устарела или верификация заблокировала запрос.\n"
            "• Временный сбой серверов Instagram.\n\n"
            "Пожалуйста, убедитесь, что аккаунт автора публичный, и попробуйте позже."
        )
        
    finally:
        # Clean up temporary files synchronously
        if downloaded_filepath and os.path.exists(downloaded_filepath):
            try:
                os.remove(downloaded_filepath)
                logger.info(f"Cleaned up temporary file: {downloaded_filepath}")
            except Exception as e:
                logger.error(f"Failed to remove temporary file {downloaded_filepath}: {e}")

# Catchall handler for other text messages to provide assistance
@dp.message(F.text)
async def handle_unknown_text(message: Message):
    # Simply ignore if the message is from a group chat and does not mention/reply to bot to avoid spamming
    if message.chat.type != "private":
        return
        
    await message.reply(
        "🧐 <b>Режим ожидания ссылки!</b>\n\n"
        "Вы просто написали мне текст. Чтобы скачать видео, отправьте сообщение, "
        "содержащее прямую ссылку на Instagram Reel или публикацию.\n\n"
        "Например: <code>https://www.instagram.com/reel/C8F.../</code>"
    )

# Start long polling
async def main():
    logger.info("Starting Telegram Bot long polling setup...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped successfully.")
