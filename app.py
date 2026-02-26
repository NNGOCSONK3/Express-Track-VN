import logging
import os
import asyncio
import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiohttp import web

# --- CẤU HÌNH LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CẤU HÌNH BIẾN ---
# Choreo thường cấp cổng qua biến môi trường PORT, mặc định là 8080
PORT = int(os.environ.get("PORT", 8080))
API_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")

# Khởi tạo Bot và Dispatcher
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- HÀM TRA CỨU VẬN ĐƠN (SPX) ---
async def get_tracking_info(tracking_number):
    url = f"https://spx.vn/api/v2/fleet_order/tracking_search?sls_tracking_number={tracking_number}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, headers=headers)
            data = response.json()
            if data.get("error") == 0 and "data" in data:
                tracking_list = data["data"].get("tracking_list", [])
                if tracking_list:
                    latest = tracking_list[0]
                    return (f"📦 **Mã đơn:** `{tracking_number}`\n"
                            f"📍 **Trạng thái:** {latest['status_description']}\n"
                            f"⏰ **Thời gian:** {latest['ctime']}")
            return "❌ Không tìm thấy thông tin cho mã này."
        except Exception as e:
            logger.error(f"Lỗi tra cứu: {e}")
            return "⚠️ Không thể kết nối với hệ thống vận chuyển."

# --- XỬ LÝ TELEGRAM MESSAGES ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.reply("Chào Sơn! Gửi mã vận đơn SPX để mình tra cứu 24/7 giúp bạn nhé.")

@dp.message()
async def handle_tracking(message: types.Message):
    if not message.text:
        return
    
    tracking_number = message.text.strip()
    await bot.send_chat_action(message.chat.id, "typing")
    
    result = await get_tracking_info(tracking_number)
    await message.answer(result, parse_mode="Markdown")

# --- WEB SERVER ĐỂ GIỮ CHOREO ALIVE ---
async def handle_health_check(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web server started on port {PORT}")

# --- MAIN RUNNER ---
async def main():
    # Chạy Web Server và Bot Polling song song
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")
