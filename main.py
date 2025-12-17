import asyncio
import logging
import sys
import random
import os
import base64
from io import BytesIO
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from openai import AsyncOpenAI
from aiohttp import web # <-- Для веб-сервера

# === НАСТРОЙКИ ===
TG_BOT_TOKEN = "2065954275:AAEfYKiMl-ikv8-CIdBZzVYDv1cOgIwGPLE"
GROQ_API_KEY = "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"
MY_ID = 1243374131

TEXT_MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
AUDIO_MODEL = "whisper-large-v3"

SYSTEM_PROMPT = """
ТЫ — ИИ-АССИСТЕНТ. ТЕБЯ ЗОВУТ "ДЖАРВИС".
ТВОЙ ВЛАДЕЛЕЦ И БОСС: Хан (Khan).
Хан — Fullstack разработчик (PHP, Laravel, Python, Django, JS).

ТВОИ ЗАДАЧИ:
1. Общаться с клиентами от имени ассистента. НИКОГДА не говори, что ты Хан.
2. Говори: "Хан сейчас занят", "Я передам Хану", "Хан просил передать".
3. Понимай любой язык. Если пишут на узбекском — отвечай на узбекском. Если на русском — на русском.
4. Отвечай кратко, профессионально, но с легкой ноткой дружелюбия.
5. Ну и не надо зацикливаться на "Хан сейчас занят", "Я передам Хану", "Хан просил передать", и т.д, то есть не общайся как какой-то зацикленный робот а вникай в беседу и будь также дружелюбным чтобы не быть через чур деловым.

ЕСЛИ СПРАШИВАЮТ ЦЕНУ: "Нужно ТЗ, Хан оценит и скажет точную сумму."
ЕСЛИ ПРИСЛАЛИ ФОТО: Опиши, что там, и спроси, чем помочь по этому изображению.
"""

chat_history = {}

client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

bot = Bot(token=TG_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# --- ФУНКЦИИ БОТА ---

async def image_to_base64(file_id):
    file = await bot.get_file(file_id)
    binary_io = BytesIO()
    await bot.download_file(file.file_path, binary_io)
    return base64.b64encode(binary_io.getvalue()).decode('utf-8')

async def transcribe_audio(file_id):
    file = await bot.get_file(file_id)
    filename = f"temp_{file_id}.m4a"
    await bot.download_file(file.file_path, filename)
    try:
        with open(filename, "rb") as audio_file:
            transcription = await client.audio.transcriptions.create(
                file=(filename, audio_file.read()),
                model=AUDIO_MODEL,
                response_format="json"
            )
        return transcription.text
    finally:
        if os.path.exists(filename): os.remove(filename)

# --- ЛОГИКА БОТА ---

@dp.business_message()
async def handle_business_message(message: Message):
    user_id = message.chat.id
    sender_id = message.from_user.id
    user_name = message.from_user.first_name
    
    if sender_id == MY_ID:
        if user_id in chat_history:
            text = message.text or "[Файл]"
            chat_history[user_id].append({"role": "assistant", "content": text})
        return

    if message.from_user.is_bot: return
    print(f"📩 {user_name}: {message.content_type}")

    try:
        if user_id not in chat_history:
            chat_history[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

        current_content = []
        ai_response = ""
        use_vision = False
        reply_ctx = ""
        if message.reply_to_message:
            r_text = message.reply_to_message.text or "[Медиа]"
            reply_ctx = f" (В ответ на: '{r_text}')"

        if message.photo:
            await bot.send_chat_action(chat_id=user_id, action="upload_photo", business_connection_id=message.business_connection_id)
            img_b64 = await image_to_base64(message.photo[-1].file_id)
            caption = message.caption or "Что на изображении?"
            current_content = [
                {"type": "text", "text": f"{caption} {reply_ctx}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            ]
            use_vision = True

        elif message.voice or message.video_note or message.audio:
            await bot.send_chat_action(chat_id=user_id, action="record_voice", business_connection_id=message.business_connection_id)
            fid = message.voice.file_id if message.voice else (message.video_note.file_id if message.video_note else message.audio.file_id)
            text_voice = await transcribe_audio(fid)
            if message.video_note and message.video_note.thumb:
                img_b64 = await image_to_base64(message.video_note.thumb.file_id)
                current_content = [
                    {"type": "text", "text": f"Видео-кружок. Текст: '{text_voice}'. {reply_ctx}. Анализируй кадр."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]
                use_vision = True
            else:
                current_content = f"[Голос]: {text_voice} {reply_ctx}"

        elif message.text:
            current_content = message.text + reply_ctx
        else:
            return

        if use_vision:
            res = await client.chat.completions.create(
                model=VISION_MODEL,
                messages=[{"role": "user", "content": current_content}],
                temperature=0.5,
                max_tokens=500
            )
            ai_response = res.choices[0].message.content
            chat_history[user_id].append({"role": "user", "content": "[Файл]"})
        else:
            chat_history[user_id].append({"role": "user", "content": current_content})
            if len(chat_history[user_id]) > 15:
                chat_history[user_id] = [chat_history[user_id][0]] + chat_history[user_id][-10:]
            
            await asyncio.sleep(1)
            await bot.send_chat_action(chat_id=user_id, action="typing", business_connection_id=message.business_connection_id)
            await asyncio.sleep(random.randint(2, 4))
            
            res = await client.chat.completions.create(
                model=TEXT_MODEL,
                messages=chat_history[user_id],
                temperature=0.7,
                max_tokens=400
            )
            ai_response = res.choices[0].message.content

        chat_history[user_id].append({"role": "assistant", "content": ai_response})
        await bot.send_message(
            chat_id=user_id,
            text=ai_response,
            business_connection_id=message.business_connection_id,
            reply_to_message_id=message.message_id
        )
        print(f"🤖 Ответ: {ai_response}")

    except Exception as e:
        print(f"❌ Error: {e}")

# --- ВЕБ-СЕРВЕР (Keep Alive) ---
async def handle_ping(request):
    return web.Response(text="Jarvis is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render выдает порт через переменную окружения, или используем 8080
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌍 Web server started on port {port}")

# --- ЗАПУСК ---
async def main():
    print("🚀 JARVIS CLOUD запущен")
    # Запускаем и веб-сервер, и бота одновременно
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main())
    except KeyboardInterrupt: pass