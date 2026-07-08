# Day 4: добавлены ffmpeg и deno (JS-рантайм) — оба нужны yt-dlp даже
# для одного только extract_info (превью), не только для скачивания:
# YouTube требует расшифровку через JS-рантайм (yt-dlp-ejs) уже на этапе
# получения метаданных. См. PROJECT_SPEC §6.4.
FROM python:3.13-slim
WORKDIR /app
# ffmpeg — системный бинарник (НЕ pip-пакет с тем же именем — частая
# ошибка, которая молча ничего не скачивает). deno — JS-рантайм для
# yt-dlp-ejs, устанавливается официальным скриптом (в apt его нет).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://deno.land/install.sh | sh \
    && mv /root/.deno/bin/deno /usr/local/bin/deno \
    && rm -rf /root/.deno
RUN pip install --no-cache-dir uv
COPY pyproject.toml alembic.ini ./
COPY src ./src
COPY infra/alembic ./infra/alembic
# Day 9: FTL-локали. Нужны и боту (рендерит строки), и воркеру — образ
# общий; воркер строки не рендерит, но COPY дешёвый и держит образы
# идентичными. Путь /app/locales совпадает с locales_dir() (parents[3]
# от src/presentation/telegram/i18n.py → /app).
COPY locales ./locales
RUN uv pip install --system --no-cache -e .
COPY infra/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "src.main"]
