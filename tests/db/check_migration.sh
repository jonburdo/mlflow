#!/bin/bash
set -ex

cd tests/db

# MLflow 3.8 imports FallbackAsyncAdaptedQueuePool, which SQLAlchemy 2.1 removed.
pip install mlflow==3.8.0 'sqlalchemy<2.1'
python check_migration.py pre-migration
# Install mlflow from the repository
pip install -e ../..
mlflow db upgrade $MLFLOW_TRACKING_URI
python check_migration.py post-migration
