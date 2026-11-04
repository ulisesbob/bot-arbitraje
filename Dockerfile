FROM python:3.12-slim

WORKDIR /app
COPY arbitraje.py comandos.py ./

# La config (token, chat id, umbral) viene por variables de entorno:
#   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
# El resto usa los valores por defecto de arbitraje.py; /umbral los cambia en caliente.
ENV PYTHONUNBUFFERED=1

CMD ["python", "arbitraje.py"]
