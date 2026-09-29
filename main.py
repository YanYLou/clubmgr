import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOMAIN_DIR = os.path.join(ROOT_DIR, "domain")
DATA_DIR = os.path.join(ROOT_DIR, "data")

DB_PATH = os.path.join(DATA_DIR, "data.db")