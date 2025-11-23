#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import csv
import glob
import logging
import os
import random
import unicodedata
from typing import Dict, List, Tuple, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv
from aiohttp import web  # healthcheck

# ── Настройки ─────────────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN обязателен: добавь его в Secrets/Env.")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # твой Telegram ID, если задан

PAGE_SIZE = 12  # для пагинации в «Ucz się słówek»


# ── Утилиты ──────────────────────────────────────────────────────────────────
def _strip_accents(s: str) -> str:
    s = (s or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


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


def _word_to_number_pl(s: str) -> Optional[int]:
    t = _strip_accents(s)
    if t in _NUM_WORD:
        return _NUM_WORD[t]
    total = 0
    for part in t.split():
        if part in _NUM_WORD:
            total += _NUM_WORD[part]
        else:
            return None
    return total or None


def valid_answers_pl(expected_pl: str) -> List[str]:
    """Список допустимых ответов: слово + вариант без диакритик + цифры, если числительное."""
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


def paginate(items: List, page: int, page_size: int = PAGE_SIZE):
    total = max(1, (len(items) + page_size - 1) // page_size)
    page = page % total
    start = page * page_size
    return items[start:start + page_size], page, total


# ── FSM ───────────────────────────────────────────────────────────────────────
class QuizStates(StatesGroup):
    waiting_for_answer = State()


class FeedbackStates(StatesGroup):
    waiting_for_feedback = State()


# ── Модель данных ─────────────────────────────────────────────────────────────
class PolishTrainerBot:

    def __init__(self):
        # Базовый словарь: «зашитые» слова (на случай, если CSV нет).
        self.vocabulary: Dict[str, str] = {
            # Powitania (порядок задаём в categories)
            "dzień dobry": "добрый день",
            "dobry wieczór": "добрый вечер",
            "cześć": "привет/пока",
            "do widzenia": "до свидания",
            "na razie": "пока",
            "pa": "пока",
            "dziękuję": "спасибо",
            "proszę": "пожалуйста",
            "przepraszam": "извините",
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

            # Liczby
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

            # Zwroty
            "jak się masz?": "как дела?",
            "miło mi cię poznać": "приятно познакомиться",
            "nie rozumiem": "я не понимаю",
            "mówisz po angielsku?": "ты говоришь по-английски?",
            "ile to kosztuje?": "сколько это стоит?",
            "gdzie jest toaleta?": "где туалет?",

            # Ubrania
            "koszulka": "футболка",
            "koszula": "рубашка",
            "spodnie": "штаны",
            "dżinsy": "джинсы",
            "spódnica": "юбка",
            "sukienka": "платье",
            "sweter": "свитер",
            "bluza": "толстовка",
            "kurtka": "куртка",
            "płaszcz": "пальто",
            "buty": "обувь",
            "buty sportowe": "кроссовки",
            "czapka": "шапка",
            "szalik": "шарф",
            "rękawiczki": "перчатки",

            # Sport
            "piłka nożna": "футбол",
            "koszykówka": "баскетбол",
            "siatkówka": "волейбол",
            "tenis": "теннис",
            "pływanie": "плавание",
            "bieganie": "бег",
            "jazda na rowerze": "езда на велосипеде",
            "narciarstwo": "лыжный спорт",
            "łyżwiarstwo": "катание на коньках",
            "joga": "йога",
            "gimnastyka": "гимнастика",
            "sporty siłowe": "силовые виды спорта",
        }

        # Категории по умолчанию
        self.categories: Dict[str, List[str]] = {
            "powitania": [
                "dzień dobry", "dobry wieczór", "cześć", "do widzenia",
                "na razie", "pa", "dziękuję", "proszę", "przepraszam", "tak",
                "nie"
            ],
            "kolory": [
                "czerwony", "niebieski", "zielony", "żółty", "czarny", "biały",
                "różowy", "fioletowy"
            ],
            "liczby_0_10": [
                "jeden", "dwa", "трzy", "trzy", "cztery", "pięć", "sześć",
                "siedem", "osiem", "dziewięć", "dziesięć"
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
            "ubrania": [
                "koszulka", "koszula", "spodnie", "dżinsy", "spódnica",
                "sukienka", "sweter", "bluza", "kurtka", "płaszcz", "buty",
                "buty sportowe", "czapka", "szalik", "rękawiczki"
            ],
            "sport": [
                "piłka nożna", "koszykówka", "siatkówka", "tenis", "pływanie",
                "bieganie", "jazda na rowerze", "narciarstwo", "łyżwiarstwo",
                "joga", "gimnastyka", "sporty siłowe"
            ],
        }

        # Подтягиваем CSV, которые расширяют/перезаписывают словарь
        self.load_csv_vocabulary()

        # Сортируем категории (кроме powitania, где порядок смысловой)
        for k, lst in self.categories.items():
            if k == "powitania":
                # оставляем заданный порядок, но убираем дубли
                seen = []
                for w in lst:
                    if w not in seen:
                        seen.append(w)
                self.categories[k] = seen
            else:
                self.categories[k] = sorted(list(dict.fromkeys(lst)),
                                            key=_strip_accents)

        self.user_scores: Dict[int, Dict] = {}
        self.quiz_sessions: Dict[int, Dict] = {}

    # ── CSV ────────────────────────────────────────────────────────────────
    def load_csv_vocabulary(self):
        """
        Подгружаем все CSV из папки data/.

        Форматы:
        1) Новый общий файл data/slownik.csv:
           kategoria;pl;ru

        2) Старые файлы по категориям (powitania.csv, rodzina.csv...):
           pl;ru
           Имя файла (без .csv) = ключ категории.
        """
        try:
            files = glob.glob("data/*.csv")
            if not files:
                logger.warning(
                    "В папке data/ нет CSV. Используются только 'зашитые' слова."
                )
                return

            for path in files:
                base = os.path.splitext(os.path.basename(path))[0].lower()

                # 1) Новый формат — один общий словарь
                if base == "slownik":
                    with open(path, "r", encoding="utf-8") as f:
                        reader = csv.reader(f, delimiter=";")
                        header_checked = False
                        for row in reader:
                            if not row:
                                continue
                            if not header_checked:
                                header_checked = True
                                if row[0].strip().lower() == "kategoria":
                                    # это заголовок
                                    continue
                            if len(row) < 3:
                                continue
                            cat = (row[0] or "").strip()
                            pl = (row[1] or "").strip()
                            ru = (row[2] or "").strip()
                            if not (cat and pl and ru):
                                continue
                            self.vocabulary[pl] = ru
                            self.categories.setdefault(cat, []).append(pl)

                # 2) Старый формат — отдельный CSV на категорию
                else:
                    cat_key = base
                    with open(path, "r", encoding="utf-8") as f:
                        reader = csv.reader(f, delimiter=";")
                        for row in reader:
                            if len(row) < 2:
                                continue
                            pl = (row[0] or "").strip()
                            ru = (row[1] or "").strip()
                            if not (pl and ru):
                                continue
                            self.vocabulary[pl] = ru
                            self.categories.setdefault(cat_key, []).append(pl)

            logger.info(
                f"✅ CSV загружены. Категорий: {len(self.categories)}, слов: {len(self.vocabulary)}"
            )
        except Exception as e:
            logger.error(f"Ошибка при загрузке CSV: {e}")

    # ── Статы ─────────────────────────────────────────────────────────────
    def get_user_stats(self, user_id: int) -> Dict:
        if user_id not in self.user_scores:
            self.user_scores[user_id] = {
                "total_questions": 0,
                "correct_answers": 0,
                "quiz_count": 0,
            }
        return self.user_scores[user_id]

    def update_user_score(self, user_id: int, is_correct: bool):
        s = self.get_user_stats(user_id)
        s["total_questions"] += 1
        if is_correct:
            s["correct_answers"] += 1

    def flat_items(
            self,
            pool_keys: Optional[List[str]] = None) -> List[Tuple[str, str]]:
        items: List[Tuple[str, str]] = []
        if pool_keys:
            for ck in pool_keys:
                for w in self.categories.get(ck, []):
                    if w in self.vocabulary:
                        items.append((w, self.vocabulary[w]))
        else:
            items = list(self.vocabulary.items())
        items.sort(key=lambda x: _strip_accents(x[0]))
        return items


# ── Инициализация бота ────────────────────────────────────────────────────────
trainer = PolishTrainerBot()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# ── Группы и названия ─────────────────────────────────────────────────────────
GROUPS = {
    "podstawy": [
        "powitania",
        "kolory",
        "liczby_0_10",
        "liczby_10_20",
        "liczby_20_100",
        "liczby_100_1000",
        "zwroty",
    ],
    "jedzenie": [
        "jedzenie_owoce",
        "jedzenie_warzywa",
        "jedzenie_mieso",
        "jedzenie_ryby",
        "jedzenie_nabial",
        "jedzenie_pieczywo",
        "jedzenie_napoje",
        "jedzenie_slodycze",
        "jedzenie_przyprawy",
    ],
    "rutyna": ["rutyna"],
    "rodzina": ["rodzina", "semya"],
    "czas_wolny": ["czas_wolny"],
    "mieszkanie": ["mieszkanie"],
    "ubrania_group": ["ubrania"],
    "sport_group": ["sport"],
}

NAMES_PL = {
    "podstawy": "Podstawy",
    "jedzenie": "Jedzenie",
    "rutyna": "Rutyna",
    "rodzina": "Rodzina",
    "czas_wolny": "Czas wolny",
    "mieszkanie": "Mieszkanie",
    "ubrania_group": "Ubrania",
    "sport_group": "Sport",
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
    "rodzina": "Rodzina",
    "semya": "Rodzina",
    "czas_wolny": "Czas wolny",
    "mieszkanie": "Mieszkanie",
    "ubrania": "Ubrania",
    "sport": "Sport",
}


def icon_for_group(gkey: str) -> str:
    return {
        "podstawy": "👋",
        "jedzenie": "🍽️",
        "rodzina": "👨‍👩‍👧‍👦",
        "rutyna": "🕒",
        "czas_wolny": "🎯",
        "mieszkanie": "🏠",
        "ubrania_group": "👕",
        "sport_group": "🏀",
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
        [InlineKeyboardButton(text="🎲 Losowe słowo", callback_data="random")],
        [InlineKeyboardButton(text="📊 Postępy", callback_data="progress")],
        [
            InlineKeyboardButton(text="Обратная связь",
                                 callback_data="feedback")
        ],
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
                callback_data=f"learn_group:{gkey}",
            )
        ])
    rows.append(
        [InlineKeyboardButton(text="🔙 Wróć", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_group_categories_keyboard_learn(
        group_key: str) -> InlineKeyboardMarkup:
    rows = []
    for ckey in GROUPS.get(group_key, []):
        if ckey in trainer.categories and trainer.categories[ckey]:
            rows.append([
                InlineKeyboardButton(
                    text=f"📂 {NAMES_PL.get(ckey, ckey.capitalize())}",
                    callback_data=f"learn_cat:{group_key}:{ckey}:0",
                )
            ])
    rows.append(
        [InlineKeyboardButton(text="🔙 Wróć", callback_data="nav_learn")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_learn_pagination(group_key: str, ckey: str, page: int, total: int,
                        cats_in_group: List[str]) -> InlineKeyboardMarkup:
    prev_p = (page - 1) % total
    next_p = (page + 1) % total

    i = cats_in_group.index(ckey)
    prev_c = cats_in_group[i - 1] if i > 0 else cats_in_group[-1]
    next_c = cats_in_group[
        i + 1] if i < len(cats_in_group) - 1 else cats_in_group[0]

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="◀️", callback_data=f"learn_cat:{group_key}:{prev_c}:0"),
            InlineKeyboardButton(text=f"{NAMES_PL.get(ckey, ckey)}",
                                 callback_data="noop"),
            InlineKeyboardButton(
                text="▶️", callback_data=f"learn_cat:{group_key}:{next_c}:0"),
        ],
        [
            InlineKeyboardButton(
                text="⏮",
                callback_data=f"learn_cat:{group_key}:{ckey}:{prev_p}"),
            InlineKeyboardButton(text=f"{page+1}/{total}",
                                 callback_data="noop"),
            InlineKeyboardButton(
                text="⏭",
                callback_data=f"learn_cat:{group_key}:{ckey}:{next_p}"),
        ],
        [
            InlineKeyboardButton(text="🔙 Wróć",
                                 callback_data=f"learn_group:{group_key}")
        ],
    ])


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
async def back_to_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("🏠 Menu główne\n\nWybierz opcję:",
                               reply_markup=get_main_keyboard())
    await cb.answer()


# ── Обратная связь ───────────────────────────────────────────────────────────
@router.callback_query(F.data == "feedback")
async def feedback_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(FeedbackStates.waiting_for_feedback)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data="feedback_cancel")
    ]])
    await cb.message.edit_text(
        "💬 Напиши, пожалуйста, своё сообщение.\n"
        "Это может быть отзыв, идея или пожелание.\n\n"
        "Чтобы отменить, нажми «Отмена».",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data == "feedback_cancel")
async def feedback_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("🏠 Возврат в меню.",
                               reply_markup=get_main_keyboard())
    await cb.answer("Отменено")


@router.message(FeedbackStates.waiting_for_feedback)
async def feedback_receive(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "Сообщение пустое. Напиши, пожалуйста, текст или нажми /start, чтобы выйти."
        )
        return

    await message.answer("Спасибо! 💌 Сообщение отправлено Оле.",
                         reply_markup=get_main_keyboard())
    await state.clear()

    if ADMIN_ID:
        user = message.from_user
        uname = f"@{user.username}" if user and user.username else "(без username)"
        info = ("📩 Новое сообщение обратной связи\n"
                f"От: {user.full_name if user else ''} {uname}\n"
                f"ID: {user.id if user else '—'}\n\n"
                f"{text}")
        try:
            await bot.send_message(ADMIN_ID, info)
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение админу: {e}")


# ── Ucz się słówek ────────────────────────────────────────────────────────────
@router.callback_query(F.data == "nav_learn")
async def nav_learn(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(
        "📖 <b>Ucz się słówek</b>\n\nWybierz grupę:",
        reply_markup=get_groups_keyboard(),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("learn_group:"))
async def nav_learn_group(cb: CallbackQuery):
    g = cb.data.split(":", 1)[1]
    await cb.message.edit_text(
        f"📚 <b>{NAMES_PL.get(g, g)}</b>\nWybierz kategorię:",
        reply_markup=get_group_categories_keyboard_learn(g),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("learn_cat:"))
async def learn_cat(cb: CallbackQuery):
    _, group_key, ckey, page_s = cb.data.split(":")
    page = int(page_s)

    words = [
        w for w in trainer.categories.get(ckey, []) if w in trainer.vocabulary
    ]
    if ckey != "powitania":
        words.sort(key=_strip_accents)

    if not words:
        await cb.message.edit_text(
            "❌ Pusto.",
            reply_markup=get_group_categories_keyboard_learn(group_key))
        return await cb.answer()

    items = [(w, trainer.vocabulary[w]) for w in words]
    chunk, page, total = paginate(items, page, PAGE_SIZE)

    lines = [f"📃 <b>{NAMES_PL.get(ckey, ckey)}</b> — razem {len(items)}"]
    for pl, ru in chunk:
        digits = [x for x in valid_answers_pl(pl) if x.isdigit()]
        tail = f" • dop.: {', '.join(digits)}" if digits else ""
        lines.append(f"• <b>{pl}</b> — {ru}{tail}")

    cats_in_group = [
        c for c in GROUPS.get(group_key, [])
        if c in trainer.categories and trainer.categories[c]
    ]
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=kb_learn_pagination(group_key, ckey, page, total,
                                         cats_in_group),
        parse_mode="HTML",
    )
    await cb.answer()


# ── Тренировка ────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "nav_train")
async def nav_train(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧠 Wszystkie słowa",
                                 callback_data="train_scope:all")
        ],
        [
            InlineKeyboardButton(text="🎯 Wybierz kategorię",
                                 callback_data="train_scope:bycat")
        ],
        [InlineKeyboardButton(text="🔙 Wróć", callback_data="back_to_menu")],
    ])
    await cb.message.edit_text("🎯 <b>Tryb treningowy</b>\nWybierz zakres:",
                               reply_markup=kb,
                               parse_mode="HTML")
    await cb.answer()


def kb_train_groups() -> InlineKeyboardMarkup:
    rows = []
    for gkey, cats in GROUPS.items():
        existing = [
            c for c in cats
            if c in trainer.categories and trainer.categories[c]
        ]
        if existing:
            rows.append([
                InlineKeyboardButton(
                    text=f"{icon_for_group(gkey)} {NAMES_PL.get(gkey, gkey)}",
                    callback_data=f"train_pick_group:{gkey}",
                )
            ])
    rows.append(
        [InlineKeyboardButton(text="🔙 Wróć", callback_data="nav_train")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_train_cats(group_key: str) -> InlineKeyboardMarkup:
    rows = []
    for ckey in GROUPS.get(group_key, []):
        if ckey in trainer.categories and trainer.categories[ckey]:
            rows.append([
                InlineKeyboardButton(
                    text=f"📂 {NAMES_PL.get(ckey, ckey)}",
                    callback_data=f"train_pick_cat:{ckey}",
                )
            ])
    rows.append([
        InlineKeyboardButton(text="🔙 Wróć", callback_data="train_scope:bycat")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("train_scope:"))
async def train_scope(cb: CallbackQuery, state: FSMContext):
    scope = cb.data.split(":", 1)[1]
    if scope == "all":
        await state.update_data(train_cats=None)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇵🇱 → 🇷🇺", callback_data="quiz_pl_ru")],
            [InlineKeyboardButton(text="🇷🇺 → 🇵🇱", callback_data="quiz_ru_pl")],
            [InlineKeyboardButton(text="🔙 Wróć", callback_data="nav_train")],
        ])
        await cb.message.edit_text("Wybierz kierunek quizu:", reply_markup=kb)
    else:
        await cb.message.edit_text("🎯 Wybierz grupę:",
                                   reply_markup=kb_train_groups(),
                                   parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("train_pick_group:"))
async def train_pick_group(cb: CallbackQuery):
    g = cb.data.split(":", 1)[1]
    await cb.message.edit_text(
        f"🎯 <b>{NAMES_PL.get(g, g)}</b>\nWybierz kategorię:",
        reply_markup=kb_train_cats(g),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("train_pick_cat:"))
async def train_pick_cat(cb: CallbackQuery, state: FSMContext):
    ckey = cb.data.split(":", 1)[1]
    await state.update_data(train_cats=[ckey])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇵🇱 → 🇷🇺", callback_data="quiz_pl_ru")],
        [InlineKeyboardButton(text="🇷🇺 → 🇵🇱", callback_data="quiz_ru_pl")],
        [
            InlineKeyboardButton(text="🔙 Wróć",
                                 callback_data="train_scope:bycat")
        ],
    ])
    await cb.message.edit_text(
        f"🧠 {NAMES_PL.get(ckey, ckey)} — wybierz kierunek:", reply_markup=kb)
    await cb.answer()


@router.callback_query((F.data == "quiz_pl_ru") | (F.data == "quiz_ru_pl"))
async def quiz_start(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    direction = "pl_ru" if cb.data == "quiz_pl_ru" else "ru_pl"
    data = await state.get_data()
    pool_keys = data.get("train_cats")

    words = trainer.flat_items(pool_keys)
    if not words:
        return await cb.message.answer("❌ Brak słów w wybranym zakresie.")

    random.shuffle(words)
    words = words[:10]

    trainer.quiz_sessions[uid] = {
        "words": words,
        "current_question": 0,
        "score": 0,
        "total": len(words),
        "direction": direction,
    }
    await ask_question(cb.message, uid, state)
    await cb.answer()


async def ask_question(msg: Message, uid: int, state: FSMContext):
    sess = trainer.quiz_sessions.get(uid)
    if not sess:
        return
    i = sess["current_question"]
    if i >= sess["total"]:
        return await finish_quiz(msg, uid)

    pl, ru = sess["words"][i]
    if sess["direction"] == "pl_ru":
        q = f"Co znaczy po rosyjsku: «{pl}»?"
        valid = [ru] + [x for x in valid_answers_pl(pl) if x.isdigit()]
    else:
        q = f"Jak będzie po polsku: «{ru}»?"
        valid = valid_answers_pl(pl)

    await state.update_data(correct_answer_list=valid, user_id=uid)
    await state.set_state(QuizStates.waiting_for_answer)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Pomiń", callback_data="skip_question")],
        [InlineKeyboardButton(text="❌ Zakończ", callback_data="end_quiz")],
    ])
    await msg.answer(f"🎯 Pytanie {i+1}/{sess['total']}\n\n{q}",
                     reply_markup=kb)


@router.message(QuizStates.waiting_for_answer)
async def on_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("user_id")
    sess = trainer.quiz_sessions.get(uid)
    if not sess:
        await message.answer("❌ Brak sesji quizu.")
        return await state.clear()

    user = (message.text or "").strip()
    valid: List[str] = data.get("correct_answer_list", [])
    ok = equals_relaxed(user, valid)
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
        return await state.clear()
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
    percent = (score / total * 100) if total else 0.0
    trainer.get_user_stats(uid)["quiz_count"] += 1
    del trainer.quiz_sessions[uid]

    text = f"🎉 Wynik: {score}/{total} ({percent:.1f}%)"
    if percent >= 80:
        text += "\n🌟 Świetnie!"
    elif percent >= 60:
        text += "\n👍 Dobrze!"
    else:
        text += "\n📚 Ćwicz dalej!"
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


# ── Прогресс ──────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "progress")
async def progress(cb: CallbackQuery):
    uid = cb.from_user.id
    s = trainer.get_user_stats(uid)
    if s["total_questions"]:
        acc = s["correct_answers"] / s["total_questions"] * 100
        text = ("📊 Twoje postępy:\n\n"
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


# ── Healthcheck для Render ────────────────────────────────────────────────────
async def healthcheck(_):
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
    asyncio.create_task(start_web_server())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
