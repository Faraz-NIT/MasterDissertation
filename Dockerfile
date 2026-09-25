FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY configs ./configs
RUN useradd --create-home researcher && chown -R researcher:researcher /app
USER researcher
ENTRYPOINT ["ega"]
CMD ["doctor"]
