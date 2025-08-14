"""
Test dosyası - AI Code Review için kasıtlı hatalar içerir
Bu dosya Gemini ve Copilot'un neleri yakalayacağını test etmek için
"""

import os
import subprocess
from typing import Any, Dict, List

# HATA 1: Hardcoded credentials (Güvenlik açığı)
DATABASE_URL = "postgresql://admin:SuperSecret123!@localhost:5432/production"
API_SECRET = "sk-proj-VerySecretKey123456789"
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"

# HATA 2: SQL Injection açığı
def get_user_by_id(user_id: str):
    """Kullanıcıyı ID'ye göre getir - SQL INJECTION AÇIĞI VAR!"""
    query = f"SELECT * FROM users WHERE id = {user_id}"  # Tehlikeli!
    # Doğrusu: query = "SELECT * FROM users WHERE id = %s", (user_id,)
    return execute_query(query)

# HATA 3: Command Injection açığı
def process_file(filename: str):
    """Dosyayı işle - COMMAND INJECTION AÇIĞI VAR!"""
    cmd = f"cat {filename}"  # Tehlikeli!
    result = subprocess.run(cmd, shell=True, capture_output=True)
    return result.stdout

# HATA 4: Path Traversal açığı
def read_user_file(user_input: str):
    """Kullanıcı dosyasını oku - PATH TRAVERSAL AÇIĞI VAR!"""
    file_path = f"/var/data/{user_input}"  # ../../etc/passwd gibi inputlar tehlikeli
    with open(file_path, 'r') as f:
        return f.read()

# HATA 5: Türkçe karakter hatası
def turkish_greeting(name: str) -> str:
    """Türkçe selamlama - KARAKTER HATASI VAR"""
    return f"Merhaba {name}, bugun nasilsiniz?"  # bugün ve nasılsınız yanlış

# HATA 6: Performance sorunu - O(n³) complexity
def find_duplicates_slow(items: List[int]) -> List[int]:
    """Yavaş duplicate bulma - PERFORMANCE SORUNU"""
    duplicates = []
    for i in range(len(items)):
        for j in range(len(items)):
            for k in range(len(items)):
                if i != j and j != k and items[i] == items[j] == items[k]:
                    if items[i] not in duplicates:
                        duplicates.append(items[i])
    return duplicates

# HATA 7: Memory leak potansiyeli
class DataProcessor:
    def __init__(self):
        self.cached_data = []  # Hiç temizlenmiyor
    
    def process(self, data):
        result = data * 1000000
        self.cached_data.append(result)  # Sürekli büyüyor, memory leak!
        return result

# HATA 8: Error handling yok
def divide_numbers(a: float, b: float) -> float:
    """Bölme işlemi - ERROR HANDLING YOK"""
    return a / b  # ZeroDivisionError riski

# HATA 9: Type hint eksik
def calculate_total(items):  # Type hint yok
    total = 0
    for item in items:
        total += item.price  # AttributeError riski
    return total

# HATA 10: Unused variables ve imports
import json  # Kullanılmıyor
import requests  # Kullanılmıyor

def unused_function():
    x = 10
    y = 20
    z = 30  # z kullanılmıyor
    return x + y

# HATA 11: Insecure random
import random
def generate_token():
    """Güvensiz token üretimi"""
    return str(random.randint(1000, 9999))  # Cryptographically weak!

# HATA 12: FreeCAD specific - Resource limit yok
def run_freecad_script(script_path: str):
    """FreeCAD script çalıştır - RESOURCE LIMIT YOK"""
    cmd = ["FreeCADCmd", script_path]
    # Timeout yok, memory limit yok - tehlikeli!
    subprocess.run(cmd)

# HATA 13: Logging sensitive data
import logging
def authenticate_user(username: str, password: str):
    """Kullanıcı doğrulama - SENSITIVE DATA LOGGING"""
    logging.info(f"Login attempt: {username} with password {password}")  # Password loglanmamalı!
    # ... authentication logic
    return True

# HATA 14: Weak encryption
def encrypt_data(data: str) -> str:
    """Zayıf şifreleme - GÜVENSİZ"""
    # ROT13 is not encryption!
    return data.encode('rot13')  

# HATA 15: CORS misconfiguration simulation
CORS_ORIGINS = ["*"]  # Herkese açık, güvensiz!

if __name__ == "__main__":
    # Test the vulnerable functions
    print("Testing vulnerable code...")
    print(get_user_by_id("1 OR 1=1"))  # SQL Injection attempt
    print(turkish_greeting("Ahmet"))
    print(divide_numbers(10, 0))  # Will crash!