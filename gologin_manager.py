"""Модуль для работы с Gologin"""
import requests
import json
from typing import Optional
from config import Config
from logger import setup_logger

logger = setup_logger(__name__)


class GologinManager:
    """Класс для управления Gologin профилями"""
    
    def __init__(self):
        self.api_token = Config.GOLOGIN_API_TOKEN.strip() if Config.GOLOGIN_API_TOKEN else ""
        self.profile_id = Config.GOLOGIN_PROFILE_ID.strip() if Config.GOLOGIN_PROFILE_ID else ""
        self.base_url = "https://api.gologin.com"
        
        # Проверяем что токен и profile_id не пустые и не равны значениям по умолчанию
        if not self.api_token or self.api_token in ["", "your_gologin_api_token"]:
            self.api_token = ""
        if not self.profile_id or self.profile_id in ["", "your_profile_id"]:
            self.profile_id = ""
        
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        } if self.api_token else {}
    
    def get_profile(self, profile_id: Optional[str] = None) -> Optional[dict]:
        """Получить информацию о профиле"""
        if not self.api_token:
            logger.warning("Gologin API токен не указан")
            return None
        
        profile_id = profile_id or self.profile_id
        if not profile_id:
            logger.warning("Gologin Profile ID не указан")
            return None
        
        try:
            url = f"{self.base_url}/browser/{profile_id}"
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка при получении профиля Gologin: {e}")
            return None
    
    def start_profile(self, profile_id: Optional[str] = None) -> Optional[dict]:
        """Запустить профиль и получить данные для подключения"""
        if not self.api_token or not self.api_token.strip():
            logger.debug("Gologin API токен не указан, пропускаем Gologin")
            return None
        
        profile_id = (profile_id or self.profile_id).strip()
        if not profile_id or profile_id in ["", "your_profile_id"]:
            logger.debug("Gologin Profile ID не указан, пропускаем Gologin")
            return None
        
        try:
            url = f"{self.base_url}/browser/{profile_id}"
            response = requests.post(url, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            
            # Возвращаем данные для подключения WebDriver
            return {
                'ws_endpoint': data.get('wsEndpoint'),
                'profile_id': profile_id
            }
        except Exception as e:
            logger.error(f"Ошибка при запуске профиля Gologin: {e}")
            return None
    
    def stop_profile(self, profile_id: Optional[str] = None) -> bool:
        """Остановить профиль"""
        if not self.api_token or not self.api_token.strip():
            return False
        
        profile_id = (profile_id or self.profile_id).strip()
        if not profile_id or profile_id in ["", "your_profile_id"]:
            return False
        
        try:
            url = f"{self.base_url}/browser/stop/{profile_id}"
            response = requests.post(url, headers=self.headers)
            response.raise_for_status()
            logger.info(f"Профиль Gologin {profile_id} остановлен")
            return True
        except Exception as e:
            logger.error(f"Ошибка при остановке профиля Gologin: {e}")
            return False
