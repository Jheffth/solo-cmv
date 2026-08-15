import os
from dotenv import load_dotenv

load_dotenv()

APP_NAME = "Solo CMV"
APP_VERSION = "0.1.0"

SECRET_KEY = os.getenv("SECRET_KEY", "troque-esta-chave-em-producao-solo-cmv")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./solo_cmv.db")
