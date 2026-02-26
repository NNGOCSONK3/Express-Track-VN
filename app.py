import logging
import os
import asyncio
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

# --- CẤU HÌNH HỆ THỐNG ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cấu hình cổng và Token từ biến môi trường
PORT = int(os.environ.get("PORT", 8000))
API_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Kiểm tra Token để tránh lỗi Unauthorized (Lỗi Sơn đã gặp trong log)
if not API_TOKEN:
    logger.error("CHƯA CẤU HÌNH TELEGRAM_TOKEN! Bot sẽ không thể hoạt động.")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Biến tạm lưu đơn hàng (Sẽ mất khi server restart trên Choreo)
monitored_orders = {}

# --- HÀM TRA CỨU VẬN ĐƠN SPX (TỐI ƯU HÓA) ---
async def get_tracking_info(tracking_number):
    # Sử dụng Endpoint chính xác Sơn đã tìm thấy
    url = "https://spx.vn/shipment/order/open/order/get_order_info"
    params = {"spx_tn": tracking_number, "language_code": "vi"}
    
    # Giả lập trình duyệt tối đa để tránh bị chặn
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": f"https://spx.vn/shipment/order/open/order/get_order_info?spx_tn={tracking_number}&language_code=vi",
        "X-Requested-With": "XMLHttpRequest"
    }

    # CẤU HÌNH PROXY (Nếu chạy trên Choreo/Hugging Face mà bị chặn IP)
    # Thay bằng: "http://user:pass@ip:port" nếu bạn có Proxy
    proxy_url = os.environ.get("PROXY_URL", None)
    proxies = {"all://": proxy_url} if proxy_url else None

    async with httpx.AsyncClient(proxies=proxies, timeout=20.0, follow_redirects=True) as client:
        try:
            response = await client.get(url, params=params, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("retcode") == 0 and "data" in data:
                    order = data["data"]
                    nodes = order.get("nodes", [])
                    latest_node = nodes[0] if nodes else {}
                    
                    status_title = order.get("status_description", "Không rõ")
                    last_update = latest_node.get("description", "Chưa có hành trình")
                    update_time = latest_node.get("ctime", "N/A")
                    
                    return {
                        "status_text": f"📦 **Đơn hàng:** `{tracking_number}`\n📍 **Trạng thái:** {status_title}\n🕒 **Cập nhật mới nhất:** {last_update}\n⏰ **Thời gian:** {update_time}",
                        "current_desc": last_update
                    }
                return {"status_text": "❌ Không tìm thấy mã vận đơn này."}
            
            elif response.status_code == 403:
                return {"status_text": "🚫 Lỗi 403: IP của server bị SPX chặn. Sơn hãy thử dùng Proxy Việt Nam."}
            
            return {"status_text": f"⚠️ Lỗi hệ thống SPX (Mã lỗi: {response.status_code})"}
            
        except Exception as e:
            logger.error(f"Lỗi kết nối: {e}")
            return {"status_text": "⚠️ Không thể kết nối với hệ thống SPX lúc này."}

# --- TÁC VỤ KIỂM TRA TỰ ĐỘNG (BACKGROUND TASK) ---
async def auto_check_loop():
    while True:
        if monitored_orders:
            logger.info(f"Đang kiểm tra tự động {len(monitored_orders)} đơn hàng...")
            for tn, info in list(monitored_orders.items()):
                res = await get_tracking_info(tn)
                # Nếu có thay đổi ở phần description (mô tả hành trình mới nhất)
                if res and "current_desc" in res and res["current_desc"] != info["last_desc"]:
                    msg = f"🔔 **CẬP NHẬT MỚI!**\n\n{res['status_text']}"
                    try:
                        await bot.send_message(info["chat_id"], msg, parse_mode="Markdown")
                        monitored_orders[tn]["last_desc"] = res["current_desc"]
                    except Exception as e:
                        logger.error(f"Lỗi gửi tin nhắn cho {info['chat_id']}: {e}")
        
        # Kiểm tra mỗi 15 phút (900 giây) để tránh bị khóa IP
        await asyncio.sleep(900)

# --- XỬ LÝ LỆNH TELEGRAM ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Chào Sơn! Gửi mã vận đơn SPX để mình theo dõi giúp bạn nhé.")

@dp.message()
async def handle_msg(message: types.Message):
    tn = message.text.strip()
    if len(tn) < 5: return

    await bot.send_chat_action(message.chat.id, "typing")
    res = await get_tracking_info(tn)
    
    builder = InlineKeyboardBuilder()
    if tn in monitored_orders:
        builder.button(text="❌ Dừng theo dõi", callback_data=f"unwatch_{tn}")
    else:
        builder.button(text="🔔 Bật thông báo tự động", callback_data=f"watch_{tn}")

    await message.answer(res["status_text"], reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("watch_"))
async def watch_callback(callback: types.CallbackQuery):
    tn = callback.data.split("_")[1]
    res = await get_tracking_info(tn)
    if "current_desc" in res:
        monitored_orders[tn] = {"last_desc": res["current_desc"], "chat_id": callback.message.chat.id}
        await callback.answer("Đã bật thông báo!")
        await callback.message.answer(f"✅ Mình sẽ báo cho Sơn ngay khi đơn `{tn}` có cập nhật mới!")

@dp.callback_query(F.data.startswith("unwatch_"))
async def unwatch_callback(callback: types.CallbackQuery):
    tn = callback.data.split("_")[1]
    if tn in monitored_orders:
        del monitored_orders[tn]
    await callback.answer("Đã tắt theo dõi.")
    await callback.message.answer(f"➖ Đã dừng cập nhật cho đơn `{tn}`.")

# --- WEB SERVER CHO HEALTH CHECK ---
async def health_check(request):
    return web.Response(text="Bot is running!")

async def main():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    
    logger.info(f"Khởi động hệ thống tại cổng {PORT}...")
    await asyncio.gather(
        site.start(),
        dp.start_polling(bot),
        auto_check_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())
