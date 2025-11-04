#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import csv
import glob
import logging
import os
import random
from typing import Dict, List

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv

# для healthcheck на Render
from aiohttp import web

# ── Настройки ──────────────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN обязателен: добавь его в Secrets/Env.")


# ── Состояния ─────────────────────────────────────────────────────────────────
class QuizStates(StatesGroup):
    waiting_for_answer = State()


# ── Модель бота ───────────────────────────────────────────────────────────────
class PolishTrainerBot:

    def __init__(self):
        # Базовая лексика (pl → ru), чтобы были стартовые категории
        self.vocabulary: Dict[str, str] = {
            # Powitania (приветствия/прощания)
            "dzień dobry": "добрый день",
            "dobry wieczór": "добрый вечер",
            "cześć": "привет/пока",
            "pa": "пока",
            "na razie": "пока",
            "do widzenia": "до свидания",
            "dziękuję": "спасибо",
            "proszę": "пожалуйста",
            "tak": "да",
            "nie": "нет",

            # Kolory
            "czerwony": "красный",
            "niebieski": "синий",
            "zielony": "зелёный",
            "żółty": "жёлтый",
            "czarny": "чёрный",
            "biały": "белый",
            "różowy": "розовый",
            "fioletowy": "фиолетовый",

            # Liczby 0–10
            "jeden": "один",
            "dwa": "два",
            "trzy": "три",
            "cztery": "четыре",
            "pięć": "пять",
            "sześć": "шесть",
            "siedem": "семь",
            "osiem": "восемь",
            "dziewięć": "девять",
            "dziesięć": "десять",

            # Liczby 10–20
            "jedenaście": "одиннадцать",
            "dwanaście": "двенадцать",
            "trzynaście": "тринадцать",
            "czternaście": "четырнадцать",
            "piętnaście": "пятнадцать",
            "szesnaście": "шестнадцать",
            "siedemnaście": "семнадцать",
            "osiemnaście": "восемнадцать",
            "dziewiętnaście": "девятнадцать",
            "dwadzieścia": "двадцать",

            # Liczby 20–100 (десятки)
            "trzydzieści": "тридцать",
            "czterdzieści": "сорок",
            "pięćdziesiąt": "пятьдесят",
            "sześćdziesiąt": "шестьдесят",
            "siedemdziesiąt": "семьдесят",
            "osiemdziesiąt": "восемьдесят",
            "dziewięćdziesiąt": "девяносто",

            # Liczby 100–1000
            "sto": "сто",
            "dwieście": "двести",
            "trzysta": "триста",
            "czterysta": "четыреста",
            "pięćset": "пятьсот",
            "sześćset": "шестьсот",
            "siedemset": "семьсот",
            "osiemset": "восемьсот",
            "dziewięćset": "девятьсот",
            "tysiąc": "тысяча",

            # Zwroty
            "jak się masz?": "как дела?",
            "miło mi cię poznać": "приятно познакомиться",
            "nie rozumiem": "я не понимаю",
            "mówisz po angielsku?": "ты говоришь по-английски?",
            "ile to kosztuje?": "сколько это стоит?",
            "gdzie jest toaleta?": "где туалет?",
        }

        # Категории (ключи — польские, как в интерфейсе)
        self.categories: Dict[str, List[str]] = {
            # Podstawy → powitania, kolory, liczby*, zwroty
            "powitania": [
                "dzień dobry", "dobry wieczór", "cześć", "do widzenia",
                "dziękuję", "proszę", "tak", "nie", "pa", "na razie"
            ],
            "kolory": [
                "czerwony", "niebieski", "zielony", "żółty", "czarny", "biały",
                "różowy", "fioletowy"
            ],
            "liczby_0_10": [
                "jeden", "dwa", "trzy", "cztery", "pięć", "sześć", "siedem",
                "osiem", "dziewięć", "dziesięć"
            ],
            "liczby_10_20": [
                "jedenaście", "dwanaście", "trzynaście", "czternaście",
                "piętnaście", "szesnaście", "siedemnaście", "osiemnaście",
                "dziewiętnaście", "dwadzieścia"
            ],
            "liczby_20_100": [
                "trzydzieści", "czterdzieści", "pięćdziesiąt", "sześćdziesiąt",
                "siedemdziesiąt", "osiemdziesiąt", "dziewięćdziesiąt"
            ],
            "liczby_100_1000": [
                "sto", "dwieście", "trzysta", "czterysta", "pięćset",
                "sześćset", "siedemset", "osiemset", "dziewięćset", "tysiąc"
            ],
            "zwroty": [
                "jak się masz?", "miło mi cię poznać", "nie rozumiem",
                "мówisz po angielsku?", "ile to kosztuje?",
                "gdzie jest toaleta?"
            ],

            # Остальные подтянутся из CSV:
            # "rodzina", "semya", "rutyna", "mieszkanie", "czas_wolny",
            # jedzenie_owoce, jedzenie_warzywa, itd.
        }

        # Подтягиваем все CSV из data/
        self.load_csv_vocabulary()

        # Статистика/сессии
        self.user_scores: Dict[int, Dict] = {}
        self.quiz_sessions: Dict[int, Dict] = {}

    def load_csv_vocabulary(self):
        """Подгружаем все CSV из папки data/ и расширяем словарь/категории."""
        try:
            files = glob.glob("data/*.csv")
            for path in files:
                cat_key = os.path.splitext(os.path.basename(path))[0].lower()
                if cat_key not in self.categories:
                    self.categories[cat_key] = []
                with open(path, "r", encoding="utf-8") as f:
                    reader = csv.reader(f, delimiter=";")
                    for row in reader:
                        if len(row) >= 2:
                            pl = (row[0] or "").strip()
                            ru = (row[1] or "").strip()
                            if pl and ru:
                                self.vocabulary[pl] = ru
                                self.categories[cat_key].append(pl)
            logger.info(
                f"✅ Категорий: {len(self.categories)}; слов: {len(self.vocabulary)}"
            )
        except Exception as e:
            logger.error(f"Ошибка при загрузке CSV: {e}")

    def get_user_stats(self, user_id: int) -> Dict:
        if user_id not in self.user_scores:
            self.user_scores[user_id] = {
                'total_questions': 0,
                'correct_answers': 0,
                'quiz_count': 0
            }
        return self.user_scores[user_id]

    def update_user_score(self, user_id: int, is_correct: bool):
        s = self.get_user_stats(user_id)
        s['total_questions'] += 1
        if is_correct:
            s['correct_answers'] += 1


# ── Инициализация aiogram ────────────────────────────────────────────────────
trainer = PolishTrainerBot()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# ── Группы и названия ─────────────────────────────────────────────────────────
GROUPS = {
    # Показываем только существующие категории (фильтрация — ниже)
    "podstawy": [
        "powitania", "kolory", "liczby_0_10", "liczby_10_20", "liczby_20_100",
        "liczby_100_1000", "zwroty"
    ],
    "jedzenie": [
        # сюда автоматически попадут CSV: jedzenie_owoce, jedzenie_warzywa, itd.
        # если ты их создала — добавь ключи, чтобы показать в меню:
        "jedzenie_owoce",
        "jedzenie_warzywa",
        "jedzenie_mieso",
        "jedzenie_ryby",
        "jedzenie_nabial",
        "jedzenie_pieczywo",
        "jedzenie_napoje",
        "jedzenie_slodycze",
        "jedzenie_przyprawy"
    ],
    "rutyna": ["rutyna"],
    "rodzina": ["rodzina", "semya"],
    "czas_wolny": ["czas_wolny"],
    "mieszkanie": ["mieszkanie"],
}

NAMES_PL = {
    # группы
    "podstawy": "Podstawy",  # 👋
    "jedzenie": "Jedzenie",  # 🍽️
    "rutyna": "Rutyna",  # 🕒
    "rodzina": "Rodzina",  # 👨‍👩‍👧‍👦
    "czas_wolny": "Czas wolny",  # 🎯
    "mieszkanie": "Mieszkanie",  # 🏠

    # категории
    "powitania": "Powitania",
    "kolory": "Kolory",
    "zwroty": "Zwroty",
    "liczby_0_10": "Liczby 0–10",
    "liczby_10_20": "Liczby 10–20",
    "liczby_20_100": "Liczby 20–100",
    "liczby_100_1000": "Liczby 100–1000",
    "jedzenie_owoce": "Owoce",
    "jedzenie_warzywa": "Warzywa",
    "jedzenie_mieso": "Mięso",
    "jedzenie_ryby": "Ryby",
    "jedzenie_nabial": "Nabiał",
    "jedzenie_pieczywo": "Pieczywo",
    "jedzenie_napoje": "Napoje",
    "jedzenie_slodycze": "Słodycze",
    "jedzenie_przyprawy": "Przyprawy",
    "rutyna": "Rutyna",
    "rodzina": "Rodzina",
    "semya": "Rodzina",
    "czas_wolny": "Czas wolny",
    "mieszkanie": "Mieszkanie",
}


def icon_for_group(gkey: str) -> str:
    return {
        "podstawy": "👋",
        "jedzenie": "🍽️",
        "rodzina": "👨‍👩‍👧‍👦",
        "rutyna": "🕒",
        "czas_wolny": "🎯",
        "mieszkanie": "🏠"
    }.get(gkey, "📁")


# ── Клавиатуры ────────────────────────────────────────────────────────────────
def get_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📖 Ucz się słówek",
                                 callback_data="nav_learn")
        ],
        [
            InlineKeyboardButton(text="🎯 Tryb treningowy",
                                 callback_data="nav_train")
        ],
        [
            InlineKeyboardButton(text="🔎 Przeglądaj",
                                 callback_data="nav_browse")
        ],
        [InlineKeyboardButton(text="🎲 Losowe słowo", callback_data="random")],
        [InlineKeyboardButton(text="📊 Postępy", callback_data="progress")],
    ])


def get_groups_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for gkey, cats in GROUPS.items():
        # показываем группу только если в ней есть хотя бы одна реальная категория
        existing = [
            c for c in cats
            if c in trainer.categories and trainer.categories[c]
        ]
        if not existing:
            continue
        rows.append([
            InlineKeyboardButton(
                text=
                f"{icon_for_group(gkey)} {NAMES_PL.get(gkey, gkey.capitalize())}",
                callback_data=f"learn_group:{gkey}")
        ])
    rows.append(
        [InlineKeyboardButton(text="🔙 Wróć", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_group_categories_keyboard(group_key: str) -> InlineKeyboardMarkup:
    rows = []
    for ckey in GROUPS.get(group_key, []):
        if ckey in trainer.categories and trainer.categories[ckey]:
            rows.append([
                InlineKeyboardButton(
                    text=f"📂 {NAMES_PL.get(ckey, ckey.capitalize())}",
                    callback_data=f"cat_{ckey}")
            ])
    rows.append(
        [InlineKeyboardButton(text="🔙 Wróć", callback_data="nav_learn")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Старт и меню ──────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message):
    txt = ("🇵🇱 Witaj w Polish Trainer Bot! 🇵🇱\n\n"
           "Ucz się słownictwa, rozwiązuj quizy i śledź postępy.\n"
           "Учи слова, проходи викторины и отслеживай прогресс.\n\n"
           "Wybierz opcję / Выбери действие:")
    await message.answer(txt,
                         reply_markup=get_main_keyboard(),
                         parse_mode="HTML")


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(cb: CallbackQuery):
    await cb.message.edit_text("🏠 Menu główne\n\nWybierz opcję:",
                               reply_markup=get_main_keyboard())
    await cb.answer()


# ── Новая навигация: «Ucz się słówek» (Группы → Категории) ───────────────────
@router.callback_query(F.data == "nav_learn")
async def nav_learn(cb: CallbackQuery):
    await cb.message.edit_text("📖 <b>Ucz się słówek</b>\n\nWybierz grupę:",
                               reply_markup=get_groups_keyboard(),
                               parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("learn_group:"))
async def nav_learn_group(cb: CallbackQuery):
    group_key = cb.data.split(":", 1)[1]
    title = NAMES_PL.get(group_key, group_key.capitalize())
    await cb.message.edit_text(
        f"📚 <b>{title}</b>\n\nWybierz kategorię:",
        reply_markup=get_group_categories_keyboard(group_key),
        parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "nav_train")
async def nav_train(cb: CallbackQuery):
    # пока используем текущий вход в квиз
    await cb.answer()
    await quiz_entry(cb)


@router.callback_query(F.data == "nav_browse")
async def nav_browse(cb: CallbackQuery):
    await cb.message.edit_text(
        "🔎 <b>Przeglądaj</b>\n\nWybierz grupę w „📖 Ucz się słówek”.\n"
        "W następnym kroku dodamy paginację.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📖 Ucz się słówek",
                                     callback_data="nav_learn")
            ],
            [
                InlineKeyboardButton(text="🔙 Wróć",
                                     callback_data="back_to_menu")
            ],
        ]),
        parse_mode="HTML")
    await cb.answer()


# ── Просмотр категорий ───────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("cat_"))
async def show_category(cb: CallbackQuery):
    key = cb.data.replace("cat_", "")
    if key == "all":
        pairs = list(trainer.vocabulary.items())
        cat_name = "Wszystkie słowa"
    else:
        lst = trainer.categories.get(key, [])
        pairs = [(w, trainer.vocabulary[w]) for w in lst
                 if w in trainer.vocabulary]
        cat_name = NAMES_PL.get(key, key.capitalize())

    if not pairs:
        await cb.message.edit_text("❌ W tej kategorii na razie nie ma słów.",
                                   reply_markup=get_main_keyboard())
        await cb.answer()
        return

    text = f"📚 <b>{cat_name}</b>\n\n"
    for pl, ru in pairs:
        text += f"🇵🇱 <code>{pl}</code> → {ru}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Grupy", callback_data="nav_learn")],
        [
            InlineKeyboardButton(text="🏠 Menu główne",
                                 callback_data="back_to_menu")
        ],
    ])
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


# ── ВИКТОРИНА (как раньше) ───────────────────────────────────────────────────
@router.callback_query(F.data == "quiz")
async def quiz_entry(cb: CallbackQuery):
    await cb.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇵🇱 → 🇷🇺", callback_data="quiz_pl_ru")],
        [InlineKeyboardButton(text="🇷🇺 → 🇵🇱", callback_data="quiz_ru_pl")],
        [InlineKeyboardButton(text="🔙 Wróć", callback_data="back_to_menu")],
    ])
    await cb.message.edit_text(
        "Wybierz tryb quizu:\n\n"
        "🇵🇱 → 🇷🇺 Polskie słowo → tłumaczenie na rosyjski\n"
        "🇷🇺 → 🇵🇱 Rosyjskie słowo → tłumaczenie na polski",
        reply_markup=kb)


@router.callback_query((F.data == "quiz_pl_ru") | (F.data == "quiz_ru_pl"))
async def quiz_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    uid = cb.from_user.id
    direction = "pl_ru" if cb.data == "quiz_pl_ru" else "ru_pl"

    words = random.sample(list(trainer.vocabulary.items()),
                          min(5, len(trainer.vocabulary)))
    trainer.quiz_sessions[uid] = {
        "words": words,
        "current_question": 0,
        "score": 0,
        "total": len(words),
        "direction": direction
    }
    await ask_question(cb.message, uid, state)


async def ask_question(msg: Message, uid: int, state: FSMContext):
    sess = trainer.quiz_sessions.get(uid)
    if not sess:
        return
    i = sess["current_question"]
    if i >= sess["total"]:
        await finish_quiz(msg, uid)
        return

    pl, ru = sess["words"][i]
    if sess["direction"] == "pl_ru":
        question = f"Co znaczy po rosyjsku: «{pl}»?"
        correct = ru
        display = pl
    else:
        question = f"Jak będzie po polsku: «{ru}»?"
        correct = pl
        display = ru

    await state.update_data(correct_answer=correct.strip().lower(),
                            display_word=display,
                            user_id=uid)
    await state.set_state(QuizStates.waiting_for_answer)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Pomiń", callback_data="skip_question")],
        [InlineKeyboardButton(text="❌ Zakończ", callback_data="end_quiz")],
    ])
    progress = f"{i+1}/{sess['total']}"
    await msg.answer(f"🎯 Pytanie {progress}\n\n{question}", reply_markup=kb)


@router.message(QuizStates.waiting_for_answer)
async def on_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = data["user_id"]
    sess = trainer.quiz_sessions.get(uid)
    if not sess:
        await message.answer("❌ Brak sesji quizu. Wciśnij «🎯 Quiz».")
        await state.clear()
        return

    user_text = (message.text or "").strip().lower()
    correct = data["correct_answer"]
    display = data["display_word"]

    ok = (user_text == correct)
    if ok:
        sess["score"] += 1
        reply = f"✅ Dobrze! {display} → {correct}"
    else:
        reply = f"❌ Źle. {display} → {correct}"

    trainer.update_user_score(uid, ok)
    sess["current_question"] += 1

    await message.answer(reply)

    if sess["current_question"] >= sess["total"]:
        await finish_quiz(message, uid)
        await state.clear()
    else:
        await ask_question(message, uid, state)


@router.callback_query(F.data == "skip_question")
async def skip_q(cb: CallbackQuery, state: FSMContext):
    await cb.answer("⏭️ Pominięto")
    data = await state.get_data()
    uid = data.get("user_id")
    sess = trainer.quiz_sessions.get(uid)
    if not sess:
        await cb.message.answer("❌ Brak sesji quizu. Wciśnij «🎯 Quiz».")
        await state.clear()
        return
    sess["current_question"] += 1
    if sess["current_question"] >= sess["total"]:
        await finish_quiz(cb.message, uid)
        await state.clear()
    else:
        await ask_question(cb.message, uid, state)


@router.callback_query(F.data == "end_quiz")
async def end_q(cb: CallbackQuery, state: FSMContext):
    await cb.answer("❌ Zakończono")
    data = await state.get_data()
    uid = data.get("user_id")
    if uid in trainer.quiz_sessions:
        del trainer.quiz_sessions[uid]
    await state.clear()
    await cb.message.answer("❌ Quiz zakończony.",
                            reply_markup=get_main_keyboard())


async def finish_quiz(msg: Message, uid: int):
    sess = trainer.quiz_sessions.get(uid)
    if not sess:
        return
    score, total = sess["score"], sess["total"]
    percent = score / total * 100
    trainer.get_user_stats(uid)["quiz_count"] += 1
    del trainer.quiz_sessions[uid]

    text = f"🎉 Wynik: {score}/{total} ({percent:.1f}%)"
    if percent >= 80: text += "\n🌟 Świetnie!"
    elif percent >= 60: text += "\n👍 Dobrze!"
    else: text += "\n📚 Ćwicz dalej!"
    await msg.answer(text, reply_markup=get_main_keyboard())


# ── Случайное слово ───────────────────────────────────────────────────────────
@router.callback_query(F.data == "random")
async def random_word(cb: CallbackQuery):
    pl, ru = random.choice(list(trainer.vocabulary.items()))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Jeszcze jedno", callback_data="random")],
        [
            InlineKeyboardButton(text="🏠 Menu główne",
                                 callback_data="back_to_menu")
        ],
    ])
    await cb.message.edit_text(f"🎲 Losowe słowo:\n\n🇵🇱 {pl} → {ru}",
                               reply_markup=kb)
    await cb.answer()


# ── Прогресс ───────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "progress")
async def progress(cb: CallbackQuery):
    uid = cb.from_user.id
    s = trainer.get_user_stats(uid)
    if s["total_questions"] > 0:
        acc = s["correct_answers"] / s["total_questions"] * 100
        text = (f"📊 Twoje postępy:\n\n"
                f"Pytania: {s['total_questions']}\n"
                f"Poprawnych: {s['correct_answers']}\n"
                f"Skuteczność: {acc:.1f}%\n"
                f"Quizów: {s['quiz_count']}")
    else:
        text = "📊 Brak statystyk. Zrób quiz!"
    await cb.message.edit_text(text, reply_markup=get_main_keyboard())
    await cb.answer()


# ── Регистрация роутера ───────────────────────────────────────────────────────
dp.include_router(router)


# ── Healthcheck веб-сервер для Render ─────────────────────────────────────────
async def healthcheck(request):
    return web.Response(text="OK")


async def start_web_server():
    app = web.Application()
    app.add_routes(
        [web.get("/", healthcheck),
         web.get("/health", healthcheck)])
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info(f"🌐 Web server started on port {port}")


# ── Запуск ────────────────────────────────────────────────────────────────────
async def main():
    logger.info("🚀 Uruchamianie Polish Trainer Bot...")
    asyncio.create_task(start_web_server())  # healthcheck для Render/cron
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
