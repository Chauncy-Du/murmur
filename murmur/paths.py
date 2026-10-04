"""Default local storage locations, independent of AppData redirection."""
from pathlib import Path


PROJECT_ROOT = Path(r'D:\LocalProjects\MurMur')


def data_dir():
    return PROJECT_ROOT / 'data'


def runtime_root():
    return PROJECT_ROOT / 'runtimes'


def model_root():
    return PROJECT_ROOT / 'models'


def startup_error_log():
    return data_dir() / 'startup-error.log'
