FROM python:3.12-slim

# Только UTC-данные в логах, буферизация отключена (логи сразу идут в docker logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Сначала зависимости — слой кэшируется отдельно от кода
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py storage.py reports.py menus.py ./

# Небольшой non-root пользователь для безопасности
RUN useradd -m bot && mkdir -p /data && chown -R bot:bot /data /app
USER bot

# База данных лежит в смонтированном томе /data
ENV DB_PATH=/data/worktime.db

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('https://api.telegram.org', timeout=4)" || exit 1

CMD ["python", "bot.py"]
