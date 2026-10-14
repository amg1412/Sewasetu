"""Single place that reads configuration (app.ini + SS_* environment overrides).

Both the web app and the scheduled jobs import this. The March 2026 'consolidation'
(CR-2026-031) renamed settings.ini to app.ini but left the nightly job reading the
old name, so the job crashed every night for months. One loader means that cannot
happen again.
"""
import os
import configparser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "app.ini")

ENV_MAP = {
    "SS_DB_HOST": ("database", "host"), "SS_DB_PORT": ("database", "port"),
    "SS_DB_NAME": ("database", "name"), "SS_DB_USER": ("database", "user"),
    "SS_DB_PASSWORD": ("database", "password"),
    "SS_SECRET_KEY": ("app", "secret_key"), "SS_SMS_URL": ("app", "sms_gateway_url"),
    "SS_UPLOAD_DIR": ("app", "upload_dir"),
}


def load_config():
    config = configparser.ConfigParser()
    with open(CONFIG_PATH) as fh:          # fail loudly if the file is missing
        config.read_file(fh)
    for key, (section, option) in ENV_MAP.items():
        if os.environ.get(key):
            config.set(section, option, os.environ[key])
    return config
