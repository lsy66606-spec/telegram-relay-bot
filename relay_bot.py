import logging
import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.helpers import escape_markdown
from flask import Flask, request
# --- 关键修改1：删除 from flask.helpers import run_simple 这行 ---

# ... 中间的配置、全局变量、消息处理函数（完全不变） ...

# --- 主函数（修改启动逻辑，删除 run_simple，用 app.run 替代） ---
async def main_async() -> None:
    application = Application.builder().token(BOT_TOKEN).build()
    
    # 添加处理器（不变）
    application.add_error_handler(error_handler)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(
        filters.TEXT & filters.REPLY & filters.User(user_id=ADMIN_CHAT_ID),
        handle_admin_reply
    ))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))

    # 创建Flask应用（不变）
    app = Flask(__name__)

    # 异步Webhook视图函数（不变）
    @app.route('/webhook', methods=['POST'])
    async def webhook() -> str:
        update = Update.de_json(request.get_json(force=True), application.bot)
        await application.process_update(update)
        return "ok"

    # 设置Webhook（不变）
    await application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    logger.info(f"Webhook已设置为：{WEBHOOK_URL}/webhook")

    # --- 关键修改2：用 app.run 启动，添加 async_mode="asgiref" 支持异步 ---
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,  # 生产环境必须关闭debug
        use_reloader=False,  # 关闭自动重载，避免Render重复启动
        async_mode="asgiref"  # 启用异步模式，依赖Flask[async]安装的asgiref
    )

if __name__ == "__main__":
    asyncio.run(main_async())


