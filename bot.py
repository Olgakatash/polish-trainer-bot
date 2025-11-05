#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import csv
import glob
import logging
import os
import random
import unicodedata
from typing import Dict, List, Tuple

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

PAGE_SIZE = 12  # для пагинации в «Przeglądaj»


# ── Утилиты ──────────────────────────────────────────────────────────────────
def _strip_accents(s: str) -> str:
    s = (s or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


# числительные → цифры (для принятия «50» как верного ответа к «pięćdziesiąt»)
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
    if t in _NUM_WORD: return _NUM_WORD[t]
    total = 0
    for p in t.split():
        if p in _NUM_WORD: total += _NUM_WORD[p]
        else: return None
    return total or None


def valid_answers_pl(expected_pl: str) -> List[str]:
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


# ── Модель данных ─────────────────────────────────────────────────────────────
class PolishTrainerBot:

    def __init__(self):
        # базовые слова
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
        }
        # категории (ключи совпадают с CSV файлами)
        self.categories: Dict[str, List[str]] = {
            # Podstawy
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
                "trzydzieści", "czterdzieści", "pięćdziesiąт", "sześćdziesiąт",
                "siedemdziesiąт", "osiemdziesiąт", "dziewięćdziesiąт"
            ],
            "liczby_100_1000": [
                "sto", "dwieście", "trzysta", "czterysta", "pięćсет",
                "sześćset", "siedемset", "osiemset", "dziewięćсет", "tysiąc"
            ],
            "zwroty": [
                "jak się masz?", "miło mi cię poznać", "nie rozumiem",
                "mówisz po angielsku?", "ile to kosztuje?",
                "gdzie jest toaleta?"
            ],

            # Остальные подтянутся из CSV при наличии:
            # jedzenie_owoce, jedzenie_warzywa, ...; rutyna; rodzina/semya; czas_wolny; mieszkanie
        }

        self.load_csv_vocabulary()

        # после загрузки — алфавитно отсортируем слова в категориях
        for k, lst in self.categories.items():
            self.categories[k] = sorted(list(dict.fromkeys(lst)),
                                        key=_strip_accents)

        self.user_scores: Dict[int, Dict] = {}
        self.quiz_sessions: Dict[int, Dict] = {}

    def load_csv_vocabulary(self):
        try:
            for path in glob.glob("data/*.csv"):
                cat_key = os.path.splitext(os.path.basename(path))[0].lower()
                self.categories.setdefault(cat_key, [])
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

    def flat_items(self,
                   pool_keys: List[str] | None = None
                   ) -> List[Tuple[str, str]]:
        items: List[Tuple[str, str]] = []
        if pool_keys:
            for ck in pool_keys:
                for w in self.categories.get(ck, []):
                    if w in self.vocabulary:
                        items.append((w, self.vocabulary[w]))
        else:
            items = list(self.vocabulary.items())
        # алфавитная сортировка по польскому
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
        # показываем группу, только если в ней есть хотя бы одна непустая категория
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


# отдельная клавиатура для «Przeglądaj» (идём на browse_cat, чтобы были стрелки)
def get_group_categories_keyboard_browse(
        group_key: str) -> InlineKeyboardMarkup:
    rows = []
    for ckey in GROUPS.get(group_key, []):
        if ckey in trainer.categories and trainer.categories[ckey]:
            rows.append([
                InlineKeyboardButton(
                    text=f"📂 {NAMES_PL.get(ckey, ckey.capitalize())}",
                    callback_data=
                    f"browse_cat:{group_key}:{ckey}:0"  # страница 0
                )
            ])
    rows.append(
        [InlineKeyboardButton(text="🔙 Wróć", callback_data="nav_browse")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_pagination(group_key: str, ckey: str, page: int, total: int,
                  cats_in_group: List[str]):
    prev_p = (page - 1) % total
    next_p = (page + 1) % total
    # соседние категории в группе
    i = cats_in_group.index(ckey)
    prev_c = cats_in_group[i - 1] if i > 0 else cats_in_group[-1]
    next_c = cats_in_group[
        i + 1] if i < len(cats_in_group) - 1 else cats_in_group[0]
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="◀️", callback_data=f"browse_cat:{group_key}:{prev_c}:0"),
            InlineKeyboardButton(text=f"{NAMES_PL.get(ckey, ckey)}",
                                 callback_data="noop"),
            InlineKeyboardButton(
                text="▶️", callback_data=f"browse_cat:{group_key}:{next_c}:0")
        ],
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
        [
            InlineKeyboardButton(text="🔙 Wróć",
                                 callback_data=f"browse_group:{group_key}")
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
async def back_to_menu(cb: CallbackQuery):
    await cb.message.edit_text("🏠 Menu główne\n\nWybierz opcję:",
                               reply_markup=get_main_keyboard())
    await cb.answer()


# ── Learn: группы → категории → список ────────────────────────────────────────
@router.callback_query(F.data == "nav_learn")
async def nav_learn(cb: CallbackQuery):
    await cb.message.edit_text("📖 <b>Ucz się słówek</b>\n\nWybierz grupę:",
                               reply_markup=get_groups_keyboard(),
                               parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("learn_group:"))
async def nav_learn_group(cb: CallbackQuery):
    group_key = cb.data.split(":", 1)[1]
    await cb.message.edit_text(
        f"📚 <b>{NAMES_PL.get(group_key, group_key.capitalize())}</b>\n\nWybierz kategorię:",
        reply_markup=get_group_categories_keyboard(group_key),
        parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("cat_"))
async def show_category(cb: CallbackQuery):
    key = cb.data.replace("cat_", "")
    lst = sorted([
        w for w in trainer.categories.get(key, []) if w in trainer.vocabulary
    ],
                 key=_strip_accents)
    name = NAMES_PL.get(key, key.capitalize())

    if not lst:
        await cb.message.edit_text("❌ W tej kategorii na razie nie ma słów.",
                                   reply_markup=get_main_keyboard())
        return await cb.answer()

    lines = [f"📚 <b>{name}</b>\n"]
    for pl in lst:
        lines.append(f"🇵🇱 <code>{pl}</code> → {trainer.vocabulary[pl]}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Grupy", callback_data="nav_learn")],
        [
            InlineKeyboardButton(text="🏠 Menu główne",
                                 callback_data="back_to_menu")
        ],
    ])
    await cb.message.edit_text("\n".join(lines),
                               reply_markup=kb,
                               parse_mode="HTML")
    await cb.answer()


# ── Przeglądaj: группы → категории (browse) → стрелки/пагинация ──────────────
@router.callback_query(F.data == "nav_browse")
async def nav_browse(cb: CallbackQuery):
    kb = []
    for gkey, cats in GROUPS.items():
        existing = [
            c for c in cats
            if c in trainer.categories and trainer.categories[c]
        ]
        if not existing:
            continue
        kb.append([
            InlineKeyboardButton(
                text=f"{icon_for_group(gkey)} {NAMES_PL.get(gkey,gkey)}",
                callback_data=f"browse_group:{gkey}")
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
        reply_markup=get_group_categories_keyboard_browse(g),
        parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("browse_cat:"))
async def browse_cat(cb: CallbackQuery):
    _, group_key, ckey, page_s = cb.data.split(":")
    page = int(page_s)
    words = [
        w for w in trainer.categories.get(ckey, []) if w in trainer.vocabulary
    ]
    words.sort(key=_strip_accents)
    if not words:
        await cb.message.edit_text(
            "❌ Pusto.",
            reply_markup=get_group_categories_keyboard_browse(group_key))
        return await cb.answer()

    chunk, page, total = paginate([(w, trainer.vocabulary[w]) for w in words],
                                  page, PAGE_SIZE)
    lines = [f"📃 <b>{NAMES_PL.get(ckey, ckey)}</b> — razem {len(words)}"]
    for pl, ru in chunk:
        digits = [x for x in valid_answers_pl(pl) if x.isdigit()]
        tail = f" • dop.: {', '.join(digits)}" if digits else ""
        lines.append(f"• <b>{pl}</b> — {ru}{tail}")

    cats_in_group = [
        c for c in GROUPS.get(group_key, [])
        if c in trainer.categories and trainer.categories[c]
    ]
    await cb.message.edit_text("\n".join(lines),
                               reply_markup=kb_pagination(
                                   group_key, ckey, page, total,
                                   cats_in_group),
                               parse_mode="HTML")
    await cb.answer()


# ── Тренировка ────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "nav_train")
async def nav_train(cb: CallbackQuery):
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
        await cb.message.edit_text(
            "🎯 Wybierz kategorię (Podstawy):",
            reply_markup=get_group_categories_keyboard_browse("podstawy"),
            parse_mode="HTML")
    await cb.answer()


@router.callback_query((F.data == "quiz_pl_ru") | (F.data == "quiz_ru_pl"))
async def quiz_start(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    direction = "pl_ru" if cb.data == "quiz_pl_ru" else "ru_pl"

    # если перед этим выбиралась категория через browse_cat, её не сохраняли — качаем весь словарь
    words = trainer.flat_items()
    if not words:
        return await cb.message.answer("❌ Brak słów w wybranym zakresie.")
    random.shuffle(words)
    words = words[:10]

    trainer.quiz_sessions[uid] = {
        "words": words,
        "current_question": 0,
        "score": 0,
        "total": len(words),
        "direction": direction
    }
    await ask_question(cb.message, uid, state)
    await cb.answer()


async def ask_question(msg: Message, uid: int, state: FSMContext):
    sess = trainer.quiz_sessions.get(uid)
    if not sess: return
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
    if uid in trainer.quiz_sessions: del trainer.quiz_sessions[uid]
    await state.clear()
    await cb.message.answer("❌ Quiz zakończony.",
                            reply_markup=get_main_keyboard())


async def finish_quiz(msg: Message, uid: int):
    sess = trainer.quiz_sessions.get(uid)
    if not sess: return
    score, total = sess["score"], sess["total"]
    percent = (score / total * 100) if total else 0.0
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


# ── Прогресс ──────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "progress")
async def progress(cb: CallbackQuery):
    uid = cb.from_user.id
    s = trainer.get_user_stats(uid)
    if s["total_questions"]:
        acc = s["correct_answers"] / s["total_questions"] * 100
        text = (
            f"📊 Twoje postępy:\n\nPytania: {s['total_questions']}\n"
            f"Poprawnych: {s['correct_answers']}\nSkuteczność: {acc:.1f}%\n"
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
