#!/usr/bin/env python3
"""
Polish Trainer Bot - An interactive Polish language learning application
"""

import random
import sys
import time

class PolishTrainerBot:
    def __init__(self):
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
        
        self.score = 0
        self.total_questions = 0
    
    def display_welcome(self):
        print("=" * 50)
        print("🇵🇱 WITAJ W POLISH TRAINER BOT! 🇵🇱")
        print("=" * 50)
        print("Welcome to your Polish language trainer!")
        print("Learn vocabulary, practice phrases, and test your knowledge.")
        print()
    
    def display_menu(self):
        print("\n📚 What would you like to do?")
        print("1. 📖 Study vocabulary")
        print("2. 🎯 Take a quiz")
        print("3. 🎲 Random word practice")
        print("4. 📊 View your progress")
        print("5. ❌ Exit")
        return input("\nChoose an option (1-5): ").strip()
    
    def study_vocabulary(self):
        print("\n📖 VOCABULARY STUDY MODE")
        print("-" * 30)
        
        categories = {
            "greetings": ["dzień dobry", "dobry wieczór", "cześć", "do widzenia", "dziękuję", "proszę", "tak", "nie"],
            "family": ["mama", "tata", "syn", "córka", "brat", "siostra", "dziadek", "babcia"],
            "numbers": ["jeden", "dwa", "trzy", "cztery", "pięć", "sześć", "siedem", "osiem", "dziewięć", "dziesięć"],
            "colors": ["czerwony", "niebieski", "zielony", "żółty", "czarny", "biały", "różowy", "fioletowy"],
            "food": ["chleb", "mleko", "woda", "mięso", "ryba", "jabłko", "banan", "ser"],
            "phrases": ["jak się masz?", "miło mi cię poznać", "nie rozumiem", "mówisz po angielsku?", "ile to kosztuje?", "gdzie jest toaleta?"]
        }
        
        print("Categories:")
        for i, category in enumerate(categories.keys(), 1):
            print(f"{i}. {category.title()}")
        print(f"{len(categories) + 1}. All vocabulary")
        
        choice = input(f"\nSelect category (1-{len(categories) + 1}): ").strip()
        
        try:
            choice_num = int(choice)
            if choice_num == len(categories) + 1:
                words_to_study = list(self.vocabulary.keys())
            else:
                category_name = list(categories.keys())[choice_num - 1]
                words_to_study = categories[category_name]
        except (ValueError, IndexError):
            print("Invalid choice. Showing all vocabulary.")
            words_to_study = list(self.vocabulary.keys())
        
        print(f"\n📝 Studying {len(words_to_study)} words:")
        print("-" * 40)
        
        for polish_word in words_to_study:
            english_meaning = self.vocabulary[polish_word]
            print(f"🇵🇱 {polish_word.ljust(20)} → {english_meaning}")
            time.sleep(0.5)
        
        input("\nPress Enter to continue...")
    
    def take_quiz(self):
        print("\n🎯 QUIZ MODE")
        print("-" * 15)
        
        num_questions = min(10, len(self.vocabulary))
        quiz_words = random.sample(list(self.vocabulary.items()), num_questions)
        correct_answers = 0
        
        print(f"Answer {num_questions} questions!")
        print("Type your answer in English.\n")
        
        for i, (polish_word, correct_answer) in enumerate(quiz_words, 1):
            print(f"Question {i}/{num_questions}")
            user_answer = input(f"What does '{polish_word}' mean? ").strip().lower()
            
            if user_answer == correct_answer.lower():
                print("✅ Correct! Świetnie! (Great!)")
                correct_answers += 1
                self.score += 1
            else:
                print(f"❌ Wrong. The correct answer is: {correct_answer}")
            
            self.total_questions += 1
            print("-" * 30)
        
        percentage = (correct_answers / num_questions) * 100
        print(f"\n🎉 Quiz Complete!")
        print(f"Score: {correct_answers}/{num_questions} ({percentage:.1f}%)")
        
        if percentage >= 80:
            print("🌟 Excellent work! Doskonale!")
        elif percentage >= 60:
            print("👍 Good job! Dobrze!")
        else:
            print("📚 Keep studying! Ucz się dalej!")
        
        input("\nPress Enter to continue...")
    
    def random_word_practice(self):
        print("\n🎲 RANDOM WORD PRACTICE")
        print("-" * 25)
        print("Press Enter to see the next word, or type 'quit' to stop.\n")
        
        while True:
            polish_word, english_meaning = random.choice(list(self.vocabulary.items()))
            
            input(f"🇵🇱 {polish_word}")
            print(f"   → {english_meaning}")
            
            user_input = input("\nPress Enter for next word (or 'quit'): ").strip().lower()
            if user_input == 'quit':
                break
            print("-" * 30)
    
    def view_progress(self):
        print("\n📊 YOUR PROGRESS")
        print("-" * 17)
        
        if self.total_questions > 0:
            accuracy = (self.score / self.total_questions) * 100
            print(f"Questions answered: {self.total_questions}")
            print(f"Correct answers: {self.score}")
            print(f"Accuracy: {accuracy:.1f}%")
            
            if accuracy >= 90:
                print("🏆 You're a Polish language champion!")
            elif accuracy >= 70:
                print("🎖️ You're doing great!")
            elif accuracy >= 50:
                print("📈 Keep up the good work!")
            else:
                print("💪 Practice makes perfect!")
        else:
            print("No quiz attempts yet. Take a quiz to see your progress!")
        
        print(f"\nTotal vocabulary available: {len(self.vocabulary)} words")
        input("\nPress Enter to continue...")
    
    def run(self):
        self.display_welcome()
        
        while True:
            choice = self.display_menu()
            
            if choice == '1':
                self.study_vocabulary()
            elif choice == '2':
                self.take_quiz()
            elif choice == '3':
                self.random_word_practice()
            elif choice == '4':
                self.view_progress()
            elif choice == '5':
                print("\nDziękuję za naukę! (Thank you for learning!)")
                print("Do widzenia! (Goodbye!)")
                break
            else:
                print("Invalid choice. Please select 1-5.")

if __name__ == "__main__":
    print("Starting Polish Trainer Bot...")
    bot = PolishTrainerBot()
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n\nDo widzenia! (Goodbye!)")
        sys.exit(0)