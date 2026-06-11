import os
import re
import time
import asyncio
import logging
import tempfile
from typing import Dict, Optional
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import yt_dlp

# Загружаем .env только если файл существует (для локального запуска)
if os.path.exists(".env"):
    load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    logger.error("BOT_TOKEN is not defined!")
    raise ValueError("BOT_TOKEN must be set either in .env file or as environment variable.")

DOWNLOADS_DIR = os.path.join(tempfile.gettempdir(), "instabot_downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

rate_limit_db: Dict[int, float] = {}
RATE_LIMIT_SECONDS = 15

INSTAGRAM_LINK_REGEX = re.compile(
    r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/([a-zA-Z0-9_-]+)',
    re.IGNORECASE
)
INSTAGRAM_STORY_REGEX = re.compile(
    r'https?://(?:www\.)?instagram\.com/stories/([a-zA-Z0-9\._-]+)',
    re.IGNORECASE
)

def run_yt_dlp(url: str, output_template: str) -> Optional[str]:
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 48 * 1024 * 1024,
        'nocheckcertificate': True,
        'socket_timeout': 30,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
        }
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            if info_dict is None:
                return None
            filename = ydl.prepare_filename(info_dict)
            if os.path.exists(filename):
                return filename
            base_name, _ = os.path.splitext(filename)
            for ext in ['.mp4', '.mkv', '.webm', '.3gp']:
                possible_file = base_name + ext
                if os.path.exists(possible_file):
                    return possible_file
            return None
    except yt_dlp.utils.DownloadError as de:
        if "File is larger than max-filesize" in str(de):
            raise ValueError("FILE_TOO_LARGE")
        return None
    except Exception as e:
        logger.exception(f"yt-dlp error: {e}")
        return None

async def download_instagram_video(url: str, matched_id: str) -> str:
    output_tmpl = os.path.join(DOWNLOADS_DIR, f"{matched_id}_%(ext)s")
    loop = asyncio.get_running_loop()
    filepath = await loop.run_in_executor(None, run_yt_dlp, url, output_tmpl)
    if not filepath:
        raise RuntimeError("Download failed")
    return filepath

@dp.message(Command("start"))
async def cmd_start(message: Message):
    welcome_text = "Ты пидрюга ебанный. Готовь свой задок, сейчас буду заливать в тебя свою сперму"
    await message.reply(welcome_text)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "Не еби мозги\n"
        "Просто отправьте текстовое сообщение со ссылкой на пост или Reel из Instagram. "
        "Бот сам найдет ссылку и начнет загрузку."
    )
    await message.reply(help_text)

@dp.message(F.text.regexp(INSTAGRAM_STORY_REGEX))
async def handle_stories_link(message: Message):
    await message.reply("Я твою маму ебал")

@dp.message(lambda msg: msg.text and INSTAGRAM_LINK_REGEX.search(msg.text))
async def handle_instagram_download(message: Message):
    user_id = message.from_user.id
    current_time = time.time()

    last_use = rate_limit_db.get(user_id, 0)
    if current_time - last_use < RATE_LIMIT_SECONDS:
        seconds_left = int(RATE_LIMIT_SECONDS - (current_time - last_use))
        await message.reply(f"⏳ Пожалуйста, подождите!\nВы сможете скачать следующее видео через {seconds_left} сек.")
        return

    match = INSTAGRAM_LINK_REGEX.search(message.text)
    if not match:
        await message.reply("Не удалось распознать ссылку на Instagram.")
        return

    url = match.group(0)
    matched_id = match.group(1)
    rate_limit_db[user_id] = current_time

    status_msg = await message.reply("⏳ <b>Скачиваю видео из Instagram, пожалуйста, подождите...</b>")

    downloaded_filepath = None
    try:
        downloaded_filepath = await download_instagram_video(url, matched_id)

        if not downloaded_filepath or not os.path.exists(downloaded_filepath):
            raise RuntimeError("Downloaded file not found")

        file_size_mb = os.path.getsize(downloaded_filepath) / (1024 * 1024)
        if file_size_mb > 49.5:
            raise ValueError("FILE_TOO_LARGE")

        video_input = FSInputFile(downloaded_filepath)
        await bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
        await message.reply_video(
            video=video_input,
            caption="<b>Сперма в ваш зад успешно залита!</b>\n\n🦾 Скачано с помощью @kachatel_spermi_bot",
            supports_streaming=True
        )

    except ValueError as ve:
        if str(ve) == "FILE_TOO_LARGE":
            await status_msg.edit_text("<b>Ошибка: Слишком дохуя спермы!</b>")
        else:
            await status_msg.edit_text("<b>Произошла ошибка при обработке хуя.</b>")
    except Exception as e:
        logger.exception(f"Error: {e}")
        await status_msg.edit_text(
            "<b>Не удалось залить сперму.</b>\n\n"
            "Возможные причины:\n"
            "• Профиль автора закрыт или является приватным.\n"
            "• Ссылка устарела.\n"
            "Пожалуйста, убедитесь, что автор достал свой хуй и попробуйте позже."
        )
    finally:
        if downloaded_filepath and os.path.exists(downloaded_filepath):
            try:
                os.remove(downloaded_filepath)
            except:
                pass

@dp.message(F.text)
async def handle_unknown_text(message: Message):
    if message.chat.type != "private":
        return
    await message.reply(
        "<b>Режим ожидания спермы!</b>\n\n"
        "Чтобы залить сперму, отправьте прямую ссылку на Reel или пост из Instagram.\n"
        "Например: <code>https://www.instagram.com/reel/C8F.../</code>"
    )

async def main():
    logger.info("Starting Telegram Bot long polling setup...")
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
        logger.info("Bot stopped.")
    finally:
        print("=== Бот завершил работу ===")
        input("Нажми Enter, чтобы закрыть окно...")
