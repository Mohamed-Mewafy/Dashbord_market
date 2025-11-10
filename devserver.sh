#!/bin/sh
source .venv/bin/activate
python -u -m flask --app main run --debug -p ${PORT:-8080}