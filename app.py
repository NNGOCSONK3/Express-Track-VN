import logging
import os
import asyncio
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

# --- CẤU HÌNH ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 8000))
API_TOKEN = os.environ.get("TELEGRAM_TOKEN")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Biến lưu trữ tạm thời (Sẽ mất khi bot restart trên Choreo)
# Cấu trúc: { "tracking_number": {"status": "Đang giao", "chat_id": 12345} }
monitored_orders = {}

# --- HÀM TRA CỨU API SPX ---
async def get_tracking_info(tracking_number):
    url = "https://spx.vn/shipment/order/open/order/get_order_info"
    params = {"spx_tn": tracking_number, "language_code": "vi"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest"
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(url, params=params, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if data.get("retcode") == 0 and "data" in data:
                    order_info = data["data"]
                    nodes = order_info.get("nodes", [])
                    status_desc = nodes[0].get("description", "Không rõ") if nodes else "Chưa có hành trình"
                    return {"status": status_desc, "full_info": order_info}
            return None
        except Exception as e:
            logger.error(f"Lỗi API: {e}")
            return None

# --- VÒNG LẶP KIỂM TRA TỰ ĐỘNG (BACKGROUND TASK) ---
async def auto_check_orders():
    while True:
        logger.info(f"Đang kiểm tra {len(monitored_orders)} đơn hàng đang theo dõi...")
        for tn, info in list(monitored_orders.items()):
            current_data = await get_tracking_info(tn)
            if current_data:
                new_status = current_data["status"]
                # Nếu trạng thái thay đổi so với lần lưu cuối cùng
                if new_status != info["status"]:
                    msg = (f"🔔 **THÔNG BÁO THAY ĐỔI ĐƠN HÀNG!**\n\n"
                           f"📦 Mã đơn: `{tn}`\n"
                           f"🔄 Trạng thái cũ: {info['status']}\n"
                           f"✅ Trạng thái mới: {new_status}")
                    try:
                        await bot.send_message(info["chat_id"], msg, parse_mode="Markdown")
                        # Cập nhật trạng thái mới vào bộ nhớ
                        monitored_orders[tn]["status"] = new_status
                    except Exception as e:
                        logger.error(f"Không thể gửi tin nhắn cho {info['chat_id']}: {e}")
        
        # Đợi 10 phút (600 giây) rồi kiểm tra lại
        await asyncio.sleep(600)

# --- XỬ LÝ TIN NHẮN TELEGRAM ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.reply("Chào Sơn! Gửi mã SPX để tra cứu hoặc theo dõi tự động.")

@dp.message()
async def handle_message(message: types.Message):
    tn = message.text.strip()
    if len(tn) < 5: return

    await bot.send_chat_action(message.chat.id, "typing")
    data = await get_tracking_info(tn)
    
    if data:
        status = data["status"]
        # Tạo nút bấm Bật/Tắt theo dõi
        builder = InlineKeyboardBuilder()
        if tn in monitored_orders:
            builder.button(text="❌ Dừng theo dõi", callback_data=f"unwatch_{tn}")
        else:
            builder.button(text="🔔 Bật thông báo tự động", callback_data=f"watch_{tn}")
        
        await message.answer(
            f"📦 **Mã đơn:** `{tn}`\n📍 **Hiện tại:** {status}",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ Không tìm thấy thông tin đơn hàng.")

# --- XỬ LÝ NÚT BẤM (CALLBACK QUERY) ---
@dp.callback_query(F.data.startswith("watch_"))
async def watch_order(callback: types.CallbackQuery):
    tn = callback.data.split("_")[1]
    data = await get_tracking_info(tn)
    if data:
        monitored_orders[tn] = {"status": data["status"], "chat_id": callback.message.chat.id}
        await callback.answer("Đã bật thông báo tự động!")
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(f"✅ Đang theo dõi đơn `{tn}`. Mình sẽ báo khi có thay đổi!")

@dp.callback_query(F.data.startswith("unwatch_"))
async def unwatch_order(callback: types.CallbackQuery):
    tn = callback.data.split("_")[1]
    if tn in monitored_orders:
        del monitored_orders[tn]
        await callback.answer("Đã tắt theo dõi.")
        await callback.message.answer(f"➖ Đã dừng cập nhật cho đơn `{tn}`.")

# --- WEB SERVER & MAIN ---
async def handle_health(request): return web.Response(text="Bot is running")

async def main():
    app = web.Application()
    app.router.add_get("/", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    
    await asyncio.gather(
        site.start(),
        dp.start_polling(bot),
        auto_check_orders() # Chạy tác vụ kiểm tra ngầm
    )

if __name__ == "__main__":
    asyncio.run(main())
