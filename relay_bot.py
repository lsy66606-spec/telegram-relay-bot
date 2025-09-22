import logging
import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.helpers import escape_markdown
from flask import Flask, request

# --- 配置 ---
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

# --- 1. 初始化全局事件循环 + Telegram Application（关键：复用循环） ---
# 创建全局事件循环（避免被asyncio.run()关闭）
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# 初始化Telegram Application
application = Application.builder().token(BOT_TOKEN).build()
# 初始化并启动Application（使用全局循环）
loop.run_until_complete(application.initialize())
loop.run_until_complete(application.start())
logger.info("Telegram Application 初始化完成")

# --- 2. 消息处理函数（修复管理员回复的事件循环问题） ---
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
    
    # 构造并发送头部信息
    header = f"📩 收到来自用户 {escaped_name} \\(ID: `{escaped_user_id}`\\) 的新消息："
    try:
        header_msg = await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID, 
            text=header, 
            parse_mode='MarkdownV2'
        )
        # 转发原始消息
        forwarded = await context.bot.forward_message(
            chat_id=ADMIN_CHAT_ID,
            from_chat_id=update.message.chat_id,
            message_id=message_id
        )
        # 存储消息关联
        message_user_map[header_msg.message_id] = user_id
        message_user_map[forwarded.message_id] = user_id
        logger.info(f"消息转发成功（头部ID: {header_msg.message_id}，转发ID: {forwarded.message_id}）")
    except Exception as e:
        logger.error(f"用户消息转发失败: {str(e)}")
        await update.message.reply_text("消息转发失败，请稍后再试～")

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global message_user_map
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
        
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ 请先回复一条机器人转发的用户消息")
        return
        
    replied_message_id = update.message.reply_to_message.message_id
    original_user_id = message_user_map.get(replied_message_id)
    
    if not original_user_id:
        await update.message.reply_text("⚠️ 未找到对应的用户，请回复机器人转发的消息")
        return
        
    # 修复：使用全局事件循环执行回复（避免循环关闭）
    if update.message.text:
        try:
            # 直接用context.bot发送，复用Application的事件循环
            await context.bot.send_message(
                chat_id=original_user_id,
                text=f"{update.message.text}"
            )
            await update.message.reply_text("✅ 回复已成功发送给用户")
            logger.info(f"回复用户 {original_user_id} 成功")
        except Exception as e:
            error_msg = f"回复发送失败: {str(e)}"
            await update.message.reply_text(f"❌ {error_msg}")
            logger.error(error_msg)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"更新处理错误: {context.error}")

# --- 3. 添加处理器 ---
application.add_error_handler(error_handler)
application.add_handler(CommandHandler("start", start_command))
application.add_handler(MessageHandler(
    filters.TEXT & filters.REPLY & filters.User(user_id=ADMIN_CHAT_ID),
    handle_admin_reply
))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))

# --- 4. Flask Webhook视图（复用全局事件循环，不关闭） ---
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook_sync() -> str:
    try:
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, application.bot)
        # 关键修复：用全局loop执行异步处理，不使用asyncio.run()（避免关闭循环）
        loop.run_until_complete(application.process_update(update))
        return "ok"
    except Exception as e:
        logger.error(f"Webhook处理失败: {str(e)}")
        return "error", 500

# --- 5. 主函数：设置Webhook + 启动Flask ---
def main() -> None:
    # 设置Webhook（用全局循环）
    loop.run_until_complete(application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook"))
    logger.info(f"Webhook已设置为：{WEBHOOK_URL}/webhook")

    # 启动Flask服务（生产模式配置）
    app.run(
        host='0.0.0.0',
        port=PORT,
        use_reloader=False,  # 关闭自动重载，避免循环冲突
        debug=False          # 关闭调试，稳定运行
    )

if __name__ == "__main__":
    main()




