import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.helpers import escape_markdown
# 新增：导入Flask（用于创建HTTP服务，Render支持）
from flask import Flask, request

# --- 核心配置（新增+修改） ---
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('TELEGRAM_ADMIN_CHAT_ID')
# 1. 读取Render分配的动态端口（必须）
PORT = int(os.getenv('PORT', 5000))
# 2. 配置Webhook URL（需替换为你的Render服务域名，格式：https://xxx.onrender.com）
WEBHOOK_URL = os.getenv('WEBHOOK_URL')  # 后续在Render设为环境变量

if not BOT_TOKEN or not ADMIN_CHAT_ID or not WEBHOOK_URL:
    print("错误：请设置 TELEGRAM_BOT_TOKEN、TELEGRAM_ADMIN_CHAT_ID、WEBHOOK_URL 环境变量！")
    exit(1)

try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
except ValueError:
    print("错误：TELEGRAM_ADMIN_CHAT_ID 必须是整数！")
    exit(1)

# --- 全局变量与日志（不变） ---
message_user_map = {}
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 命令/消息处理函数（完全不变） ---
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
    logger.info(f"已转发消息，头部消息ID: {header_msg.message_id}, 转发消息ID: {forwarded.message_id}")

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global message_user_map
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
        
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ 请先回复一条消息")
        return
        
    replied_message_id = update.message.reply_to_message.message_id
    logger.info(f"管理员回复了消息ID: {replied_message_id}")
    
    original_user_id = message_user_map.get(replied_message_id)
    if original_user_id:
        if update.message.text:
            try:
                await context.bot.send_message(
                    chat_id=original_user_id,
                    text=f"{update.message.text}"
                )
                await update.message.reply_text("✅ 回复已成功发送给用户。")
                logger.info(f"已向用户 {original_user_id} 发送回复")
            except Exception as e:
                await update.message.reply_text(f"❌ 发送失败: {str(e)}")
                logger.error(f"发送回复失败: {str(e)}")
    else:
        await update.message.reply_text("⚠️ 请直接 '回复' 由机器人转发的用户消息来进行沟通。")
        logger.warning(f"未找到与消息ID {replied_message_id} 关联的用户")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"更新 {update} 导致错误 {context.error}")

# --- 核心改动：用Webhook替换Polling，添加Flask HTTP服务 ---
def main() -> None:
    # 1. 创建Telegram Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # 2. 添加所有处理器（不变）
    application.add_error_handler(error_handler)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(
        filters.TEXT & filters.REPLY & filters.User(user_id=ADMIN_CHAT_ID),
        handle_admin_reply
    ))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))

    # 3. 创建Flask实例（用于监听Render的端口）
    app = Flask(__name__)

    # 4. 定义Webhook接口：Telegram会向这个路径发送消息请求
    @app.route('/webhook', methods=['POST'])
    async def webhook() -> str:
        # 将HTTP请求解析为Telegram Update对象
        update = Update.de_json(request.get_json(force=True), application.bot)
        # 处理Update
        await application.process_update(update)
        return "ok"  # 必须返回"ok"给Telegram，否则会重复发送

    # 5. 启动前设置Webhook（告诉Telegram：往哪个URL发消息）
    async def setup_webhook():
        await application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
        logger.info(f"Webhook已设置为：{WEBHOOK_URL}/webhook")

    # 6. 先执行Webhook设置，再启动Flask服务（监听Render的端口）
    application.loop.run_until_complete(setup_webhook())
    app.run(host='0.0.0.0', port=PORT)  # host必须为0.0.0.0，Render才能访问

if __name__ == "__main__":
    main()
    
    

