from logging import INFO as LOG_LEVEL_INFO
from enum import IntEnum
from pathlib import Path


class AppStatus(IntEnum):
    ERROR = 0
    READY = 1
    BUSY = 2


APP_NAME = 'grabby'
APP_VERSION = '0.0.1'

# FIXME: is using home() a problem?
DEFAULT_DESTINATION_BASE = Path.home() / APP_NAME / 'grabs'
DEFAULT_MOUNT_BASE = Path.home() / APP_NAME / 'mounts'
DEFAULT_LOG_LEVEL = LOG_LEVEL_INFO

GRABBY_CONFIG_ENV_VAR = 'GRABBY_CONFIG_PATH'
