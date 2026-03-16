"""
Weather app: OpenWeather Geocoding + Current Weather.
CLI: city or coordinates, cache, retries with backoff.
+ Added: 5-day forecast (every 3 hours)
"""

import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("OW_API_KEY")

GEOCODING_URL = "https://api.openweathermap.org/geo/1.0/direct"
WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

CACHE_FILE = Path(__file__).parent / "weather_cache.json"
CACHE_MAX_AGE_HOURS = 3
RETRY_DELAYS = (1, 2, 4)


# =========================
# RETRIES
# =========================

def _request_with_retries(url: str, params: dict) -> requests.Response | None:
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


# =========================
# GEOCODING
# =========================

def get_coordinates(city: str) -> tuple[float, float] | None:
    """Геокодинг города в координаты (lat, lon) через OpenWeather."""
    if not API_KEY:
        print("[get_coordinates] Ошибка: OW_API_KEY не задан. Добавьте OW_API_KEY=... в .env")
        return None

    print(f"[get_coordinates] OW_API_KEY загружен: {bool(API_KEY)}")
    print(f"[get_coordinates] city={city!r}")

    params = {"q": city, "limit": 1, "appid": API_KEY, "lang": "ru"}
    resp = _request_with_retries(GEOCODING_URL, params)

    if resp is None:
        print("[get_coordinates] Ошибка сети при запросе координат (resp is None).")
        return None

    print(f"[get_coordinates] status_code={resp.status_code}")

    if resp.status_code != 200:
        try:
            body = resp.text
        except Exception:
            body = "<no text>"
        if resp.status_code == 401:
            print("[get_coordinates] Ошибка 401: неверный или недействительный OW_API_KEY.")
        elif resp.status_code == 429:
            print("[get_coordinates] Ошибка 429: превышен лимит запросов.")
        elif resp.status_code >= 500:
            print(f"[get_coordinates] Ошибка сервера OpenWeather: HTTP {resp.status_code}")
        else:
            print(f"[get_coordinates] Ошибка геокодинга: HTTP {resp.status_code}")
        print(f"[get_coordinates] Тело ответа: {body}")
        return None

    try:
        data = resp.json()
    except (ValueError, TypeError) as e:
        print(f"[get_coordinates] Ошибка парсинга JSON: {e}")
        return None

    if not data:
        print(f"[get_coordinates] Пустой ответ геокодинга. Город не найден: «{city}»")
        return None

    try:
        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
        print(f"[get_coordinates] Успех: lat={lat}, lon={lon}")
        return lat, lon
    except (KeyError, TypeError, ValueError) as e:
        print(f"[get_coordinates] Ошибка структуры ответа: {e}")
        return None


# =========================
# CURRENT WEATHER
# =========================

def get_weather_by_coordinates(lat: float, lon: float) -> dict | None:
    if not API_KEY:
        print("Ошибка: API_KEY не задан.")
        return None

    params = {
        "lat": lat,
        "lon": lon,
        "appid": API_KEY,
        "units": "metric",
        "lang": "ru",
    }

    resp = _request_with_retries(WEATHER_URL, params)

    if resp is None:
        print("Ошибка сети при запросе погоды.")
        return None

    if resp.status_code != 200:
        if resp.status_code == 401:
            print("Ошибка: неверный API-ключ.")
        else:
            print(f"Ошибка погоды: HTTP {resp.status_code}")
        return None

    try:
        return resp.json()
    except (ValueError, TypeError):
        print("Ошибка: неожиданный ответ API погоды.")
        return None


def _format_weather_message(city: str, data: dict) -> str:
    try:
        temp = round(data["main"]["temp"], 1)
        desc = (data.get("weather") or [{}])[0].get("description", "—")
        return f"Погода в {city}: {temp}°C, {desc}"
    except (KeyError, TypeError):
        return f"Погода в {city}: данные получены, но формат ответа неожиданный."


# =========================
# FORECAST 5 DAYS
# =========================

def get_forecast_by_coordinates(lat: float, lon: float) -> dict | None:
    if not API_KEY:
        print("Ошибка: API_KEY не задан.")
        return None

    params = {
        "lat": lat,
        "lon": lon,
        "appid": API_KEY,
        "units": "metric",
        "lang": "ru",
    }

    resp = _request_with_retries(FORECAST_URL, params)

    if resp is None:
        print("Ошибка сети при запросе прогноза.")
        return None

    if resp.status_code != 200:
        if resp.status_code == 401:
            print("Ошибка: неверный API-ключ.")
        else:
            print(f"Ошибка прогноза: HTTP {resp.status_code}")
        return None

    try:
        return resp.json()
    except (ValueError, TypeError):
        print("Ошибка формата данных прогноза.")
        return None


def _format_forecast(data: dict) -> None:
    try:
        city = data["city"]["name"]
        print(f"\nПрогноз для {city} (каждые 3 часа):\n")

        for item in data["list"]:
            dt = item["dt_txt"]
            temp = round(item["main"]["temp"], 1)
            desc = item["weather"][0]["description"]
            print(f"{dt} → {temp}°C, {desc}")

    except (KeyError, TypeError):
        print("Ошибка формата данных прогноза.")


# =========================
# CACHE
# =========================

def _save_cache(city: str, lat: float, lon: float, weather: dict) -> None:
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


# =========================
# CLI MODES
# =========================

def _run_by_city() -> bool:
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


def _run_forecast_by_city() -> None:
    city = input("Введите город для прогноза: ").strip()
    if not city:
        print("Город не указан.")
        return
    coords = get_coordinates(city)
    if coords is None:
        return
    lat, lon = coords
    forecast = get_forecast_by_coordinates(lat, lon)
    if forecast is None:
        return
    _format_forecast(forecast)


def _run_air_quality_by_city() -> None:
    """Режим: качество воздуха по городу с текстовым отчётом."""
    city = input("Введите город для оценки качества воздуха: ").strip()
    if not city:
        print("Город не указан.")
        return

    coords = get_coordinates(city)
    if coords is None:
        return

    lat, lon = coords
    air = get_air_quality_by_coordinates(lat, lon)
    if not air:
        return

    report = air.get("text_report")
    if report:
        print(report)
    else:
        print("Данные о качестве воздуха получены, но отчёт недоступен.")


def _offer_cache() -> None:
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


# =========================
# AIR POLLUTION
# =========================


_AIR_QUALITY_LEVELS = {
    1: {
        "name": "Хорошее",
        "no2": (0, 50),
        "o3": (0, 60),
        "pm10": (0, 25),
        "pm2_5": (0, 15),
        "so2": (0, 20),
        "co": (0, 4400),
    },
    2: {
        "name": "Удовлетворительное",
        "no2": (50, 100),
        "o3": (60, 120),
        "pm10": (25, 50),
        "pm2_5": (15, 30),
        "so2": (20, 80),
        "co": (4400, 9400),
    },
    3: {
        "name": "Умеренное",
        "no2": (100, 200),
        "o3": (120, 180),
        "pm10": (50, 90),
        "pm2_5": (30, 55),
        "so2": (80, 250),
        "co": (9400, 12400),
    },
    4: {
        "name": "Плохое",
        "no2": (200, 400),
        "o3": (180, 240),
        "pm10": (90, 180),
        "pm2_5": (55, 110),
        "so2": (250, 350),
        "co": (12400, 15400),
    },
    5: {
        "name": "Очень плохое",
        "no2": (400, None),
        "o3": (240, None),
        "pm10": (180, None),
        "pm2_5": (110, None),
        "so2": (350, None),
        "co": (15400, None),
    },
}


def _classify_component(pollutant: str, value: float) -> tuple[int, str]:
    """Определяет уровень качества по таблице OpenWeather для одного компонента."""
    if value is None:
        return 0, "нет данных"
    for idx in range(1, 6):
        level = _AIR_QUALITY_LEVELS[idx]
        bounds = level.get(pollutant)
        if not bounds:
            continue
        low, high = bounds
        if high is None:
            if value >= low:
                return idx, level["name"]
        else:
            if low <= value < high:
                return idx, level["name"]
    return 0, "вне диапазона"


def get_air_quality_by_coordinates(lat: float, lon: float) -> dict | None:
    """
    Получение данных о загрязнении воздуха по координатам.

    URL (из задания):
    http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={API key}

    Возвращает словарь с:
    - общим индексом/статусом;
    - детализацией по компонентам и признаком, что выше нормы (Good), что нет;
    - готовым текстовым отчётом в поле 'text_report'.
    """
    if not API_KEY:
        print("Ошибка: API_KEY не задан. Добавьте API_KEY=... в .env")
        return None

    url = "https://api.openweathermap.org/data/2.5/air_pollution"
    params = {"lat": lat, "lon": lon, "appid": API_KEY}

    resp = _request_with_retries(url, params)
    if resp is None:
        print("Ошибка сети при запросе загрязнения воздуха. Проверьте интернет.")
        return None

    if resp.status_code != 200:
        if resp.status_code == 401:
            print("Ошибка: неверный или недействительный API-ключ OpenWeather.")
        else:
            print(f"Ошибка загрязнения воздуха: HTTP {resp.status_code}")
        return None

    try:
        data = resp.json()
    except (ValueError, TypeError):
        print("Ошибка: неожиданный ответ Air Pollution API.")
        return None

    if not data.get("list"):
        print("Данные о загрязнении воздуха не найдены для этих координат.")
        return None

    entry = data["list"][0]
    components = entry.get("components", {})
    main = entry.get("main", {})
    aqi = main.get("aqi")

    status_map = {
        1: "Хорошее",
        2: "Удовлетворительное",
        3: "Умеренное",
        4: "Плохое",
        5: "Очень плохое",
    }
    status_name = status_map.get(aqi, "Неизвестно")

    detailed_components: dict[str, dict] = {}
    for key in ("pm2_5", "pm10", "no2", "o3", "so2", "co"):
        value = components.get(key)
        level_index, level_name = _classify_component(
            key,
            value if value is not None else None,
        )
        detailed_components[key] = {
            "value": value,
            "level_index": level_index,
            "level_name": level_name,
            "above_good": level_index > 1 if level_index else None,
        }

    # Текстовый отчёт: общий статус + что в норме, что выше нормы (Good)
    human_names = {
        "pm2_5": "PM2.5 (мелкие твёрдые частицы)",
        "pm10": "PM10 (взвешенные частицы)",
        "no2": "NO₂ (диоксид азота)",
        "o3": "O₃ (озон)",
        "so2": "SO₂ (диоксид серы)",
        "co": "CO (угарный газ)",
    }

    lines: list[str] = []
    lines.append(f"Качество воздуха: индекс {aqi}, статус: {status_name}.")
    lines.append("")

    lines.append("Показатели в пределах нормы (уровень 1 — «Хорошее»):")
    for key, desc in detailed_components.items():
        value = desc.get("value")
        level_index = desc.get("level_index")
        level_name = desc.get("level_name")
        above_good = desc.get("above_good")
        name = human_names.get(key, key)

        if value is None or not level_index or above_good:
            continue

        lines.append(
            f"  • {name}: {value} µg/m³ (уровень {level_index} — {level_name})"
        )

    lines.append("")
    lines.append("Показатели выше нормы (хуже, чем «Хорошее»):")
    any_above = False
    for key, desc in detailed_components.items():
        value = desc.get("value")
        level_index = desc.get("level_index")
        level_name = desc.get("level_name")
        above_good = desc.get("above_good")
        name = human_names.get(key, key)

        if value is None or not level_index or not above_good:
            continue

        any_above = True
        lines.append(
            f"  • {name}: {value} µg/m³ (уровень {level_index} — {level_name})"
        )

    if not any_above:
        lines.append("  • нет показателей выше нормы")

    return {
        "aqi_index": aqi,
        "aqi_status": status_name,
        "components": detailed_components,
        "text_report": "\n".join(lines),
    }


# =========================
# MAIN
# =========================

def main() -> None:
    print(
        "Режимы: 1 — по городу, 2 — по координатам, 3 — прогноз 5 дней, "
        "4 — качество воздуха по городу, 0 — выход."
    )
    while True:
        choice = input("Выбор (0/1/2/3/4): ").strip()
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
        if choice == "3":
            _run_forecast_by_city()
            continue
        if choice == "4":
            _run_air_quality_by_city()
            continue
        print("Введите 0, 1, 2, 3 или 4.")


if __name__ == "__main__":
    main()