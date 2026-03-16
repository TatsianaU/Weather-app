import os
import threading
import time
from datetime import datetime
from typing import Optional, Tuple

from dotenv import load_dotenv
import telebot
from telebot import types

from weather_app import (
    get_coordinates,
    get_weather_by_coordinates,
    get_forecast_by_coordinates,
    get_air_quality_by_coordinates,
)

load_dotenv()

# Основной токен берём из BOT_TOKEN (по ТЗ).
# Для обратной совместимости можно поддержать старую переменную TOKEN.
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in .env")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")


# =========================
# IN-MEMORY USER STATE
# =========================

user_last_location: dict[int, Tuple[float, float]] = {}
user_last_city: dict[int, str] = {}
user_forecast_cache: dict[int, dict] = {}
user_notifications: dict[int, bool] = {}
user_last_condition: dict[int, Optional[str]] = {}


# =========================
# HELPERS
# =========================

def _is_command_text(text: Optional[str]) -> bool:
    return bool(text) and text.strip().startswith("/")


def _reset_flow_and_show_menu(message: telebot.types.Message) -> None:
    """
    Сбрасывает незавершённые сценарии (next_step) и показывает главное меню.
    Важно: next_step может перехватить /start, поэтому этот helper можно вызывать из любых обработчиков.
    """
    try:
        bot.clear_step_handler_by_chat_id(message.chat.id)
    except Exception:
        pass
    cmd_start(message)


def _build_main_menu() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(
        types.KeyboardButton("☀️ Текущая погода по городу"),
        types.KeyboardButton("📍 Погода по геолокации"),
    )
    kb.row(
        types.KeyboardButton("📅 Прогноз на 5 дней"),
        types.KeyboardButton("🔔 Погодные уведомления"),
    )
    kb.row(
        types.KeyboardButton("📊 Сравнение городов"),
        types.KeyboardButton("🌈 Расширенные данные"),
    )
    return kb


def _format_unix_time(ts: int, timezone_shift: int = 0) -> str:
    """
    Форматирует Unix-время в локальное HH:MM с учётом timezone сдвига (в секундах).
    """
    try:
        dt = datetime.utcfromtimestamp(ts + timezone_shift)
        return dt.strftime("%H:%M")
    except (OSError, OverflowError, ValueError, TypeError):
        return "—"


def _format_current_weather(city: str, data: dict) -> str:
    main = data.get("main", {})
    wind = data.get("wind", {})
    weather_list = data.get("weather") or [{}]
    weather = weather_list[0]

    temp = main.get("temp")
    feels = main.get("feels_like")
    humidity = main.get("humidity")
    pressure = main.get("pressure")
    wind_speed = wind.get("speed")
    desc = weather.get("description", "нет данных")

    lines = [
        f"<b>Погода в {city}</b>",
        f"Описание: {desc}",
    ]
    if temp is not None:
        lines.append(f"Температура: {temp}°C (ощущается как {feels}°C)")
    if humidity is not None:
        lines.append(f"Влажность: {humidity}%")
    if pressure is not None:
        lines.append(f"Давление: {pressure} гПа")
    if wind_speed is not None:
        lines.append(f"Ветер: {wind_speed} м/с")

    return "\n".join(lines)


def _get_or_ask_location(message: telebot.types.Message) -> Optional[Tuple[float, float]]:
    user_id = message.from_user.id
    loc = user_last_location.get(user_id)
    if loc:
        return loc
    city = user_last_city.get(user_id)
    if city:
        coords = get_coordinates(city)
        if coords:
            user_last_location[user_id] = coords
            return coords
    bot.reply_to(
        message,
        "Не удалось определить местоположение.\n"
        "Сначала отправьте город (кнопка «Текущая погода по городу»)\n"
        "или поделитесь геолокацией (кнопка «Погода по геолокации»).",
    )
    return None


# =========================
# COMMANDS / MENU
# =========================

@bot.message_handler(commands=["start"])
def cmd_start(message: telebot.types.Message) -> None:
    # /start должен сбрасывать незавершённые сценарии
    try:
        bot.clear_step_handler_by_chat_id(message.chat.id)
    except Exception:
        pass

    bot.send_message(
        message.chat.id,
        "Привет! Я погодный бот.\n"
        "Выберите действие на клавиатуре ниже.",
        reply_markup=_build_main_menu(),
    )


# =========================
# 1. ТЕКУЩАЯ ПОГОДА ПО ГОРОДУ
# =========================

@bot.message_handler(func=lambda m: m.text == "☀️ Текущая погода по городу")
def ask_city_weather(message: telebot.types.Message) -> None:
    msg = bot.reply_to(message, "Введите название города:")
    bot.register_next_step_handler(msg, handle_city_weather)


def handle_city_weather(message: telebot.types.Message) -> None:
    if _is_command_text(message.text):
        _reset_flow_and_show_menu(message)
        return

    city = (message.text or "").strip()
    if not city:
        bot.reply_to(message, "Город не распознан.")
        return

    coords = get_coordinates(city)
    if not coords:
        bot.reply_to(
            message,
            f"Не удалось найти город «{city}» или произошла ошибка при обращении к сервису погоды.",
        )
        return

    lat, lon = coords
    data = get_weather_by_coordinates(lat, lon)
    if not data:
        bot.reply_to(message, "Не удалось получить погоду для этого города.")
        return

    user_id = message.from_user.id
    user_last_city[user_id] = city
    user_last_location[user_id] = (lat, lon)

    bot.send_message(
        message.chat.id,
        _format_current_weather(city, data),
        reply_markup=_build_main_menu(),
    )


# =========================
# 2. ПРОГНОЗ НА 5 ДНЕЙ (INLINE)
# =========================

@bot.message_handler(func=lambda m: m.text == "📅 Прогноз на 5 дней")
def show_forecast_menu(message: telebot.types.Message) -> None:
    coords = _get_or_ask_location(message)
    if not coords:
        return

    lat, lon = coords
    forecast = get_forecast_by_coordinates(lat, lon)
    if not forecast:
        bot.reply_to(message, "Не удалось получить прогноз погоды.")
        return

    user_id = message.from_user.id
    user_forecast_cache[user_id] = forecast

    # Собираем список уникальных дней
    from collections import OrderedDict

    days = OrderedDict()
    for item in forecast.get("list", []):
        dt_txt = item.get("dt_txt", "")
        day = dt_txt.split(" ")[0]
        days.setdefault(day, []).append(item)

    kb = types.InlineKeyboardMarkup()
    for idx, day in enumerate(days.keys()):
        kb.add(
            types.InlineKeyboardButton(
                text=day,
                callback_data=f"forecast_day:{idx}",
            )
        )

    kb.add(types.InlineKeyboardButton(text="Закрыть", callback_data="forecast_close"))

    bot.send_message(
        message.chat.id,
        "Выберите день, чтобы посмотреть подробный прогноз:",
        reply_markup=kb,
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("forecast_day:"))
def handle_forecast_day(call: telebot.types.CallbackQuery) -> None:
    user_id = call.from_user.id
    forecast = user_forecast_cache.get(user_id)
    if not forecast:
        bot.answer_callback_query(call.id, "Прогноз устарел, запросите ещё раз.")
        return

    from collections import OrderedDict

    days = OrderedDict()
    for item in forecast.get("list", []):
        dt_txt = item.get("dt_txt", "")
        day = dt_txt.split(" ")[0]
        days.setdefault(day, []).append(item)

    try:
        idx = int(call.data.split(":")[1])
    except (IndexError, ValueError):
        bot.answer_callback_query(call.id, "Ошибка выбора дня.")
        return

    if idx < 0 or idx >= len(days):
        bot.answer_callback_query(call.id, "День не найден.")
        return

    day_key = list(days.keys())[idx]
    entries = days[day_key]

    lines = [f"<b>Прогноз на {day_key}</b>"]
    for item in entries:
        dt_txt = item.get("dt_txt", "")
        time_part = dt_txt.split(" ")[1][:5] if " " in dt_txt else dt_txt
        main = item.get("main", {})
        temp = main.get("temp")
        desc = (item.get("weather") or [{}])[0].get("description", "нет данных")
        lines.append(f"{time_part}: {temp}°C, {desc}")

    text = "\n".join(lines)

    # Клавиатура остаётся той же, мы просто редактируем сообщение
    bot.edit_message_text(
        text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=call.message.reply_markup,
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "forecast_close")
def handle_forecast_close(call: telebot.types.CallbackQuery) -> None:
    # Удаляем сообщение с инлайн-клавиатурой
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    bot.answer_callback_query(call.id)


# =========================
# 3. ПОГОДА ПО ГЕОЛОКАЦИИ
# =========================

@bot.message_handler(func=lambda m: m.text == "📍 Погода по геолокации")
def ask_location(message: telebot.types.Message) -> None:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(types.KeyboardButton("Отправить местоположение", request_location=True))
    bot.send_message(
        message.chat.id,
        "Нажмите кнопку ниже, чтобы отправить свою геолокацию.",
        reply_markup=kb,
    )


@bot.message_handler(content_types=["location"])
def handle_location(message: telebot.types.Message) -> None:
    if not message.location:
        bot.reply_to(message, "Геолокация не распознана.")
        return

    lat = message.location.latitude
    lon = message.location.longitude

    data = get_weather_by_coordinates(lat, lon)
    if not data:
        bot.reply_to(message, "Не удалось получить погоду по этой геолокации.")
        return

    user_id = message.from_user.id
    user_last_location[user_id] = (lat, lon)
    user_last_city[user_id] = f"{lat:.2f}, {lon:.2f}"

    bot.send_message(
        message.chat.id,
        _format_current_weather("вашей точке", data),
        reply_markup=_build_main_menu(),
    )


# =========================
# 4. ПОДПИСКА НА УВЕДОМЛЕНИЯ
# =========================

@bot.message_handler(func=lambda m: m.text == "🔔 Погодные уведомления")
def notifications_menu(message: telebot.types.Message) -> None:
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Включить", callback_data="notify_on"),
        types.InlineKeyboardButton("⛔ Выключить", callback_data="notify_off"),
    )
    bot.send_message(
        message.chat.id,
        "Подписка на уведомления каждые 2 часа по последнему местоположению.",
        reply_markup=kb,
    )


@bot.callback_query_handler(func=lambda call: call.data in ("notify_on", "notify_off"))
def handle_notify_toggle(call: telebot.types.CallbackQuery) -> None:
    user_id = call.from_user.id
    if call.data == "notify_on":
        user_notifications[user_id] = True
        bot.answer_callback_query(call.id, "Уведомления включены.")
        bot.send_message(
            call.message.chat.id,
            "Уведомления включены. Я буду проверять погоду каждые 2 часа.",
            reply_markup=_build_main_menu(),
        )
    else:
        user_notifications[user_id] = False
        bot.answer_callback_query(call.id, "Уведомления выключены.")
        bot.send_message(
            call.message.chat.id,
            "Уведомления выключены.",
            reply_markup=_build_main_menu(),
        )


def _notifications_worker() -> None:
    while True:
        time.sleep(2 * 60 * 60)  # каждые 2 часа
        for user_id, enabled in list(user_notifications.items()):
            if not enabled:
                continue
            coords = user_last_location.get(user_id)
            if not coords:
                continue
            lat, lon = coords
            data = get_weather_by_coordinates(lat, lon)
            if not data:
                continue
            condition = (data.get("weather") or [{}])[0].get("description", "")
            last_cond = user_last_condition.get(user_id)
            # Отправляем, если изменилось или дождь/снег
            if condition != last_cond or any(
                word in condition.lower() for word in ("дожд", "rain", "снег", "snow")
            ):
                user_last_condition[user_id] = condition
                try:
                    bot.send_message(
                        user_id,
                        "Обновление погоды по вашей подписке:\n"
                        + _format_current_weather("вашей точке", data),
                    )
                except Exception:
                    continue


threading.Thread(target=_notifications_worker, daemon=True).start()


# =========================
# 5. СРАВНЕНИЕ ГОРОДОВ
# =========================

@bot.message_handler(func=lambda m: m.text == "📊 Сравнение городов")
def compare_cities_ask(message: telebot.types.Message) -> None:
    msg = bot.reply_to(
        message,
        "Введите два города через запятую, например:\n"
        "<code>Москва, Санкт-Петербург</code>",
    )
    bot.register_next_step_handler(msg, handle_compare_cities)


def handle_compare_cities(message: telebot.types.Message) -> None:
    if _is_command_text(message.text):
        _reset_flow_and_show_menu(message)
        return

    text = (message.text or "").strip()
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) != 2:
        bot.reply_to(message, "Нужно ввести ровно два города через запятую.")
        return

    city1, city2 = parts
    result_lines = []

    def fetch(city: str):
        coords = get_coordinates(city)
        if not coords:
            return city, None
        lat, lon = coords
        data = get_weather_by_coordinates(lat, lon)
        return city, data

    c1, w1 = fetch(city1)
    c2, w2 = fetch(city2)

    if not w1 or not w2:
        bot.reply_to(
            message,
            "Не удалось получить погоду хотя бы для одного из городов.",
        )
        return

    t1 = w1.get("main", {}).get("temp")
    t2 = w2.get("main", {}).get("temp")
    h1 = w1.get("main", {}).get("humidity")
    h2 = w2.get("main", {}).get("humidity")

    result_lines.append("<b>Сравнение городов</b>")
    result_lines.append(f"{'Параметр':<12} | {c1:<15} | {c2:<15}")
    result_lines.append("-" * 44)
    result_lines.append(
        f"{'Температура':<12} | {t1}°C{' ' * (9 - len(str(int(t1)))) if t1 is not None else '':<1} | {t2}°C"
        if t1 is not None and t2 is not None
        else "Температура: данные не полные"
    )
    result_lines.append(
        f"{'Влажность':<12} | {h1}%{' ' * (9 - len(str(int(h1)))) if h1 is not None else '':<1} | {h2}%"
        if h1 is not None and h2 is not None
        else "Влажность: данные не полные"
    )

    bot.send_message(
        message.chat.id,
        "\n".join(result_lines),
        reply_markup=_build_main_menu(),
    )


# =========================
# 6. РАСШИРЕННЫЕ ДАННЫЕ
# =========================

@bot.message_handler(func=lambda m: m.text == "🌈 Расширенные данные")
def extended_ask(message: telebot.types.Message) -> None:
    msg = bot.reply_to(
        message,
        "Введите город <b>или</b> координаты в формате <code>широта, долгота</code>:",
    )
    bot.register_next_step_handler(msg, handle_extended)


def handle_extended(message: telebot.types.Message) -> None:
    if _is_command_text(message.text):
        _reset_flow_and_show_menu(message)
        return

    text = (message.text or "").strip()

    lat: Optional[float] = None
    lon: Optional[float] = None
    city_for_title: str = text

    # Пробуем распарсить как координаты
    parts = [p.strip().replace(",", ".") for p in text.split() if p.strip()]
    if len(parts) == 2:
        try:
            lat = float(parts[0])
            lon = float(parts[1])
            city_for_title = f"{lat:.2f}, {lon:.2f}"
        except ValueError:
            lat = lon = None

    if lat is None or lon is None:
        # Пытаемся как город
        coords = get_coordinates(text)
        if not coords:
            bot.reply_to(message, "Не удалось распознать ни город, ни координаты.")
            return
        lat, lon = coords

    weather = get_weather_by_coordinates(lat, lon)
    air = get_air_quality_by_coordinates(lat, lon)

    if not weather:
        bot.reply_to(message, "Не удалось получить метеоданные для этой точки.")
        return

    sys = weather.get("sys", {})
    timezone_shift = weather.get("timezone") or 0
    main = weather.get("main", {})
    wind = weather.get("wind", {})
    clouds = weather.get("clouds", {})
    weather_list = weather.get("weather") or [{}]
    w0 = weather_list[0]

    sunrise = sys.get("sunrise")
    sunset = sys.get("sunset")

    lines = [f"<b>Расширенные данные для {city_for_title}</b>"]
    lines.append(f"Описание: {w0.get('description', 'нет данных')}")
    lines.append(f"Температура: {main.get('temp')}°C (ощущается как {main.get('feels_like')}°C)")
    lines.append(f"Влажность: {main.get('humidity')}%")
    lines.append(f"Давление: {main.get('pressure')} гПа")
    lines.append(f"Ветер: {wind.get('speed')} м/с")
    lines.append(f"Облачность: {clouds.get('all')}%")
    if sunrise and sunset:
        sunrise_str = _format_unix_time(sunrise, timezone_shift)
        sunset_str = _format_unix_time(sunset, timezone_shift)
        lines.append(f"Восход: {sunrise_str}")
        lines.append(f"Закат: {sunset_str}")

    if air and air.get("text_report"):
        lines.append("")
        lines.append(air["text_report"])

    bot.send_message(
        message.chat.id,
        "\n".join(lines),
        reply_markup=_build_main_menu(),
    )


if __name__ == "__main__":
    bot.infinity_polling()
