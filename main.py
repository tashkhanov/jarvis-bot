import asyncio
import logging
import sys
import os
import io
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, BufferedInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ==========================================
# ⚙️ НАСТРОЙКИ
# ==========================================
TG_BOT_TOKEN = "2065954275:AAEfYKiMl-ikv8-CIdBZzVYDv1cOgIwGPLE"
GOOGLE_API_KEY = "AIzaSyBoIG3zkGWCvQMu1LWOlvbw_8S3dQkiu-Q" 
MY_ID = 1243374131

# Модели
MODEL_CHAT = "models/gemini-3-flash-preview"       # Основной мозг (Текст, Фото, Аудио, Видео)
MODEL_IMAGE = "models/imagen-4.0-generate-001"     # Рисование
MODEL_VIDEO = "models/veo-2.0-generate-001"        # Видео
# MODEL_TTS = "models/gemini-2.5-flash-preview-tts" # (Пока используем чат для ответов)

SYSTEM_PROMPT = """
Ты — Джарвис, ИИ-ассистент разработчика по имени Хан (Khan).
Твоя задача — помогать Хану и общаться с его клиентами.
Ты работаешь на базе Gemini 3 Flash. Ты видишь, слышишь и понимаешь всё.
Отвечай кратко, профессионально и по делу.
"""

# ==========================================
# 🚀 ИНИЦИАЛИЗАЦИЯ
# ==========================================
genai.configure(api_key=GOOGLE_API_KEY)

# Настройка безопасности (отключаем блокировку, чтобы не тупил)
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# Инициализация модели чата
model = genai.GenerativeModel(
    model_name=MODEL_CHAT,
    system_instruction=SYSTEM_PROMPT,
    safety_settings=safety_settings
)

bot = Bot(token=TG_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

# Хранилище чат-сессий {user_id: ChatSession}
sessions = {}

# ==========================================
# 🛠 ФУНКЦИИ
# ==========================================

async def upload_to_gemini(file_io, mime_type, file_name="temp"):
    """Загружает файл в Google File API"""
    # Сохраняем во временный файл, так как upload_file требует путь
    temp_path = f"temp_{file_name}"
    with open(temp_path, "wb") as f:
        f.write(file_io.getvalue())
    
    try:
        g_file = genai.upload_file(path=temp_path, mime_type=mime_type)
        print(f"📁 Файл загружен в Google: {g_file.name}")
        return g_file
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

async def wait_for_files_active(files):
    """Ждет, пока видео/аудио обработается на серверах Гугла"""
    print("⏳ Ожидание обработки файла...")
    for name in (file.name for file in files):
        file = genai.get_file(name)
        while file.state.name == "PROCESSING":
            await asyncio.sleep(2)
            file = genai.get_file(name)
        if file.state.name != "ACTIVE":
            raise Exception(f"File {file.name} failed to process")
    print("✅ Файл готов!")

# ==========================================
# 🎨 ГЕНЕРАЦИЯ (Imagen / Veo)
# ==========================================

@dp.message(Command("img"))
async def generate_image(message: Message):
    prompt = message.text.replace("/img", "").strip()
    if not prompt:
        await message.reply("Напиши промпт: `/img кот в космосе`")
        return
    
    await message.reply("🎨 Рисую (Imagen 4.0)...")
    try:
        imagen_model = genai.GenerativeModel(MODEL_IMAGE)
        response = imagen_model.generate_content(prompt)
        # Imagen обычно возвращает ссылки или байты. Зависит от версии API.
        # В Preview версиях это может быть images[0].image
        
        # (Тут нужна адаптация под конкретный формат ответа Imagen 4,
        # так как он новый, предполагаем стандартный output)
        
        # Если это стандартный Image Generation API:
        # В текущей версии Python SDK для Imagen мб отдельный метод,
        # но попробуем универсальный generate_content
        
        # ВРЕМЕННАЯ ЗАГЛУШКА ДЛЯ IMAGEN (Пока API может отличаться)
        # Если не сработает, он напишет ошибку в чат
        
        await message.reply("⚠️ Imagen API требует отдельной настройки outputs. Сейчас отвечу текстом.")
        
    except Exception as e:
        await message.reply(f"Ошибка генерации: {e}")

# ==========================================
# 🧠 ОБРАБОТКА СООБЩЕНИЙ (ЧАТ)
# ==========================================

@dp.business_message()
async def handle_business_message(message: Message):
    user_id = message.chat.id
    sender_id = message.from_user.id
    
    # Игнорим себя (но можем сохранять в историю, если нужно)
    if sender_id == MY_ID: return
    if message.from_user.is_bot: return

    print(f"📩 ID: {sender_id} | Тип: {message.content_type}")

    try:
        # Инициализация сессии
        if user_id not in sessions:
            sessions[user_id] = model.start_chat(history=[])
        
        chat = sessions[user_id]
        content_to_send = []
        text_part = ""

        # 1. ОБРАБОТКА ФАЙЛОВ
        await bot.send_chat_action(chat_id=user_id, action="typing", business_connection_id=message.business_connection_id)

        # ФОТО
        if message.photo:
            file_io = io.BytesIO()
            await bot.download(message.photo[-1], destination=file_io)
            g_file = await upload_to_gemini(file_io, "image/jpeg", f"{user_id}.jpg")
            content_to_send.append(g_file)
            text_part = message.caption or "Что на этом фото?"

        # ГОЛОСОВОЕ / АУДИО (Native Audio)
        elif message.voice or message.audio:
            file_id = message.voice.file_id if message.voice else message.audio.file_id
            file_io = io.BytesIO()
            await bot.download(file_id, destination=file_io)
            # Gemini 3 кушает аудио нативно!
            g_file = await upload_to_gemini(file_io, "audio/mpeg", f"{user_id}.mp3")
            await wait_for_files_active([g_file])
            content_to_send.append(g_file)
            text_part = message.caption or "Прослушай это аудио и ответь."

        # ВИДЕО / КРУЖОЧЕК (Native Video)
        elif message.video or message.video_note:
            file_id = message.video.file_id if message.video else message.video_note.file_id
            file_io = io.BytesIO()
            await bot.download(file_id, destination=file_io)
            g_file = await upload_to_gemini(file_io, "video/mp4", f"{user_id}.mp4")
            await wait_for_files_active([g_file])
            content_to_send.append(g_file)
            text_part = message.caption or "Посмотри это видео и ответь, что там происходит."

        # ТЕКСТ
        elif message.text:
            text_part = message.text

        # 2. ОТПРАВКА ЗАПРОСА
        if text_part:
            content_to_send.append(text_part)

        if not content_to_send:
            return

        # Gemini 3 Flash должен ответить быстро
        response = await chat.send_message_async(content_to_send)
        ai_answer = response.text

        # 3. ОТВЕТ
        await bot.send_message(
            chat_id=user_id,
            text=ai_answer,
            business_connection_id=message.business_connection_id,
            reply_to_message_id=message.message_id
        )
        print(f"🤖 Gemini 3: {ai_answer[:50]}...")

    except Exception as e:
        print(f"❌ Error: {e}")
        # Если модель не найдена (404), попробуем откатиться
        if "404" in str(e):
             print("⚠️ Модель Gemini 3 не найдена, проверь название!")

async def main():
    print(f"🚀 JARVIS GEMINI 3 ULTIMATE ЗАПУЩЕН")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main())
    except KeyboardInterrupt: pass