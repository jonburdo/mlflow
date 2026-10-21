FROM python:3.11

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ARG DEPENDENCIES

RUN uv pip install --system psycopg2 pymysql mysqlclient pytest pytest-cov pytest-asyncio
# Match the RHOAI 3.4 runtime lock; SQLAlchemy 2.1 switches the default PostgreSQL driver.
RUN echo "${DEPENDENCIES}" > /tmp/requirements.txt && \
    uv pip install --system -r /tmp/requirements.txt 'sqlalchemy==2.0.49'

RUN uv pip list
