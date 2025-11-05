#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import csv
import glob
import logging
import os
import random
import unicodedata
from io import BytesIO, StringIO
from typing import Dict, List, Tuple

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (BufferedInputFile, CallbackQuery,
                           InlineKeyboardButton, InlineKeyboardMarkup, Message)
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

PAGE_SIZE = 12  # пагинация списков при просмотре


# ── Вспомогательные функции (диакритики, числа, сортировка) ──────────────────
def _strip_accents(s: str) -> str:
    s = (s or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


# PL числительные → число (для ответов цифрами)
_NUM_WORD = {
    "zero": 0,
    "jeden": 1,
    "dwa": 2,
    "trzy": 3,
    "cztery": 4,
    "piec": 5,
    "pięć": 5,
    "szesc": 6,
    "sześć": 6,
    "siedem": 7,
    "osiem": 8,
    "dziewiec": 9,
    "dziewięć": 9,
    "dziesiec": 10,
    "dziesięć": 10,
    "jedenascie": 11,
    "jedenaście": 11,
    "dwanascie": 12,
    "dwanaście": 12,
    "trzynascie": 13,
    "trzynaście": 13,
    "czternascie": 14,
    "czternaście": 14,
    "pietnascie": 15,
    "piętnaście": 15,
    "szesnascie": 16,
    "szesnaście": 16,
    "siedemnascie": 17,
    "siedemnaście": 17,
    "osiemnascie": 18,
    "osiemnaście": 18,
    "dziewietnascie": 19,
    "dziewiętnaście": 19,
    "dwadziescia": 20,
    "dwadzieścia": 20,
    "trzydziesci": 30,
    "trzydzieści": 30,
    "czterdziesci": 40,
    "czterdzieści": 40,
    "piecdziesiat": 50,
    "pięćdziesiąt": 50,
    "szescdziesiat": 60,
    "sześćdziesiąt": 60,
    "siedemdziesiat": 70,
    "siedemdziesiąt": 70,
    "osiemdziesiat": 80,
    "osiemdziesiąt": 80,
    "dziewiecdziesiat": 90,
    "dziewięćdziesiąt": 90,
    "sto": 100,
    "dwiescie": 200,
    "dwieście": 200,
    "trzysta": 300,
    "czterysta": 400,
    "piecset": 500,
    "pięćset": 500,
    "szescset": 600,
    "sześćset": 600,
    "siedemset": 700,
    "osiemset": 800,
    "dziewiecset": 900,
    "dziewięćset": 900,
    "tysiac": 1000,
    "tysiąc": 1000,
}


def _word_to_number_pl(s: str):
    t = _strip_accents(s)
    if t in _NUM_WORD:
        return _NUM_WORD[t]
    parts = [p for p in t.split() if p]
    if not parts:
        return None
    total = 0
    for p in parts:
        if p in _NUM_WORD:
            total += _NUM_WORD[p]
        else:
            return None
    return total if total else None


def valid_answers_pl(expected_pl: str) -> List[str]:
    """Валидные польские ответы: слово (с/без диакритик) + цифры (если числит.)."""
    answers = {expected_pl}
    nodiac = _strip_accents(expected_pl)
    if nodiac != expected_pl.lower():
        answers.add(nodiac)
    n = _word_to_number_pl(expected_pl)
    if n is not None:
        answers.add(str(n))
    return sorted(answers, key=_strip_accents)


def equals_relaxed(user_text: str, valid: List[str]) -> bool:
    t = _strip_accents(user_text)
    return t in {_strip_accents(v) for v in valid}


def sort_categories_alphabetically(categories: Dict[str, List[str]]):
    """Сортируем слова в каждой категории по польскому алфавиту (без диакритик для стабильности)."""
    for key, words in categories.items():
        categories[key] = sorted(list(set(words)),
                                 key=lambda w: _strip_accents(w))


def paginate(items: List, page: int, page_size: int = PAGE_SIZE):
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    page = page % total_pages
    start = page * page_size
    return items[start:start + page_size], page, total_pages


# ── Состояния ─────────────────────────────────────────────────────────────────
class QuizStates(StatesGroup):
    waiting_for_answer = State()


class ImportStates(StatesGroup):
    waiting_csv_for_category = State()


# ── Модель бота ───────────────────────────────────────────────────────────────
class PolishTrainerBot:

    def __init__(self):
        # Базовая лексика (pl → ru)
        self.vocabulary: Dict[str, str] = {
            # Powitania
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

        # Категории
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
                "siedemdziesiąt", "osiемdziesiąt", "dziewięćdziesiąt"
            ],
            "liczby_100_1000": [
                "sto", "dwieście", "trzysta", "czterysta", "pięćсet",
                "sześćset", "siedemset", "osiemset", "dziewięćset", "tysiąc"
            ],
            "zwroty": [
                "jak się masz?", "miło mi cię poznać", "nie rozumiem",
                "mówisz po angielsku?", "ile to kosztuje?",
                "gdzie jest toaleta?"
            ],
        }

        # Подтягиваем все CSV из data/
        self.load_csv_vocabulary()

        # Сортировка слов внутри категорий по алфавиту
        sort_categories_alphabetically(self.categories)

        # Статистика/сессии/настройки
        self.user_scores: Dict[int, Dict] = {}
        self.quiz_sessions: Dict[int,
                                 Dict] = {}  # per-user: pool, direction, etc.
        self.user_prefs: Dict[int, Dict] = {}  # per-user: quiz_len

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

    def get_user_prefs(self, user_id: int) -> Dict:
        if user_id not in self.user_prefs:
            self.user_prefs[user_id] = {'quiz_len': 10}
        return self.user_prefs[user_id]

    def flat_items(self, pool_keys: List[str] = None) -> List[Tuple[str, str]]:
        """Собираем пары (pl, ru). Если pool_keys=None — все слова; иначе только из указанных категорий."""
        items = []
        if pool_keys:
            for ck in pool_keys:
                for w in self.categories.get(ck, []):
                    if w in self.vocabulary:
                        items.append((w, self.vocabulary[w]))
        else:
            for w, ru in self.vocabulary.items():
                items.append((w, ru))
        return items


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
    "jedzenie": [
        "jedzenie_owoce", "jedzenie_warzywa", "jedzenie_mieso",
        "jedzenie_ryby", "jedzenie_nabial", "jedzenie_pieczywo",
        "jedzenie_napoje", "jedzenie_slodycze", "jedzenie_przyprawy"
    ],
    "rutyna": ["rutyna"],
    "rodzina": ["rodzina", "semya"],
    "czas_wolny": ["czas_wolny"],
    "mieszkanie": ["mieszkanie"],
}

NAMES_PL = {
    "podstawy": "Podstawy",
    "jedzenie": "Jedzenie",
    "rutyna": "Rutyna",
    "rodzina": "Rodzina",
    "czas_wolny": "Czas wolny",
    "mieszkanie": "Mieszkanie",
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
        [
            InlineKeyboardButton(text="⬇️ Eksport (ALL CSV)",
                                 callback_data="export_all")
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


def get_group_categories_keyboard(
        group_key: str,
        with_train_buttons: bool = False) -> InlineKeyboardMarkup:
    rows = []
    cats = [
        c for c in GROUPS.get(group_key, [])
        if c in trainer.categories and trainer.categories[c]
    ]
    for ckey in cats:
        if with_train_buttons:
            rows.append([
                InlineKeyboardButton(
                    text=f"📂 {NAMES_PL.get(ckey, ckey.capitalize())}",
                    callback_data=f"train_pick_cat:{ckey}")
            ])
        else:
            rows.append([
                InlineKeyboardButton(
                    text=f"📂 {NAMES_PL.get(ckey, ckey.capitalize())}",
                    callback_data=f"browse_cat:{group_key}:{ckey}:0")
            ])
    rows.append(
        [InlineKeyboardButton(text="🔙 Wróć", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_train_scope(uid: int):
    ql = trainer.get_user_prefs(uid)['quiz_len']
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"🧠 Wszystkie słowa (len={ql})",
                                 callback_data="train_scope:all")
        ],
        [
            InlineKeyboardButton(text=f"🎯 Wybierz kategorię (len={ql})",
                                 callback_data="train_scope:bycat")
        ],
        [
            InlineKeyboardButton(text="Len: 5", callback_data="set_ql:5"),
            InlineKeyboardButton(text="10", callback_data="set_ql:10"),
            InlineKeyboardButton(text="20", callback_data="set_ql:20")
        ],
        [InlineKeyboardButton(text="🔙 Wróć", callback_data="back_to_menu")],
    ])


def kb_direction():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇵🇱 → 🇷🇺", callback_data="quiz_pl_ru")],
        [InlineKeyboardButton(text="🇷🇺 → 🇵🇱", callback_data="quiz_ru_pl")],
        [InlineKeyboardButton(text="🔙 Wróć", callback_data="nav_train")],
    ])


def kb_pagination(group_key: str, ckey: str, page: int, total: int):
    prev_p = (page - 1) % total
    next_p = (page + 1) % total
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="⏮",
                callback_data=f"browse_cat:{group_key}:{ckey}:{prev_p}"),
            InlineKeyboardButton(text=f"{page+1}/{total}",
                                 callback_data="noop"),
            InlineKeyboardButton(
                text="⏭",
                callback_data=f"browse_cat:{group_key}:{ckey}:{next_p}")
        ],
    ])


def kb_cat_nav(group_key: str, cats: List[str], current: str):
    i = cats.index(current)
    prev_c = cats[i - 1] if i > 0 else cats[-1]
    next_c = cats[i + 1] if i < len(cats) - 1 else cats[0]
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="◀️", callback_data=f"browse_cat:{group_key}:{prev_c}:0"),
            InlineKeyboardButton(text=f"{NAMES_PL.get(current, current)}",
                                 callback_data="noop"),
            InlineKeyboardButton(
                text="▶️", callback_data=f"browse_cat:{group_key}:{next_c}:0")
        ],
        [
            InlineKeyboardButton(text="🔙 Wróć",
                                 callback_data=f"browse_group:{group_key}")
        ],
    ])


def kb_category_actions(group_key: str, ckey: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧠 Trenuj tę kategorię",
                                 callback_data=f"train_cat:{ckey}")
        ],
        [
            InlineKeyboardButton(text="⬇️ Eksport CSV",
                                 callback_data=f"export_cat:{ckey}")
        ],
        [
            InlineKeyboardButton(text="⬆️ Import CSV do kategorii",
                                 callback_data=f"import_cat:{ckey}")
        ],
        [
            InlineKeyboardButton(text="🔙 Wróć",
                                 callback_data=f"browse_group:{group_key}")
        ],
    ])


# ── Старт и меню ──────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
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


# ── Ucz się słówek ───────────────────────────────────────────────────────────
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


# ── Tryb treningowy: выбор области и длины ────────────────────────────────────
@router.callback_query(F.data == "nav_train")
async def nav_train(cb: CallbackQuery, state: FSMContext):
    prefs = trainer.get_user_prefs(cb.from_user.id)
    await state.update_data(train_pool=None, train_cats=None)
    await cb.message.edit_text("🎯 <b>Tryb treningowy</b>\nWybierz zakres:",
                               reply_markup=kb_train_scope(cb.from_user.id),
                               parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("set_ql:"))
async def set_quiz_len(cb: CallbackQuery):
    val = int(cb.data.split(":", 1)[1])
    prefs = trainer.get_user_prefs(cb.from_user.id)
    prefs['quiz_len'] = val
    await cb.message.edit_text("🎯 <b>Tryb treningowy</b>\nDługość ustawiona.",
                               reply_markup=kb_train_scope(cb.from_user.id),
                               parse_mode="HTML")
    await cb.answer(f"✅ {val} pytań")


@router.callback_query(F.data.startswith("train_scope:"))
async def choose_train_scope(cb: CallbackQuery, state: FSMContext):
    scope = cb.data.split(":", 1)[1]
    if scope == "all":
        await state.update_data(train_cats=None)
        await cb.message.edit_text("Wybierz kierunek quizu:",
                                   reply_markup=kb_direction())
    else:
        # выбрать категорию в режиме тренировки
        await cb.message.edit_text("🎯 Wybierz grupę kategorii:",
                                   reply_markup=get_group_categories_keyboard(
                                       "podstawy", with_train_buttons=True))
        # покажем не только podstawy — отрендерим все группы с train-переходом
        rows = []
        kb = []
        for g in GROUPS.keys():
            kb.append([
                InlineKeyboardButton(
                    text=f"{icon_for_group(g)} {NAMES_PL.get(g,g)}",
                    callback_data=f"train_group:{g}")
            ])
        kb.append(
            [InlineKeyboardButton(text="🔙 Wróć", callback_data="nav_train")])
        await cb.message.edit_text(
            "🎯 Wybierz grupę:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()


@router.callback_query(F.data.startswith("train_group:"))
async def train_group(cb: CallbackQuery):
    g = cb.data.split(":", 1)[1]
    await cb.message.edit_text(f"🎯 {NAMES_PL.get(g,g)} — wybierz kategorię:",
                               reply_markup=get_group_categories_keyboard(
                                   g, with_train_buttons=True))
    await cb.answer()


@router.callback_query(F.data.startswith("train_pick_cat:"))
async def train_pick_cat(cb: CallbackQuery, state: FSMContext):
    ckey = cb.data.split(":", 1)[1]
    await state.update_data(train_cats=[ckey])
    await cb.message.edit_text(
        f"🧠 {NAMES_PL.get(ckey, ckey)} — wybierz kierunek quizu:",
        reply_markup=kb_direction())
    await cb.answer()


# ── Просмотр с пагинацией/стрелками и действиями категории ───────────────────
@router.callback_query(F.data == "nav_browse")
async def nav_browse(cb: CallbackQuery):
    kb = []
    for g in GROUPS.keys():
        kb.append([
            InlineKeyboardButton(
                text=f"{icon_for_group(g)} {NAMES_PL.get(g,g)}",
                callback_data=f"browse_group:{g}")
        ])
    kb.append(
        [InlineKeyboardButton(text="🔙 Wróć", callback_data="back_to_menu")])
    await cb.message.edit_text(
        "🔎 <b>Przeglądaj</b>\n\nWybierz grupę:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("browse_group:"))
async def browse_group(cb: CallbackQuery):
    g = cb.data.split(":", 1)[1]
    await cb.message.edit_text(
        f"🔎 <b>{NAMES_PL.get(g,g)}</b>\nWybierz kategorię:",
        reply_markup=get_group_categories_keyboard(g),
        parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("browse_cat:"))
async def browse_cat(cb: CallbackQuery):
    _, group_key, ckey, page_s = cb.data.split(":")
    page = int(page_s)
    words = trainer.categories.get(ckey, [])
    items = [(w, trainer.vocabulary[w]) for w in words
             if w in trainer.vocabulary]
    if not items:
        await cb.message.edit_text(
            "❌ Pusto.", reply_markup=get_group_categories_keyboard(group_key))
        return await cb.answer()

    total_pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = page % total_pages
    chunk, page, total_pages = paginate(items, page, PAGE_SIZE)

    lines = [f"📃 <b>{NAMES_PL.get(ckey, ckey)}</b> — razem {len(items)}"]
    for pl, ru in chunk:
        extra_digits = [x for x in valid_answers_pl(pl) if x.isdigit()]
        tail = f" • dop.: {', '.join(extra_digits)}" if extra_digits else ""
        lines.append(f"• <b>{pl}</b> — {ru}{tail}")

    cats_in_group = [
        c for c in GROUPS.get(group_key, [])
        if c in trainer.categories and trainer.categories[c]
    ]
    merged = InlineKeyboardMarkup(
        inline_keyboard=kb_pagination(group_key, ckey, page,
                                      total_pages).inline_keyboard +
        kb_cat_nav(group_key, cats_in_group, ckey).inline_keyboard +
        kb_category_actions(group_key, ckey).inline_keyboard)
    await cb.message.edit_text("\n".join(lines),
                               reply_markup=merged,
                               parse_mode="HTML")
    await cb.answer()


# ── Экспорт CSV ───────────────────────────────────────────────────────────────
@router.callback_query(F.data == "export_all")
async def export_all(cb: CallbackQuery):
    # один CSV "all_words.csv": pl;ru
    out = StringIO()
    writer = csv.writer(out, delimiter=";")
    for pl, ru in sorted(trainer.vocabulary.items(),
                         key=lambda x: _strip_accents(x[0])):
        writer.writerow([pl, ru])
    data = out.getvalue().encode("utf-8")
    await bot.send_document(cb.message.chat.id,
                            document=BufferedInputFile(
                                data, filename="all_words.csv"),
                            caption="⬇️ Wszystkie słowa (CSV)")
    await cb.answer("Gotowe!")


@router.callback_query(F.data.startswith("export_cat:"))
async def export_cat(cb: CallbackQuery):
    ckey = cb.data.split(":", 1)[1]
    words = trainer.categories.get(ckey, [])
    items = [(w, trainer.vocabulary[w]) for w in words
             if w in trainer.vocabulary]
    if not items:
        await cb.answer("Pusto.", show_alert=True)
        return
    out = StringIO()
    writer = csv.writer(out, delimiter=";")
    for pl, ru in items:
        writer.writerow([pl, ru])
    data = out.getvalue().encode("utf-8")
    fname = f"{ckey}.csv"
    await bot.send_document(cb.message.chat.id,
                            document=BufferedInputFile(data, filename=fname),
                            caption=f"⬇️ {NAMES_PL.get(ckey, ckey)} (CSV)")
    await cb.answer("Wyeksportowano.")


# ── Импорт CSV в выбранную категорию ─────────────────────────────────────────
@router.callback_query(F.data.startswith("import_cat:"))
async def import_cat(cb: CallbackQuery, state: FSMContext):
    ckey = cb.data.split(":", 1)[1]
    await state.update_data(import_category=ckey)
    await state.set_state(ImportStates.waiting_csv_for_category)
    await cb.message.answer(
        f"⬆️ Wyślij plik CSV dla kategorii <b>{NAMES_PL.get(ckey, ckey)}</b>.\n"
        "Format: <code>polskie;rosyjskie</code> w każdej linii.",
        parse_mode="HTML")
    await cb.answer("Czekam na CSV…")


@router.message(ImportStates.waiting_csv_for_category)
async def on_import_csv(message: Message, state: FSMContext):
    if not message.document or not (message.document.file_name
                                    or "").lower().endswith(".csv"):
        await message.answer("❌ Wyślij proszę plik .csv (UTF-8, separator ;)")
        return
    data = await state.get_data()
    ckey = data.get("import_category")
    file_info = await bot.get_file(message.document.file_id)
    buf = BytesIO()
    await bot.download(file_info, buf)
    buf.seek(0)
    text = buf.read().decode("utf-8", errors="ignore")
    reader = csv.reader(StringIO(text), delimiter=";")

    added, updated = 0, 0
    if ckey not in trainer.categories:
        trainer.categories[ckey] = []

    for row in reader:
        if len(row) >= 2:
            pl = (row[0] or "").strip()
            ru = (row[1] or "").strip()
            if not pl or not ru:
                continue
            if pl in trainer.vocabulary:
                if trainer.vocabulary[pl] != ru:
                    trainer.vocabulary[pl] = ru
                    updated += 1
            else:
                trainer.vocabulary[pl] = ru
                trainer.categories[ckey].append(pl)
                added += 1

    # алфавит + дубликаты
    sort_categories_alphabetically(trainer.categories)
    await state.clear()
    await message.answer(
        f"✅ Import zakończony: dodano {added}, zaktualizowano {updated}.\n"
        f"Kategoria: <b>{NAMES_PL.get(ckey, ckey)}</b>",
        parse_mode="HTML")


# ── ВИКТОРИНА: выбор направления, старт и проверка ───────────────────────────
@router.callback_query((F.data == "quiz_pl_ru") | (F.data == "quiz_ru_pl"))
async def quiz_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    uid = cb.from_user.id
    direction = "pl_ru" if cb.data == "quiz_pl_ru" else "ru_pl"

    data = await state.get_data()
    pool_keys: List[str] = data.get("train_cats")  # None => все слова
    words = trainer.flat_items(pool_keys)
    if not words:
        await cb.message.answer("❌ Brak słów w wybranym zakresie.")
        return

    prefs = trainer.get_user_prefs(uid)
    quiz_len = min(prefs.get('quiz_len', 10), len(words))
    random.shuffle(words)
    words = words[:quiz_len]

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
    if not sess: return
    i = sess["current_question"]
    if i >= sess["total"]:
        await finish_quiz(msg, uid)
        return

    pl, ru = sess["words"][i]
    if sess["direction"] == "pl_ru":
        # Польское → по-русски. Разрешим цифры для числительных ИЛИ точный перевод.
        question = f"Co znaczy po rosyjsku: «{pl}»?"
        valid = [ru] + [x for x in valid_answers_pl(pl) if x.isdigit()]
    else:
        # Русское → по-польски. Разрешим слово, без диакритик и цифры.
        question = f"Jak będzie po polsku: «{ru}»?"
        valid = valid_answers_pl(pl)

    await state.update_data(correct_answer_list=valid, user_id=uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Pomiń", callback_data="skip_question")],
        [InlineKeyboardButton(text="❌ Zakończ", callback_data="end_quiz")],
    ])
    progress = f"{i+1}/{sess['total']}"
    await msg.answer(f"🎯 Pytanie {progress}\n\n{question}", reply_markup=kb)


@router.message(QuizStates.waiting_for_answer)
async def on_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("user_id")
    sess = trainer.quiz_sessions.get(uid)
    if not sess:
        await message.answer("❌ Brak sesji quizu. Wciśnij «🎯 Tryb treningowy»."
                             )
        await state.clear()
        return

    user_text = (message.text or "").strip()
    valid: List[str] = data.get("correct_answer_list", [])

    ok = equals_relaxed(user_text, valid)
    trainer.update_user_score(uid, ok)

    if ok:
        sess["score"] += 1
        await message.answer("✅ Dobrze!")
    else:
        hint = ", ".join(sorted(set(valid), key=_strip_accents))
        await message.answer(f"❌ Źle.\nPodpowiedź: <b>{hint}</b>",
                             parse_mode="HTML")

    sess["current_question"] += 1
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
        await cb.message.answer("❌ Brak sesji quizu.")
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
    if not sess: return
    score, total = sess["score"], sess["total"]
    percent = score / total * 100 if total else 0.0
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
