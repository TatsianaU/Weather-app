"""
Weather app: OpenWeather Geocoding + Current Weather.
CLI: city or coordinates, cache, retries with backoff.
"""
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("API_KEY")

GEOCODING_URL = "https://api.openweathermap.org/geo/1.0/direct"
WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
CACHE_FILE = Path(__file__).parent / "weather_cache.json"
CACHE_MAX_AGE_HOURS = 3
RETRY_DELAYS = (1, 2, 4)


def _request_with_retries(url: str, params: dict) -> requests.Response | None:
    """Выполняет GET с до 3 повторов при 429 или сетевых ошибках (паузы 1s, 2s, 4s)."""
    last_resp = None
    for attempt, delay in enumerate(RETRY_DELAYS):
        try:
            resp = requests.get(url, params=params, timeout=10)
            last_resp = resp
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < len(RETRY_DELAYS) - 1:
                    time.sleep(delay)
                    continue
            return resp
        except (requests.RequestException, requests.Timeout):
            if attempt < len(RETRY_DELAYS) - 1:
                time.sleep(delay)
                continue
            return None
    return last_resp


def get_coordinates(city: str) -> tuple[float, float] | None:
    """
    OpenWeather Geocoding API: город -> (lat, lon).
    limit=1, при пустом ответе или ошибке — понятное сообщение без трейсбека.
    """
    if not API_KEY:
        print("Ошибка: API_KEY не задан. Добавьте API_KEY=... в .env")
        return None
    params = {"q": city, "limit": 1, "appid": API_KEY}
    resp = _request_with_retries(GEOCODING_URL, params)
    if resp is None:
        print("Ошибка сети при запросе координат. Проверьте интернет.")
        return None
    if resp.status_code != 200:
        if resp.status_code == 401:
            print("Ошибка: неверный или недействительный API-ключ OpenWeather.")
        else:
            print(f"Ошибка геокодинга: HTTP {resp.status_code}")
        return None
    data = resp.json()
    if not data or not isinstance(data, list) or len(data) == 0:
        print(f"Город не найден: «{city}»")
        return None
    try:
        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
        return (lat, lon)
    except (KeyError, TypeError, ValueError):
        print("Ошибка: неожиданный ответ геокодинга.")
        return None


def get_weather_by_coordinates(lat: float, lon: float) -> dict | None:
    """
    Current Weather по координатам: units=metric, lang=ru.
    При статусе != 200 или невалидном ключе — понятное сообщение без трейсбека.
    """
    if not API_KEY:
        print("Ошибка: API_KEY не задан. Добавьте API_KEY=... в .env")
        return None
    params = {"lat": lat, "lon": lon, "appid": API_KEY, "units": "metric", "lang": "ru"}
    resp = _request_with_retries(WEATHER_URL, params)
    if resp is None:
        print("Ошибка сети при запросе погоды. Проверьте интернет.")
        return None
    if resp.status_code != 200:
        if resp.status_code == 401:
            print("Ошибка: неверный или недействительный API-ключ OpenWeather.")
        else:
            print(f"Ошибка погоды: HTTP {resp.status_code}")
        return None
    try:
        return resp.json()
    except (ValueError, TypeError):
        print("Ошибка: неожиданный ответ API погоды.")
        return None


def _format_weather_message(city: str, data: dict) -> str:
    """Формирует строку: Погода в <город>: <температура>°C, <описание>."""
    try:
        temp = data["main"]["temp"]
        desc = (data.get("weather") or [{}])[0].get("description", "—")
        return f"Погода в {city}: {temp}°C, {desc}"
    except (KeyError, TypeError):
        return f"Погода в {city}: данные получены, но формат ответа неожиданный."


def _save_cache(city: str, lat: float, lon: float, weather: dict) -> None:
    """Сохраняет последний успешный ответ в weather_cache.json."""
    try:
        payload = {
            "city": city,
            "lat": lat,
            "lon": lon,
            "fetched_at": time.time(),
            "weather": weather,
        }
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except (OSError, TypeError):
        pass


def _load_cache(max_age_hours: float = CACHE_MAX_AGE_HOURS) -> dict | None:
    """Читает кэш; возвращает None, если файла нет или кэш старше max_age_hours."""
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    fetched = data.get("fetched_at")
    if fetched is None:
        return None
    if (time.time() - float(fetched)) > max_age_hours * 3600:
        return None
    return data


def _run_by_city() -> bool:
    """Режим 1: ввод города, вывод погоды. Возвращает True если нужно предложить кэш при ошибке."""
    city = input("Введите город: ").strip()
    if not city:
        print("Город не указан.")
        return False
    coords = get_coordinates(city)
    if coords is None:
        return True
    lat, lon = coords
    weather = get_weather_by_coordinates(lat, lon)
    if weather is None:
        return True
    _save_cache(city, lat, lon, weather)
    print(_format_weather_message(city, weather))
    return False


def _run_by_coordinates() -> bool:
    """Режим 2: ввод координат, вывод погоды. Возвращает True если нужно предложить кэш при ошибке."""
    try:
        lat = float(input("Широта: ").strip().replace(",", "."))
        lon = float(input("Долгота: ").strip().replace(",", "."))
    except ValueError:
        print("Ошибка: введите числа для широты и долготы.")
        return False
    city = f"{lat:.2f}, {lon:.2f}"
    weather = get_weather_by_coordinates(lat, lon)
    if weather is None:
        return True
    _save_cache(city, lat, lon, weather)
    print(_format_weather_message(city, weather))
    return False


def _offer_cache() -> None:
    """Предлагает вывести данные из кэша, если им меньше 3 часов."""
    cached = _load_cache()
    if cached is None:
        return
    city = cached.get("city", "—")
    weather = cached.get("weather")
    if not weather:
        return
    print("Показать последние сохранённые данные из кэша? (д/н): ", end="")
    if input().strip().lower() in ("д", "y", "yes", "да"):
        print(_format_weather_message(city, weather))


def main() -> None:
    print("Режимы: 1 — по городу, 2 — по координатам, 0 — выход.")
    while True:
        choice = input("Выбор (0/1/2): ").strip()
        if choice == "0":
            print("Выход.")
            break
        if choice == "1":
            if _run_by_city():
                _offer_cache()
            continue
        if choice == "2":
            if _run_by_coordinates():
                _offer_cache()
            continue
        print("Введите 0, 1 или 2.")


if __name__ == "__main__":
    main()
