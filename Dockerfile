FROM python:3.11-slim

WORKDIR /app

COPY requierments.txt .
RUN pip install --no-cache-dir -r requierments.txt
COPY . .

CMD ["python", "bot.py"]