"""
project_paths.py

Single source of truth for repository paths. The course-mandated repo
layout splits code across src/backend, src/ml_model, src/aws and
src/frontend; this module puts all of them on sys.path so the existing
flat imports (``from drift_engine import detect_drift``) keep working
from any entry point.
"""

import os
import sys

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SRC_DIR)

BACKEND_DIR = os.path.join(SRC_DIR, "backend")
ML_DIR = os.path.join(SRC_DIR, "ml_model")
AWS_DIR = os.path.join(SRC_DIR, "aws")
COLLECTORS_DIR = os.path.join(AWS_DIR, "collectors")
LAMBDA_DIR = os.path.join(AWS_DIR, "lambda")
TERRAFORM_DIR = os.path.join(AWS_DIR, "terraform")
FRONTEND_DIR = os.path.join(SRC_DIR, "frontend")

DATASET_DIR = os.path.join(ROOT_DIR, "dataset")
RAW_DATA_DIR = os.path.join(DATASET_DIR, "raw")
PROCESSED_DATA_DIR = os.path.join(DATASET_DIR, "processed")
MODELS_DIR = os.path.join(ML_DIR, "models")
RESULTS_DIR = os.path.join(ROOT_DIR, "results")

for _d in (BACKEND_DIR, ML_DIR, COLLECTORS_DIR, LAMBDA_DIR, AWS_DIR, FRONTEND_DIR, SRC_DIR):
    if _d not in sys.path:
        sys.path.insert(0, _d)
