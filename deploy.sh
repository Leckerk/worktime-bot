#!/usr/bin/env bash
#
# deploy.sh — деплой телеграм-бота учёта рабочего времени в Docker на VPS.
#
# Использование:
#   1) Скопируйте проект на сервер, например:
#        scp -r . user@ваш-vps:/opt/worktime-bot
#      (или git clone репозитория в /opt/worktime-bot)
#   2) На сервере:
#        cd /opt/worktime-bot
#        ./deploy.sh init        # первый запуск: создаст .env с шаблоном токена
#        nano .env               # вписать TELEGRAM_BOT_TOKEN (и при желании BOT_TZ)
#        ./deploy.sh             # собрать образ и запустить контейнер
#
# Команды:
#   ./deploy.sh            — тоже самое, что update
#   ./deploy.sh init       — подготовить .env и data/ (первый деплой)
#   ./deploy.sh update     — пересобрать образ и перезапустить контейнер
#   ./deploy.sh restart    — перезапустить без пересборки
#   ./deploy.sh logs       — показать последние логи (Ctrl+C для выхода)
#   ./deploy.sh status     — состояние контейнера
#   ./deploy.sh stop       — остановить бота
#   ./deploy.sh backup     — резервная копия базы данных в backups/
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

COMPOSE_CMD=""

log()  { echo -e "\033[1;32m[deploy]\033[0m $*"; }
err()  { echo -e "\033[1;31m[deploy] ОШИБКА:\033[0m $*" >&2; }

detect_compose() {
    if docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose >/dev/null 2>&1 && docker-compose version >/dev/null 2>&1; then
        COMPOSE_CMD="docker-compose"
    else
        err "Не найден Docker Compose. Установите Docker Engine + plugin compose:"
        err "  curl -fsSL https://get.docker.com | sh"
        exit 1
    fi
}

check_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        err "Docker не установлен. Установка: curl -fsSL https://get.docker.com | sh"
        err "Затем добавьте пользователя в группу: sudo usermod -aG docker \$USER (и перезайдите в систему)"
        exit 1
    fi
    if ! docker info >/dev/null 2>&1; then
        err "Нет доступа к демону Docker. Запустите через sudo или выполните:"
        err "  sudo usermod -aG docker \$USER   # после чего перезайти на сервер"
        exit 1
    fi
}

ensure_env() {
    mkdir -p data
    if [[ ! -f .env ]]; then
        cat > .env <<'EOF'
# Токен бота от @BotFather (обязательно)
TELEGRAM_BOT_TOKEN=

# Часовой пояс для напоминаний и статистики (по умолчанию Europe/Moscow)
BOT_TZ=Europe/Moscow
EOF
        chmod 600 .env
        log "Создан файл .env — заполните TELEGRAM_BOT_TOKEN и запустите: ./deploy.sh update"
        exit 0
    fi
    chmod 600 .env 2>/dev/null || true
}

validate_env() {
    # shellcheck disable=SC1091
    set -a; source .env; set +a
    if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
        err "TELEGRAM_BOT_TOKEN пуст. Откройте .env и вставьте токен от @BotFather."
        exit 1
    fi
    export BOT_TZ="${BOT_TZ:-Europe/Moscow}"
}

cmd="${1:-update}"

case "$cmd" in
    init)
        check_docker
        ensure_env
        validate_env
        detect_compose
        log "Подготовка завершена. Запуск сборки: ./deploy.sh update"
        $COMPOSE_CMD up -d --build
        log "Готово. Логи: ./deploy.sh logs"
        ;;
    update|deploy|"")
        check_docker
        ensure_env
        validate_env
        detect_compose
        log "Пересборка образа и перезапуск..."
        $COMPOSE_CMD up -d --build
        ;;
    restart)
        check_docker; detect_compose
        $COMPOSE_CMD restart
        ;;
    logs)
        check_docker; detect_compose
        $COMPOSE_CMD logs --tail=100 -f
        ;;
    status)
        check_docker; detect_compose
        $COMPOSE_CMD ps
        ;;
    stop|down)
        check_docker; detect_compose
        $COMPOSE_CMD down
        ;;
    backup)
        [[ -f data/worktime.db ]] || { err "База не найдена: $APP_DIR/data/worktime.db"; exit 1; }
        mkdir -p backups
        ts="$(date +%Y%m%d_%H%M%S)"
        cp data/worktime.db "backups/worktime_${ts}.db"
        # чистим копии старше 30 дней
        find backups -name 'worktime_*.db' -mtime +30 -delete
        log "Резервная копия: backups/worktime_${ts}.db"
        ;;
    *)
        err "Неизвестная команда: $cmd"
        sed -n '3,25p' "$0"
        exit 1
        ;;
esac

log "Текущее состояние:"
$COMPOSE_CMD ps 2>/dev/null || true
