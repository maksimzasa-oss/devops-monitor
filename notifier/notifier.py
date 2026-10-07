import logging
import os
import time
from collections import defaultdict, deque

import docker
from flask import Flask, jsonify, request

# Настройка красивого логирования в консоль Docker
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MAX_RESTARTS = int(os.getenv("MAX_RESTARTS", "2"))
RESTART_WINDOW = int(os.getenv("RESTART_WINDOW_SEC", "900"))

app = Flask(__name__)
docker_client = docker.from_env()
restarts = defaultdict(deque)


def recent_restarts(name):
    history = restarts[name]
    now = time.time()
    while history and now - history[0] > RESTART_WINDOW:
        history.popleft()
    return len(history)


@app.post("/alert")
def alert():
    data = request.get_json(force=True)
    name = data["container"]
    
    # Красиво форматируем лог инцидента для вывода в консоль
    details = (
        f"[Контейнер: {name} | "
        f"Причина: {data.get('reason')} | "
        f"Аномальных окон: {int(data.get('share', 0) * 100)}% | "
        f"RAM: {data.get('ram')}% | CPU: {data.get('cpu')}%]"
    )

    # Проверка защиты от лавины перезапусков (Anti-Flapping)
    if recent_restarts(name) >= MAX_RESTARTS:
        logging.error("🔴 КРИТИЧЕСКАЯ АВАРИЯ: Автохилинг заблокирован лимитами! %s. Требуется вмешательство человека!", details)
        return jsonify(status="blocked"), 200

    try:
        # Перезапуск контейнера через Docker SDK API
        docker_client.containers.get(name).restart()
    except docker.errors.DockerException as exc:
        logging.error("❌ ОШИБКА: Не удалось перезапустить %s. %s. Ошибка API: %s", name, details, exc)
        return jsonify(status="error"), 500

    # Записываем время успешного рестарта в историю
    restarts[name].append(time.time())
    logging.warning("🔧 АВТОХИЛИНГ: Обнаружена аномалия, контейнер успешно перезапущен! %s", details)
    return jsonify(status="restarted"), 200


@app.get("/health")
def health():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
