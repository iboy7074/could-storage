
import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from utils import ensure_download_dir, get_save_path
from file_manager import FileManager
from user_manager import UserManager

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Global state
file_manager = FileManager()
user_manager = UserManager()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Hi! I'm your Cloud Storage Bot.\n\n"
             "1. **First Time?** Type `/register` to create an account.\n"
             "2. **Commands**: Type `/home` to see all commands.\n"
             "3. **Upload**: Send any file/text.\n"
             "4. **Retrieve**: Send a Secret Code."
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    username = update.effective_user.username or "Unknown"
    
    if user_manager.register(user_id, username):
        await update.message.reply_text(f"✅ Welcome {username}! You are now registered.\nYou can start sending files immediately.")
    else:
        await update.message.reply_text("You are already registered! Just send me files.")

async def home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🏠 **Home - All Commands**\n\n"
        "**Basics**\n"
        "`/start` - Restart bot\n"
        "`/register` - Create account\n"
        "`/home` - Show this menu\n\n"
        "**Files**\n"
        "`/list` - List files & folders\n"
        "`/rename <code> <name>` - Rename file\n"
        "`/delete <code>` - Delete file\n"
        "**Upload**: Send any file/text (add caption to name it)\n"
        "**Retrieve**: Send the Secret Code\n\n"
        "**Folders**\n"
        "`/mkdir <name>` - Create folder\n"
        "`/cd <name>` - Enter folder\n"
        "`/cd ..` - Go back\n"
        "`/pwd` - Show current path\n\n"
        "**Web**\n"
        "`/setpassword <pass>` - Set web login password"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Please `/register` first.")
        return

    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: `/delete <code>`")
        return

    code = args[0]
    if file_manager.delete_file(code, update.effective_chat.id):
        await update.message.reply_text(f"🗑️ File `{code}` deleted.")
    else:
        await update.message.reply_text("❌ Failed to delete. Check code.")

async def mkdir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/mkdir <name>`")
        return
    
    name = args[0]
    if user_manager.create_folder(update.effective_chat.id, name):
        await update.message.reply_text(f"📁 Folder `{name}` created.")
    else:
        await update.message.reply_text("❌ Failed (maybe exists?).")

async def cd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/cd <name>` or `/cd ..`")
        return
    
    target = args[0]
    user_id = update.effective_chat.id
    current = user_manager.get_current_folder(user_id)
    
    if target == "..":
        if current == "/":
            await update.message.reply_text("Already at root.")
        else:
            # Go up one level
            parent = "/" + "/".join(current.strip("/").split("/")[:-1])
            if parent == "//": parent = "/" # Fix root case
            user_manager.set_current_folder(user_id, parent)
            await update.message.reply_text(f"📂 Moved to `{parent}`")
    else:
        # Try to enter folder
        if current == "/":
            new_path = f"/{target}"
        else:
            new_path = f"{current}/{target}"
            
        # Verify it exists (simple check against registered folders)
        folders = user_manager.db[str(user_id)].get("folders", ["/"])
        if new_path in folders:
            user_manager.set_current_folder(user_id, new_path)
            await update.message.reply_text(f"📂 Moved to `{new_path}`")
        else:
            await update.message.reply_text(f"❌ Folder `{target}` not found.")

async def pwd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    current = user_manager.get_current_folder(update.effective_chat.id)
    await update.message.reply_text(f"📂 Current Path: `{current}`")

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Please `/register` first.")
        return
    
    user_id = update.effective_chat.id
    current_folder = user_manager.get_current_folder(user_id)
    
    # Get files in current folder
    files = file_manager.get_user_files(user_id, current_folder)
    # Get subfolders
    subfolders = user_manager.get_subfolders(user_id, current_folder)
    
    if not files and not subfolders:
        await update.message.reply_text(f"📂 **{current_folder}** is empty.")
        return
        
    message = f"📂 **Path: {current_folder}**\n\n"
    
    if subfolders:
        message += "**Folders:**\n"
        for f in subfolders:
            name = f.split("/")[-1]
            message += f"📁 `{name}`\n"
        message += "\n"
        
    if files:
        message += "**Files:**\n"
        for code, name, _ in files:
            message += f"📄 `{code}` - {name}\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def rename_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Please `/register` first.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: `/rename <code > <new name>`")
        return

    code = args[0]
    new_name = " ".join(args[1:])
    
    if file_manager.rename_file(code, new_name, update.effective_chat.id):
        await update.message.reply_text(f"✅ File renamed to: {new_name}")
    else:
        await update.message.reply_text("❌ Failed to rename. Check the code or ownership.")

def is_authorized(update: Update) -> bool:
    return user_manager.is_registered(update.effective_chat.id)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Please `/register` first.")
        return

    ensure_download_dir()
    
    attachment = update.message.effective_attachment
    
    if isinstance(attachment, (list, tuple)):
        file_obj = attachment[-1]
        file_name = f"{file_obj.file_unique_id}.jpg"
    else:
        file_obj = attachment
        if hasattr(attachment, 'file_name'):
            file_name = attachment.file_name
        else:
            file_name = f"{attachment.file_unique_id}"

    # Use caption as name if provided
    display_name = file_name
    if update.message.caption:
        display_name = update.message.caption

    file = await file_obj.get_file()
    save_path = get_save_path(file_name)
    await file.download_to_drive(save_path)
    
    # Get current folder
    current_folder = user_manager.get_current_folder(update.effective_chat.id)
    
    # Generate Secret Code with ownership and folder
    code = file_manager.save_file_record(str(save_path), update.effective_chat.id, display_name, current_folder)
    
    await update.message.reply_text(
        f"File saved to `{current_folder}`! \n\nCode: `{code}`"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Allow register command to pass (though filters handle this, good safety)
    if not is_authorized(update):
        await update.message.reply_text("Please `/register` first.")
        return

    text = update.message.text.strip()
    file_path_str = file_manager.get_file_path(text)
    
    if file_path_str:
        if os.path.exists(file_path_str):
            # Check if it's a text file we created
            if file_path_str.endswith(".txt"):
                try:
                    with open(file_path_str, "r", encoding="utf-8") as f:
                        content = f.read()
                    await update.message.reply_text(f"📝 **Note/Link** (Code: {text}):\n\n{content}", parse_mode='Markdown')
                except Exception:
                    # Fallback if read fails
                    await update.message.reply_document(document=open(file_path_str, 'rb'), caption=f"Here is your file (Code: {text})")
            else:
                await update.message.reply_document(document=open(file_path_str, 'rb'), caption=f"Here is your file (Code: {text})")
        else:
            await update.message.reply_text("File not found on server.")
    else:
        ensure_download_dir()
        safe_prefix = "".join(c for c in text[:10] if c.isalnum()) or "text"
        file_name = f"{safe_prefix}_{update.message.id}.txt"
        save_path = get_save_path(file_name)
        
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(text)
            
        current_folder = user_manager.get_current_folder(update.effective_chat.id)
        code = file_manager.save_file_record(str(save_path), update.effective_chat.id, f"Note: {safe_prefix}...", current_folder)
        
        await update.message.reply_text(
            f"Text saved to `{current_folder}`! \n\nCode: `{code}`"
        )

async def set_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Please `/register` first.")
        return

    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: `/setpassword <password>`")
        return

    password = args[0]
    user_manager.set_web_password(update.effective_chat.id, password)
    await update.message.reply_text(f"✅ Web password set! You can now login at the website with User ID `{update.effective_chat.id}` and this password.")

async def admin_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: `/admin_login <secret_key>`")
        return

    secret = args[0]
    # Hardcoded secret for simplicity as per plan
    if secret == "secret123":
        user_manager.set_admin(update.effective_chat.id, True)
        await update.message.reply_text("👑 You are now an **Admin**! You can access the Admin Panel on the website.")
    else:
        await update.message.reply_text("❌ Invalid secret key.")

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Please `/register` first.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/search <query>`")
        return

    query = " ".join(args)
    user_id = update.effective_chat.id
    results = file_manager.search_files(query, user_id)

    if not results:
        await update.message.reply_text(f"🔍 No files found for '{query}'.")
        return

    message = f"🔍 **Search Results for '{query}':**\n\n"
    for code, name, _ in results:
        message += f"📄 `{code}` - {name}\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

if __name__ == '__main__':
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("Error: BOT_TOKEN not found in .env file.")
        exit(1)
    
    application = ApplicationBuilder().token(token).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('register', register))
    application.add_handler(CommandHandler('list', list_files))
    application.add_handler(CommandHandler('setpassword', set_password))
    application.add_handler(CommandHandler('rename', rename_file))
    application.add_handler(CommandHandler('admin_login', admin_login))
    application.add_handler(CommandHandler('search', search))
    
    # New handlers
    application.add_handler(CommandHandler('home', home))
    application.add_handler(CommandHandler('delete', delete_file))
    application.add_handler(CommandHandler('mkdir', mkdir))
    application.add_handler(CommandHandler('cd', cd))
    application.add_handler(CommandHandler('pwd', pwd))
    
    application.add_handler(MessageHandler(filters.ATTACHMENT | filters.PHOTO | filters.VIDEO | filters.AUDIO, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("Bot is running...")
    application.run_polling()
