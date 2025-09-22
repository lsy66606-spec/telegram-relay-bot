import logging
import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.helpers import escape_markdown
from flask import Flask, request
# 新增：导入同步包装所需的函数
from asyncio import run as asyncio_run

# --- 配置（确保环境变量正确读取） ---
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('TELEGRAM_ADMIN_CHAT_ID')
PORT = int(os.getenv('PORT', 5000))
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

if not BOT_TOKEN or not ADMIN_CHAT_ID or not WEBHOOK_URL:
    print("错误：请设置 TELEGRAM_BOT_TOKEN、TELEGRAM_ADMIN_CHAT_ID、WEBHOOK_URL 环境变量！")
    exit(1)

try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
except ValueError:
    print("错误：TELEGRAM_ADMIN_CHAT_ID 必须是整数！")
    exit(1)

# --- 全局变量与日志 ---
message_user_map = {}
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 1. 先初始化Telegram Application（全局单例，避免重复创建） ---
application = Application.builder().token(BOT_TOKEN).build()

# --- 2. 消息处理函数（不变，复用原有逻辑） ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("你好！你可以直接在这里给我发送消息，我会将它转达给管理员。")

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global message_user_map
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    message_id = update.message.message_id

    if user_id == ADMIN_CHAT_ID:
        return

    logger.info(f"收到用户 {user_id} 的消息 (消息ID: {message_id})")
    escaped_name = escape_markdown(user_name, version=2)
    escaped_user_id = escape_markdown(str(user_id), version=2)
    
    header = f"📩 收到来自用户 {escaped_name} \\(ID: `{escaped_user_id}`\\) 的新消息："
    header_msg = await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID, 
        text=header, 
        parse_mode='MarkdownV2'
    )

    forwarded = await context.bot.forward_message(
        chat_id=ADMIN_CHAT_ID,
        from_chat_id=update.message.chat_id,
        message_id=message_id
    )
    
    message_user_map[header_msg.message_id] = user_id
    message_user_map[forwarded.message_id] = user_id

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global message_user_map
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
        
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ 请先回复一条消息")
        return
        
    replied_message_id = update.message.reply_to_message.message_id
    original_user_id = message_user_map.get(replied_message_id)
    
    if original_user_id:
        if update.message.text:
            try:
                await context.bot.send_message(
                    chat_id=original_user_id,
                    text=f"{update.message.text}"
                )
                await update.message.reply_text("✅ 回复已成功发送给用户。")
            except Exception as e:
                await update.message.reply_text(f"❌ 发送失败: {str(e)}")
    else:
        await update.message.reply_text("⚠️ 请直接 '回复' 由机器人转发的用户消息来进行沟通。")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"更新 {update} 导致错误 {context.error}")

# --- 3. 添加处理器到Telegram Application（全局初始化时绑定） ---
application.add_error_handler(error_handler)
application.add_handler(CommandHandler("start", start_command))
application.add_handler(MessageHandler(
    filters.TEXT & filters.REPLY & filters.User(user_id=ADMIN_CHAT_ID),
    handle_admin_reply
))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))

# --- 4. Flask同步视图（关键：用同步函数包装异步的Telegram逻辑） ---
app = Flask(__name__)

# 同步Webhook视图：内部调用异步的process_update
@app.route('/webhook', methods=['POST'])
def webhook_sync() -> str:
    try:
        # 1. 解析Telegram的POST请求数据
        update_data = request.get_json(force=True)
        # 2. 转换为Telegram的Update对象
        update = Update.de_json(update_data, application.bot)
        # 3. 用asyncio.run同步执行异步的process_update（核心修复）
        asyncio_run(application.process_update(update))
        return "ok"  # 必须返回"ok"给Telegram，避免重复推送
    except Exception as e:
        logger.error(f"Webhook处理失败: {str(e)}")
        return "error", 500

# --- 5. 主函数：先设置Webhook，再启动Flask同步服务 ---
def main() -> None:
    # 同步执行Webhook设置（避免异步循环冲突）
    loop = asyncio.get_event_loop()
    loop.run_until_complete(application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook"))
    logger.info(f"Webhook已设置为：{WEBHOOK_URL}/webhook")

    # 启动Flask同步服务（无async_mode参数，适配Flask 2.3.3）
    app.run(
        host='0.0.0.0',  # 必须是0.0.0.0，Render才能访问
        port=PORT,       # 读取Render分配的动态端口
        use_reloader=False,  # 关闭自动重载，避免重复启动
        debug=False          # 生产环境关闭调试模式
    )

if __name__ == "__main__":
    main()  # 直接启动同步主函数，无需asyncio.run
    



