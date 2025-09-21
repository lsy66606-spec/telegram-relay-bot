import logging
import os  # 导入os模块用于读取环境变量
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.helpers import escape_markdown

# --- 从环境变量获取配置 ---
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')  # 从环境变量获取机器人令牌
ADMIN_CHAT_ID = os.getenv('TELEGRAM_ADMIN_CHAT_ID')  # 从环境变量获取管理员Chat ID

# 检查是否成功获取环境变量
if not BOT_TOKEN or not ADMIN_CHAT_ID:
    print("错误：请先设置 TELEGRAM_BOT_TOKEN 和 TELEGRAM_ADMIN_CHAT_ID 环境变量！")
    exit(1)

# 将ADMIN_CHAT_ID转换为整数
try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
except ValueError:
    print("错误：TELEGRAM_ADMIN_CHAT_ID 必须是整数！")
    exit(1)
# --- 配置区结束 ---

# 使用全局字典存储消息ID与用户ID的关联
message_user_map = {}

# 设置日志记录
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /start 命令，给用户发送欢迎消息"""
    await update.message.reply_text("你好！你可以直接在这里给我发送消息，我会将它转达给管理员。")


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理所有来自普通用户的消息，并将其转发给管理员"""
    global message_user_map
    
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    message_id = update.message.message_id

    # 忽略来自管理员自己的消息，避免自己给自己转发
    if user_id == ADMIN_CHAT_ID:
        return

    logger.info(f"收到用户 {user_id} 的消息 (消息ID: {message_id})")

    # 对用户名和用户ID进行Markdown转义处理
    escaped_name = escape_markdown(user_name, version=2)
    escaped_user_id = escape_markdown(str(user_id), version=2)
    
    # 构造头部信息
    header = f"📩 收到来自用户 {escaped_name} \\(ID: `{escaped_user_id}`\\) 的新消息："
    # 发送带用户ID的头部信息
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
    
    # 将用户ID存储在全局字典中，同时关联头部消息和转发消息的ID
    message_user_map[header_msg.message_id] = user_id
    message_user_map[forwarded.message_id] = user_id
    
    logger.info(f"已转发消息，头部消息ID: {header_msg.message_id}, 转发消息ID: {forwarded.message_id}")
    logger.info(f"当前关联映射: {message_user_map}")


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理管理员的回复消息，并将其发送给原始用户"""
    global message_user_map
    
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
        
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ 请先回复一条消息")
        return
        
    replied_message = update.message.reply_to_message
    replied_message_id = replied_message.message_id
    
    logger.info(f"管理员回复了消息ID: {replied_message_id}")
    logger.info(f"当前关联映射: {message_user_map}")
    
    # 从全局字典中获取原始用户ID
    original_user_id = message_user_map.get(replied_message_id)
    
    if original_user_id:
        if update.message.text:
            try:
                # 直接发送管理员的回复内容，不添加前缀文字
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


def main() -> None:
    """启动机器人"""
    application = Application.builder().token(BOT_TOKEN).build()

    # 添加错误处理器
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理所有错误"""
        logger.error(f"更新 {update} 导致错误 {context.error}")

    application.add_error_handler(error_handler)

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(
        filters.TEXT & filters.REPLY & filters.User(user_id=ADMIN_CHAT_ID),
        handle_admin_reply
    ))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))

    print("机器人已启动，等待消息...")
    application.run_polling()


if __name__ == "__main__":
    main()
    
    
    
