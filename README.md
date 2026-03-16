# Weather Telegram Bot

Учебный Telegram‑бот на Python, который показывает погоду через OpenWeather и предоставляет удобный интерфейс в Telegram: текущая погода, прогноз, геолокация, сравнение городов, качество воздуха и уведомления.

## Features

- **Текущая погода по городу**: температура, «ощущается как», давление, влажность, ветер, облачность, восход/закат.
- **Прогноз на 5 дней**: 3‑часовой прогноз с выбором даты через inline‑клавиатуру и кнопками «Назад» / «Закрыть».
- **Геолокация**: приём `location` из Telegram и показ погоды в текущей точке.
- **Уведомления**: подписка на погодные уведомления с выбором интервала (1 / 2 / 3 / 6 часов).
- **Сравнение городов**: сравнение температуры и влажности в двух городах в табличном виде (`<pre>`).
- **Расширенные данные**: ввод города или координат (`"53.9, 27.56"` или `"53.9 27.56"`), детальная информация по погоде и времени восхода/заката.
- **Качество воздуха**: запрос Air Pollution API, анализ загрязнителей (PM2.5, PM10, NO₂, O₃, SO₂, CO) и сводный вывод на русском.

## Technologies

- **Python**
- **Telegram Bot API** (через библиотеку `pyTelegramBotAPI`)
- **OpenWeather API** (Current Weather, Forecast, Air Pollution)
- **python-dotenv** (загрузка переменных окружения из `.env`)

## Installation

### Clone repository

```bash
git clone https://github.com/TatsianaU/Weather-app.git
cd Weather-app
```

### Create and activate virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure environment variables

Скопируйте пример `.env`:

```bash
# Windows
copy .env.example .env

# Linux / macOS
cp .env.example .env
```

Откройте `.env` и подставьте свои значения:

```text
OW_API_KEY=your_openweather_key
BOT_TOKEN=your_telegram_token
```

## Usage

### Run bot

```bash
python bot.py
```

В Telegram найдите своего бота по имени, отправьте команду `/start` и используйте главное меню с кнопками:

- `☀️ Текущая погода по городу`
- `📍 Погода по геолокации`
- `📅 Прогноз на 5 дней`
- `🔔 Погодные уведомления`
- `📊 Сравнение городов`
- `🌈 Расширенные данные`
