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
# Cập nhật cổng thành 8000 theo cấu hình của bạn
PORT = int(os.environ.get("PORT", 8000)) 
# Sử dụng biến môi trường để bảo mật Token
API_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")

# Khởi tạo Bot và Dispatcher
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- HÀM TRA CỨU VẬN ĐƠN (SPX) ---
async def get_tracking_info(tracking_number):
    # API tra cứu đơn hàng SPX
    url = f"https://spx.vn/api/v2/fleet_order/tracking_search?sls_tracking_number={tracking_number}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
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
            return "❌ Không tìm thấy thông tin hành trình cho mã này."
        except Exception as e:
            logger.error(f"Lỗi khi gọi API SPX: {e}")
            return "⚠️ Hệ thống vận chuyển đang bận, vui lòng thử lại sau."

# --- XỬ LÝ LỆNH TỪ TELEGRAM ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Lời chào cá nhân hóa cho Sơn
    await message.reply("Chào Sơn! Gửi mã vận đơn SPX vào đây, mình sẽ check trạng thái 24/7 giúp bạn.")

@dp.message()
async def handle_tracking(message: types.Message):
    if not message.text or len(message.text) < 5:
        return
    
    tracking_number = message.text.strip()
    # Tạo hiệu ứng "đang nhập" trên Telegram
    await bot.send_chat_action(message.chat.id, "typing")
    
    result = await get_tracking_info(tracking_number)
    await message.answer(result, parse_mode="Markdown")

# --- WEB SERVER ĐỂ VƯỢT QUA HEALTH CHECK CỦA CHOREO ---
async def handle_health_check(request):
    return web.Response(text="Bot is active and healthy!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    # Chạy trên 0.0.0.0 để Choreo có thể truy cập nội bộ
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web server đang lắng nghe tại cổng {PORT}")

# --- KHỞI CHẠY CHÍNH ---
async def main():
    logger.info("Đang khởi động bot...")
    # Chạy song song Web Server và Bot Polling
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot đã dừng!")
