import asyncio
import logging
import json
import re
import base64
from io import BytesIO
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram import F
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "8152924251:AAFJmHGJXGWgQnCcs_O64NTR8YTrK42x0GE"
MISTRAL_KEY = "rGmIVqCbaDh29Y7t3Yd7ipsbL0ZlQbny"

client = AsyncOpenAI(
    api_key=MISTRAL_KEY,
    base_url="https://api.mistral.ai/v1",
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_history = {}

INSTITUTE_INFO = """
Кубанский институт профессионального образования (КИПО):
- Основан в 1997 году
- 18 специальностей
- 5000+ студентов
- Приём без экзаменов, по среднему баллу аттестата
- Документы: заявление, паспорт, аттестат, 4 фото, медсправка 086/у
- Контакты: 8 800 500 40 68 доб. 1180, г. Краснодар, ул. Садовая 218
"""

# Загрузка групп
try:
    with open('groups.json', 'r', encoding='utf-8') as f:
        GROUP_SCHEDULES = json.load(f)
    logging.info(f"Загружено {len(GROUP_SCHEDULES)} групп")
except Exception as e:
    logging.error(f"groups.json ошибка: {e}")
    GROUP_SCHEDULES = {}

# Загрузка преподавателей (точно так же, как groups)
try:
    with open('teachers.json', 'r', encoding='utf-8') as f:
        TEACHERS = json.load(f)
    logging.info(f"Загружено {len(TEACHERS)} преподавателей")
except Exception as e:
    logging.error(f"teachers.json ошибка: {e}")
    TEACHERS = {}

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    user_history[user_id] = []
    await message.answer(
        "🤖 Привет! Я ассистент КИПО.\n\n"
        "Могу:\n"
        "• отвечать на вопросы об институте\n"
        "• показывать расписание группы (пиши 'расписание 24-ИСП1-9')\n"
        "• искать преподавателя по фамилии (пиши просто 'Иванова' или 'Абрамова')\n"
        "• анализировать фото — кинь картинку!\n\n"
        "Примеры:\n"
        "расписание ИСП 25\n"
        "Абрамова\n"
        "Ашинова\n"
        "что на фото?\n"
        "/clear — очистить чат",
        parse_mode="Markdown"
    )

@dp.message(Command("clear"))
async def clear_cmd(message: types.Message):
    user_id = message.from_user.id
    user_history[user_id] = []
    await message.answer("🧹 Чат очищен!")

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    user_id = message.from_user.id
    history = user_history.get(user_id, [])

    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)

    img_bytes = BytesIO(downloaded_file.read())
    img_base64 = base64.b64encode(img_bytes.getvalue()).decode('utf-8')

    user_text = message.caption.strip() if message.caption else "Опиши подробно, что на этой фотографии. Если связано с учебой/КИПО — упомяни."

    history.append({"role": "user", "content": user_text})

    system_prompt = (
        "Ты дружелюбный ассистент КИПО. Анализируй фото внимательно.\n"
        f"Инфо об институте:\n{INSTITUTE_INFO}\n"
        "Отвечай на русском, подробно по сути, позитивно."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
            ]
        }
    ] + history[-8:]

    try:
        await message.answer("📸 Анализирую фото...")
        response = await client.chat.completions.create(
            model="pixtral-large-latest",
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )
        reply = response.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": reply})
        user_history[user_id] = history
        await message.answer(reply)
    except Exception as e:
        logging.error(f"Vision error: {e}")
        err = str(e).lower()
        if "rate limit" in err or "429" in err:
            await message.answer("⚠️ Лимит — подожди 30–60 сек.")
        elif "model" in err:
            await message.answer("Модель pixtral-large-latest недоступна сейчас. Попробуй позже.")
        else:
            await message.answer("😔 Проблема с анализом фото. Попробуй другую картинку.")

@dp.message(F.text)
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    user_text = message.text.strip()
    lower_text = user_text.lower()

    history = user_history.get(user_id, [])
    history.append({"role": "user", "content": user_text})

    # Прямой ответ на вопросы о дате/времени
    date_keywords = ["сегодня", "дата", "год", "число", "день недели", "время", "мск", "москва", "сколько времени", "какое время"]
    if any(kw in lower_text for kw in date_keywords):
        from datetime import datetime
        import pytz
        moscow = pytz.timezone('Europe/Moscow')
        now = datetime.now(moscow)
        weekday_ru = {
            'Monday': 'понедельник', 'Tuesday': 'вторник', 'Wednesday': 'среда',
            'Thursday': 'четверг', 'Friday': 'пятница', 'Saturday': 'суббота', 'Sunday': 'воскресенье'
        }
        date_str = now.strftime("%d %B %Y года")
        time_str = now.strftime("%H:%M")
        day_ru = weekday_ru[now.strftime("%A")]
        await message.answer(f"Сегодня {day_ru}, {date_str}.\nВремя в Москве: {time_str}")
        return

    # 1. Расписание группы
    schedule_keywords = [
        "расписание", "распис", "расп", "распиши", "уроки", "занятия", "пары", "пар",
        "расписание группы", "какое расписание", "покажи расписание", "когда занятия"
    ]

    if any(kw in lower_text for kw in schedule_keywords) and GROUP_SCHEDULES:
        group_pattern = r'(\d{2}-?[А-ЯA-ZЁё]{2,5}(?:\d?)(?:-\d)?(?:\s*ЗФО)?(?:-\d{1,2})?)'
        matches = re.findall(group_pattern, user_text, re.IGNORECASE)

        query = ""
        if matches:
            query = matches[0].upper().replace(" ", "").replace("-", "")
        else:
            query = re.sub(r'[^А-ЯA-Z0-9-ЗФО]', '', user_text.upper())

        found = []
        for code, url in GROUP_SCHEDULES.items():
            clean_code = code.upper().replace(" ", "").replace("-", "")
            if query and (query in clean_code or clean_code in query):
                found.append((code, url))

        if found:
            if len(found) == 1:
                code, url = found[0]
                await message.answer(f"Расписание **{code}**:\n{url}")
            else:
                text = f"Нашёл {len(found)} вариантов:\n\n"
                for c, u in found[:8]:
                    text += f"• {c} → {u}\n"
                if len(found) > 8:
                    text += f"...ещё {len(found)-8}. Уточни."
                await message.answer(text)
            return

        else:
            await message.answer("Группу не нашёл 😔\nПример: 'расписание 24-ИСП1-9'")
            return

    # 2. Поиск преподавателя по фамилии
    if TEACHERS:
        found = []
        query_clean = lower_text.replace(".", "").replace(" ", "").replace("*", "")

        for name, url in TEACHERS.items():
            name_clean = name.lower().replace(".", "").replace(" ", "").replace("*", "")
            if query_clean in name_clean:
                found.append((name, url))

        if found:
            if len(found) == 1:
                name, url = found[0]
                await message.answer(f"Преподаватель: {name}\nРасписание: {url}")
            else:
                text = f"Нашёл {len(found)} похожих преподавателей:\n\n"
                for i, (name, url) in enumerate(found[:12], 1):
                    text += f"{i}. {name} → {url}\n"
                if len(found) > 12:
                    text += f"\n...ещё {len(found)-12}. Уточни фамилию."
                text += "\n\nНапиши номер или фамилию точнее:"
                await message.answer(text)
            return

    # 3. Всё остальное — Mistral
    system_prompt = (
        "Ты дружелюбный ассистент КИПО. Отвечай на русском, кратко и по делу.\n"
        f"Инфо:\n{INSTITUTE_INFO}\n"
        "Про расписание группы — советуй 'расписание [код]'\n"
        "Про преподавателя — советуй написать просто фамилию"
    )

    messages = [{"role": "system", "content": system_prompt}] + history[-12:]

    try:
        await message.answer("🤔 Думаю...")
        response = await client.chat.completions.create(
            model="mistral-small-latest",
            messages=messages,
            temperature=0.7,
            max_tokens=800
        )
        reply = response.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": reply})
        user_history[user_id] = history
        await message.answer(reply)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await message.answer("😔 Проблема. Попробуй позже или звони: 8 800 500 40 68 доб. 1180")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())