import logging
import os
import asyncio
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 8000))
API_TOKEN = os.environ.get("TELEGRAM_TOKEN")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
monitored_orders = {}

async def get_tracking_info(tracking_number):
    url = "https://spx.vn/shipment/order/open/order/get_order_info"
    params = {"spx_tn": tracking_number, "language_code": "vi"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...",
        "X-Requested-With": "XMLHttpRequest"
    }

    # SỬA LỖI PROXY Ở ĐÂY
    proxy_url = os.environ.get("PROXY_URL")
    
    # Khởi tạo client đúng cách cho httpx mới
    client_kwargs = {
        "timeout": 20.0,
        "follow_redirects": True,
        "headers": headers
    }
    if proxy_url:
        client_kwargs["proxy"] = proxy_url # Dùng 'proxy' thay vì 'proxies'

    async with httpx.AsyncClient(**client_kwargs) as client:
        try:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                if data.get("retcode") == 0 and "data" in data:
                    order = data["data"]
                    nodes = order.get("nodes", [])
                    latest = nodes[0] if nodes else {}
                    status_text = f"📦 **Đơn hàng:** `{tracking_number}`\n📍 **Trạng thái:** {order.get('status_description')}\n🕒 **Mới nhất:** {latest.get('description')}"
                    return {"status_text": status_text, "current_desc": latest.get('description')}
            return {"status_text": "❌ Không tìm thấy mã đơn."}
        except Exception as e:
            logger.error(f"Lỗi kết nối: {e}")
            return {"status_text": "⚠️ Lỗi kết nối hệ thống vận chuyển."}

# --- TÁC VỤ KIỂM TRA TỰ ĐỘNG ---
async def auto_check_loop():
    while True:
        for tn, info in list(monitored_orders.items()):
            res = await get_tracking_info(tn)
            if res and res.get("current_desc") != info["last_desc"]:
                await bot.send_message(info["chat_id"], f"🔔 **CẬP NHẬT!**\n\n{res['status_text']}", parse_mode="Markdown")
                monitored_orders[tn]["last_desc"] = res["current_desc"]
        await asyncio.sleep(900)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Chào Sơn! Gửi mã SPX để mình theo dõi giúp bạn.")

@dp.message()
async def handle_msg(message: types.Message):
    tn = message.text.strip()
    if len(tn) < 5: return
    res = await get_tracking_info(tn)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔔 Bật thông báo" if tn not in monitored_orders else "❌ Tắt thông báo", 
                   callback_data=f"{'watch' if tn not in monitored_orders else 'unwatch'}_{tn}")
    await message.answer(res["status_text"], reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("watch_"))
async def watch(cb: types.CallbackQuery):
    tn = cb.data.split("_")[1]
    res = await get_tracking_info(tn)
    monitored_orders[tn] = {"last_desc": res.get("current_desc"), "chat_id": cb.message.chat.id}
    await cb.answer("Đã bật theo dõi!")

async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Running"))
    runner = web.AppRunner(app)
    await runner.setup()
    await asyncio.gather(web.TCPSite(runner, "0.0.0.0", PORT).start(), dp.start_polling(bot), auto_check_loop())

if __name__ == "__main__":
    asyncio.run(main())
