#!/bin/bash
set -ex

cd tests/db

# Install the latest released version before the rhoai-3.3 code line.
pip install mlflow==3.5.1
python check_migration.py pre-migration
# Install mlflow from the repository
pip install -e ../..
mlflow db upgrade $MLFLOW_TRACKING_URI
python check_migration.py post-migration
