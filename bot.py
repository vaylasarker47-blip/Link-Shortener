import os
import sys
import asyncio
import logging
import mimetypes
import requests
from urllib.parse import unquote, urlparse
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

# লগিং কনফিগারেশন
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 🔑 আপনার BotFather API Token এখানে বসান
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"

# টেলিগ্রাম বটে ফাইল আপলোডের সর্বোচ্চ সাইজ (50 MB Limit)
MAX_FILE_SIZE_MB = 50  
DOWNLOAD_DIR = "./bot_downloads"

# ডিরেক্টরি তৈরি
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# /start কমান্ড হ্যান্ডলার
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "⚡ **পাওয়ারফুল অল-ইন-ওয়ান ফাইল ডাউনলোডার বট**\n\n"
        "যেকোনো শর্ট লিঙ্ক বা ফাইল লিঙ্ক এখানে পাঠান।\n"
        "আমি লিঙ্ক বাইপাস করে সরাসরি **APK, Photo, Video, ZIP, PDF** ইত্যাদি ফাইল আপনাকে পাঠিয়ে দেব!"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

# ১. পাওয়ারফুল বাইপাস ও লিঙ্ক এক্সট্রাকশন ইঞ্জিন
async def bypass_engine(short_url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            accept_downloads=True,
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()
        await stealth_async(page)

        try:
            # পপ-আপ অ্যাড ট্যাব স্বয়ংক্রিয়ভাবে বন্ধ করা
            page.on("popup", lambda popup: asyncio.create_task(popup.close()))
            
            await page.goto(short_url, wait_until="domcontentloaded", timeout=60000)

            # রিডাইরেক্ট এবং ক্লিক অটোমেশন
            for _ in range(8):
                await asyncio.sleep(1)
                try:
                    for text in ["Continue", "Get Link", "Download", "Skip", "Proceed"]:
                        btn = page.locator(f"text={text}")
                        if await btn.is_visible():
                            await btn.click(timeout=1000)
                except:
                    pass

            final_url = page.url
            await browser.close()
            return final_url

        except Exception as e:
            await browser.close()
            raise Exception(f"Bypass Error: {str(e)}")

# ২. ফাইল প্রসেসিং এবং চ্যাটে সেন্ড করার লজিক
async def process_and_send_file(update: Update, direct_url: str, status_msg):
    download_path = None
    try:
        # হেড রিকোয়েস্ট পাঠ্যে ফাইলের তথ্য নেওয়া
        headers = {'User-Agent': 'Mozilla/5.0'}
        head_req = requests.head(direct_url, allow_redirects=True, headers=headers, timeout=15)
        content_type = head_req.headers.get('content-type', '').lower()
        content_length = head_req.headers.get('content-length')

        # নাম ও ফরম্যাট নির্ধারণ
        parsed_url = urlparse(direct_url)
        filename = os.path.basename(parsed_url.path)
        filename = unquote(filename) if filename else "downloaded_file"

        if '.' not in filename:
            ext = mimetypes.guess_extension(content_type)
            if ext:
                filename += ext
            elif 'android' in content_type:
                filename += '.apk'

        # সাইজ লিমিট ৫০MB চেক
        if content_length:
            file_size_mb = int(content_length) / (1024 * 1024)
            if file_size_mb > MAX_FILE_SIZE_MB:
                await status_msg.edit_text(
                    f"✅ **বাইপাস সফল!**\n\n"
                    f"📁 **ফাইল:** `{filename}`\n"
                    f"📦 **সাইজ:** {file_size_mb:.1f} MB\n\n"
                    f"⚠️ ফাইলটি ৫০ মেগাবাইটের বেশি বড় হওয়ায় সরাসরি টেলিগ্রাম বটে আপলোড করা সম্ভব নয় (Bot API Limit)।\n\n"
                    f"🔗 **ডিরেক্ট ডাউনলোড লিঙ্ক:**\n{direct_url}",
                    parse_mode="Markdown"
                )
                return

        await status_msg.edit_text(f"📥 ফাইল প্রসেসিং ও ডাউনলোড হচ্ছে: `{filename}`...", parse_mode="Markdown")

        # ফাইল লোকালি সেভ করা
        download_path = os.path.join(DOWNLOAD_DIR, filename)
        with requests.get(direct_url, stream=True, headers=headers, timeout=120) as r:
            r.raise_for_status()
            with open(download_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=16384):
                    f.write(chunk)

        await status_msg.edit_text("📤 ফাইলটি টেলিগ্রাম চ্যাটে আপলোড করা হচ্ছে...")

        # ফাইল টাইপ অনুযায়ী চ্যাটে সেন্ড
        with open(download_path, 'rb') as file_data:
            if content_type.startswith('image/') and not filename.endswith('.gif'):
                await update.message.reply_photo(photo=file_data, caption=f"🖼 **ছবি:** `{filename}`", parse_mode="Markdown")
            elif content_type.startswith('video/'):
                await update.message.reply_video(video=file_data, caption=f"🎥 **ভিডিও:** `{filename}`", parse_mode="Markdown")
            elif content_type.startswith('audio/'):
                await update.message.reply_audio(audio=file_data, caption=f"🎵 **গান/অডিও:** `{filename}`", parse_mode="Markdown")
            else:
                # APK, ZIP, RAR, PDF এবং সকল ফাইল ডকুমেন্ট মোডে সেন্ড হবে
                await update.message.reply_document(
                    document=file_data,
                    filename=filename,
                    caption=f"📦 **আপনার ফাইল:** `{filename}`",
                    parse_mode="Markdown"
                )

        await status_msg.delete()

    except Exception as e:
        logger.error(f"Error in sending file: {e}")
        await status_msg.edit_text(
            f"✅ **বাইপাস সফল!**\n\n"
            f"🔗 **ডিরেক্ট মেইন লিঙ্ক:**\n{direct_url}"
        )

    finally:
        # কাজ শেষে সাথে সাথে সার্ভারের মেমোরি খালি করে ফাইল ডিলিট করা
        if download_path and os.path.exists(download_path):
            try:
                os.remove(download_path)
            except Exception:
                pass

# ৩. মূল লিঙ্ক রিসিভার
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_url = update.message.text.strip()

    if not user_url.startswith(("http://", "https://")):
        await update.message.reply_text("❌ অনুগ্রহ করে সঠিক HTTP/HTTPS ইউআরএল পাঠাও।")
        return

    status_msg = await update.message.reply_text("🚀 বাইপাস ইঞ্জিন চালু হচ্ছে, অপেক্ষা করুন...")

    try:
        direct_url = await bypass_engine(user_url)
        await process_and_send_file(update, direct_url, status_msg)
    except Exception as e:
        await status_msg.edit_text(f"❌ বাইপাস করা সম্ভব হয়নি।\n\nকারণ: `{str(e)}`", parse_mode="Markdown")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 ১০০% পাওয়ারফুল ফাইল বাইপাস বট চালু হয়েছে...")
    app.run_polling()

if __name__ == '__main__':
    main()
