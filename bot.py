#!/usr/bin/env python3
"""
Polish Trainer Telegram Bot - An interactive Polish language learning bot
"""

import asyncio
import csv
import logging
import os
import random
from typing import Dict, List, Tuple

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot token from environment
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

class QuizStates(StatesGroup):
    waiting_for_answer = State()

class PolishTrainerBot:
    def __init__(self):
        # Initialize vocabulary from the original bot
        self.vocabulary = {
            # Basic greetings
            "dzień dobry": "good day/hello",
            "dobry wieczór": "good evening", 
            "cześć": "hi/hello",
            "do widzenia": "goodbye",
            "dziękuję": "thank you",
            "proszę": "please/you're welcome",
            "tak": "yes",
            "nie": "no",
            
            # Family
            "mama": "mom",
            "tata": "dad",
            "syn": "son",
            "córka": "daughter",
            "brat": "brother",
            "siostra": "sister",
            "dziadek": "grandfather",
            "babcia": "grandmother",
            
            # Numbers
            "jeden": "one",
            "dwa": "two",
            "trzy": "three",
            "cztery": "four",
            "pięć": "five",
            "sześć": "six",
            "siedem": "seven",
            "osiem": "eight",
            "dziewięć": "nine",
            "dziesięć": "ten",
            
            # Colors
            "czerwony": "red",
            "niebieski": "blue",
            "zielony": "green",
            "żółty": "yellow",
            "czarny": "black",
            "biały": "white",
            "różowy": "pink",
            "fioletowy": "purple",
            
            # Food
            "chleb": "bread",
            "mleko": "milk",
            "woda": "water",
            "mięso": "meat",
            "ryba": "fish",
            "jabłko": "apple",
            "banan": "banana",
            "ser": "cheese",
            
            # Common phrases
            "jak się masz?": "how are you?",
            "miło mi cię poznać": "nice to meet you",
            "nie rozumiem": "I don't understand",
            "mówisz po angielsku?": "do you speak English?",
            "ile to kosztuje?": "how much does it cost?",
            "gdzie jest toaleta?": "where is the bathroom?",
        }
        
        # Load additional vocabulary from CSV
        self.load_csv_vocabulary()
        
        # User progress tracking
        self.user_scores: Dict[int, Dict] = {}
        self.quiz_sessions: Dict[int, Dict] = {}
        
        # Categories
        self.categories = {
            "greetings": ["dzień dobry", "dobry wieczór", "cześć", "do widzenia", "dziękuję", "proszę", "tak", "nie"],
            "family": ["mama", "tata", "syn", "córka", "brat", "siostra", "dziadek", "babcia"],
            "numbers": ["jeden", "dwa", "trzy", "cztery", "pięć", "sześć", "siedem", "osiem", "dziewięć", "dziesięć"],
            "colors": ["czerwony", "niebieski", "zielony", "żółty", "czarny", "biały", "różowy", "fioletowy"],
            "food": ["chleb", "mleko", "woda", "mięso", "ryba", "jabłko", "banan", "ser"],
            "phrases": ["jak się masz?", "miło mi cię poznać", "nie rozumiem", "mówisz po angielsku?", "ile to kosztuje?", "gdzie jest toaleta?"]
        }
    
    def load_csv_vocabulary(self):
        """Load vocabulary from CSV file"""
        try:
            with open('data/semya.csv', 'r', encoding='utf-8') as file:
                csv_reader = csv.reader(file, delimiter=';')
                for row in csv_reader:
                    if len(row) >= 2 and row[0] and row[1]:
                        polish_word = row[0].strip()
                        # Handle multiple translations separated by |
                        english_translations = row[1].split('|')
                        english_word = english_translations[0].strip()
                        if polish_word and english_word:
                            self.vocabulary[polish_word] = english_word
        except FileNotFoundError:
            logger.warning("CSV file not found, using default vocabulary only")
        except Exception as e:
            logger.error(f"Error loading CSV vocabulary: {e}")
    
    def get_user_stats(self, user_id: int) -> Dict:
        """Get or create user statistics"""
        if user_id not in self.user_scores:
            self.user_scores[user_id] = {
                'total_questions': 0,
                'correct_answers': 0,
                'quiz_count': 0
            }
        return self.user_scores[user_id]
    
    def update_user_score(self, user_id: int, is_correct: bool):
        """Update user's score"""
        stats = self.get_user_stats(user_id)
        stats['total_questions'] += 1
        if is_correct:
            stats['correct_answers'] += 1

# Create bot instance
trainer = PolishTrainerBot()

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

def get_main_keyboard() -> InlineKeyboardMarkup:
    """Create main menu keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Study Vocabulary", callback_data="study")],
        [InlineKeyboardButton(text="🎯 Take Quiz", callback_data="quiz")],
        [InlineKeyboardButton(text="🎲 Random Word", callback_data="random")],
        [InlineKeyboardButton(text="📊 Progress", callback_data="progress")],
    ])
    return keyboard

def get_category_keyboard() -> InlineKeyboardMarkup:
    """Create category selection keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👋 Greetings", callback_data="cat_greetings")],
        [InlineKeyboardButton(text="👨‍👩‍👧‍👦 Family", callback_data="cat_family")],
        [InlineKeyboardButton(text="🔢 Numbers", callback_data="cat_numbers")],
        [InlineKeyboardButton(text="🎨 Colors", callback_data="cat_colors")],
        [InlineKeyboardButton(text="🍞 Food", callback_data="cat_food")],
        [InlineKeyboardButton(text="💬 Phrases", callback_data="cat_phrases")],
        [InlineKeyboardButton(text="📚 All Words", callback_data="cat_all")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="back_to_menu")],
    ])
    return keyboard

@router.message(CommandStart())
async def start_command(message: Message):
    """Handle /start command"""
    welcome_text = (
        "🇵🇱 <b>Witaj w Polish Trainer Bot!</b> 🇵🇱\n\n"
        "Welcome to your Polish language trainer!\n"
        "Learn vocabulary, practice phrases, and test your knowledge.\n\n"
        "Choose an option below to get started:"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode="HTML")

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    """Handle back to main menu"""
    await callback.message.edit_text(
        "🇵🇱 <b>Polish Trainer Bot</b> 🇵🇱\n\nChoose an option:",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "study")
async def study_vocabulary(callback: CallbackQuery):
    """Handle study vocabulary"""
    await callback.message.edit_text(
        "📖 <b>Study Vocabulary</b>\n\nSelect a category to study:",
        reply_markup=get_category_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("cat_"))
async def show_category_words(callback: CallbackQuery):
    """Show words from selected category"""
    category = callback.data.replace("cat_", "")
    
    if category == "all":
        words_to_show = list(trainer.vocabulary.items())
        category_name = "All Vocabulary"
    else:
        word_list = trainer.categories.get(category, [])
        words_to_show = [(word, trainer.vocabulary[word]) for word in word_list if word in trainer.vocabulary]
        category_name = category.title()
    
    if not words_to_show:
        await callback.message.edit_text(
            "❌ No words found in this category.",
            reply_markup=get_category_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    # Format words for display
    text = f"📚 <b>{category_name}</b>\n\n"
    for polish, english in words_to_show:
        text += f"🇵🇱 <code>{polish}</code> → {english}\n"
    
    # Add navigation
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Categories", callback_data="study")],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="back_to_menu")],
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "quiz")
async def start_quiz(callback: CallbackQuery, state: FSMContext):
    """Start a quiz session"""
    user_id = callback.from_user.id
    
    # Select 5 random words for quiz
    quiz_words = random.sample(list(trainer.vocabulary.items()), min(5, len(trainer.vocabulary)))
    
    # Store quiz session
    trainer.quiz_sessions[user_id] = {
        'words': quiz_words,
        'current_question': 0,
        'score': 0,
        'total': len(quiz_words)
    }
    
    await ask_quiz_question(callback.message, user_id, state)
    await callback.answer()

async def ask_quiz_question(message: Message, user_id: int, state: FSMContext):
    """Ask the current quiz question"""
    session = trainer.quiz_sessions.get(user_id)
    if not session:
        await message.edit_text("❌ Quiz session not found. Please start a new quiz.")
        return
    
    current_q = session['current_question']
    if current_q >= session['total']:
        await finish_quiz(message, user_id)
        return
    
    polish_word, correct_answer = session['words'][current_q]
    
    # Store correct answer in FSM
    await state.update_data(
        correct_answer=correct_answer,
        polish_word=polish_word,
        user_id=user_id
    )
    await state.set_state(QuizStates.waiting_for_answer)
    
    progress = f"{current_q + 1}/{session['total']}"
    text = (
        f"🎯 <b>Quiz Question {progress}</b>\n\n"
        f"What does '<code>{polish_word}</code>' mean in English?\n\n"
        f"Type your answer:"
    )
    
    # Add skip button
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Skip", callback_data="skip_question")],
        [InlineKeyboardButton(text="❌ End Quiz", callback_data="end_quiz")],
    ])
    
    await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@router.message(QuizStates.waiting_for_answer)
async def handle_quiz_answer(message: Message, state: FSMContext):
    """Handle quiz answer from user"""
    data = await state.get_data()
    user_answer = message.text.strip().lower()
    correct_answer = data['correct_answer'].lower()
    polish_word = data['polish_word']
    user_id = data['user_id']
    
    is_correct = user_answer == correct_answer
    
    # Update score
    session = trainer.quiz_sessions[user_id]
    if is_correct:
        session['score'] += 1
        response = f"✅ <b>Correct!</b> Świetnie! (Great!)\n\n"
    else:
        response = f"❌ <b>Wrong.</b> The correct answer is: <b>{data['correct_answer']}</b>\n\n"
    
    # Update user stats
    trainer.update_user_score(user_id, is_correct)
    
    # Move to next question
    session['current_question'] += 1
    
    # Send feedback
    await message.answer(response, parse_mode="HTML")
    
    # Continue with next question or finish
    if session['current_question'] >= session['total']:
        await finish_quiz(message, user_id)
        await state.clear()
    else:
        await ask_quiz_question(message, user_id, state)

async def finish_quiz(message: Message, user_id: int):
    """Finish the quiz and show results"""
    session = trainer.quiz_sessions.get(user_id)
    if not session:
        return
    
    score = session['score']
    total = session['total']
    percentage = (score / total) * 100
    
    # Update quiz count
    stats = trainer.get_user_stats(user_id)
    stats['quiz_count'] += 1
    
    result_text = f"🎉 <b>Quiz Complete!</b>\n\n"
    result_text += f"Score: {score}/{total} ({percentage:.1f}%)\n\n"
    
    if percentage >= 80:
        result_text += "🌟 Excellent work! Doskonale!"
    elif percentage >= 60:
        result_text += "👍 Good job! Dobrze!"
    else:
        result_text += "📚 Keep studying! Ucz się dalej!"
    
    # Clean up session
    del trainer.quiz_sessions[user_id]
    
    await message.answer(result_text, reply_markup=get_main_keyboard(), parse_mode="HTML")

@router.callback_query(F.data == "skip_question")
async def skip_question(callback: CallbackQuery, state: FSMContext):
    """Skip current quiz question"""
    data = await state.get_data()
    user_id = data['user_id']
    
    session = trainer.quiz_sessions[user_id]
    session['current_question'] += 1
    
    await callback.message.edit_text("⏭️ Question skipped!")
    
    if session['current_question'] >= session['total']:
        await finish_quiz(callback.message, user_id)
        await state.clear()
    else:
        await ask_quiz_question(callback.message, user_id, state)
    
    await callback.answer()

@router.callback_query(F.data == "end_quiz")
async def end_quiz(callback: CallbackQuery, state: FSMContext):
    """End quiz early"""
    data = await state.get_data()
    user_id = data['user_id']
    
    if user_id in trainer.quiz_sessions:
        del trainer.quiz_sessions[user_id]
    
    await state.clear()
    await callback.message.edit_text(
        "❌ Quiz ended.",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "random")
async def random_word(callback: CallbackQuery):
    """Show a random word"""
    polish_word, english_meaning = random.choice(list(trainer.vocabulary.items()))
    
    text = f"🎲 <b>Random Word</b>\n\n🇵🇱 <code>{polish_word}</code>\n→ {english_meaning}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Another Word", callback_data="random")],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="back_to_menu")],
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "progress")
async def show_progress(callback: CallbackQuery):
    """Show user progress"""
    user_id = callback.from_user.id
    stats = trainer.get_user_stats(user_id)
    
    text = "📊 <b>Your Progress</b>\n\n"
    
    if stats['total_questions'] > 0:
        accuracy = (stats['correct_answers'] / stats['total_questions']) * 100
        text += f"Questions answered: {stats['total_questions']}\n"
        text += f"Correct answers: {stats['correct_answers']}\n"
        text += f"Accuracy: {accuracy:.1f}%\n"
        text += f"Quizzes taken: {stats['quiz_count']}\n\n"
        
        if accuracy >= 90:
            text += "🏆 You're a Polish language champion!"
        elif accuracy >= 70:
            text += "🎖️ You're doing great!"
        elif accuracy >= 50:
            text += "📈 Keep up the good work!"
        else:
            text += "💪 Practice makes perfect!"
    else:
        text += "No quiz attempts yet.\nTake a quiz to see your progress!"
    
    text += f"\n\nTotal vocabulary available: {len(trainer.vocabulary)} words"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="back_to_menu")],
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

# Register the router
dp.include_router(router)

async def main():
    """Main function to run the bot"""
    logger.info("Starting Polish Trainer Bot...")
    
    try:
        # Start polling
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error running bot: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())