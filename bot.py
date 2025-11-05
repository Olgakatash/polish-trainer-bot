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
        self.vocabulary: Dict[str, str] = {
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
            "czerwony": "красный",
            "niebieski": "синий",
            "zielony": "зелёный",
            "żółty": "жёлтый",
            "czarny": "чёрный",
            "biały": "белый",
            "różowy": "розовый",
            "fioletowy": "фиолетовый",
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
            "trzydzieści": "тридцать",
            "czterdzieści": "сорок",
            "pięćdziesiąt": "пятьдесят",
            "sześćdziesiąt": "шестьдесят",
            "siedemdziesiąt": "семьдесят",
            "osiemdziesiąt": "восемьдесят",
            "dziewięćdziesiąt": "девяносто",
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
            "jak się masz?": "как дела?",
            "miło mi cię poznać": "приятно познакомиться",
            "nie rozumiem": "я не понимаю",
            "mówisz po angielsku?": "ты говоришь по-английски?",
            "ile to kosztuje?": "сколько это стоит?",
            "gdzie jest toaleta?": "где туалет?",
        }

        self.categories: Dict[str, List[str]] = {
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
                "mówisz po angielsku?", "ile to kosztuje?",
                "gdzie jest toaleta?"
            ],
        }

        self.load_csv_vocabulary()
        self.user_scores: Dict[int, Dict] = {}
        self.quiz_sessions: Dict[int, Dict] = {}

    def load_csv_vocabulary(self):
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
    "podstawy": [
        "powitania", "kolory", "liczby_0_10", "liczby_10_20", "liczby_20_100",
        "liczby_100_1000", "zwroty"
    ],
}

NAMES_PL = {
    "podstawy": "Podstawy",
    "powitania": "Powitania",
    "kolory": "Kolory",
    "zwroty": "Zwroty",
    "liczby_0_10": "Liczby 0–10",
    "liczby_10_20": "Liczby 10–20",
    "liczby_20_100": "Liczby 20–100",
    "liczby_100_1000": "Liczby 100–1000",
}


def icon_for_group(gkey: str) -> str:
    return {"podstawy": "👋"}.get(gkey, "📁")


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


# ── Навигация: «Ucz się słówek» ───────────────────────────────────────────────
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


# ── Просмотр категорий (без экспорта) ─────────────────────────────────────────
@router.callback_query(F.data.startswith("cat_"))
async def show_category(cb: CallbackQuery):
    key = cb.data.replace("cat_", "")
    lst = trainer.categories.get(key, [])
    pairs = [(w, trainer.vocabulary[w]) for w in lst
             if w in trainer.vocabulary]
    cat_name = NAMES_PL.get(key, key.capitalize())

    if not pairs:
        await cb.message.edit_text("❌ W tej kategorii na razie nie ma słów.",
                                   reply_markup=get_main_keyboard())
        await cb.answer()
        return

    text_lines = [f"📚 <b>{cat_name}</b>\n"]
    for pl, ru in pairs:
        text_lines.append(f"🇵🇱 <code>{pl}</code> → {ru}")
    text = "\n".join(text_lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Grupy", callback_data="nav_learn")],
        [
            InlineKeyboardButton(text="🏠 Menu główne",
                                 callback_data="back_to_menu")
        ],
    ])
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


# ── Остальной функционал: квизы, статистика и т.д. ────────────────────────────
# (оставь свой прежний код quiz_entry, quiz_start, ask_question, on_answer, skip_q, end_q, finish_quiz,
#  random_word, progress, healthcheck, main и т.д. — он без изменений)
