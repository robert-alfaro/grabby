import logging
import threading
import yaml

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Union
from watchdog.observers import Observer as FileSystemObserver
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

from const import (
    APP_NAME,
    DEFAULT_DESTINATION_BASE,
    DEFAULT_MOUNT_BASE,
    DEFAULT_LOG_LEVEL
)
from homeassistant import HomeAssistantConfig
from organizer import MediaInfoTag, RenameMethod


LOG = logging.getLogger(__name__)


@dataclass
class GrabConfig:
    path: str
    never_delete: bool
    types: List[str]
    rename_method: Optional[RenameMethod]
    rename_as_prefix: bool
    mtime: bool
    media_tag: Optional[MediaInfoTag]

@dataclass
class ChownIds:
    user: Union[int, str]
    group: Union[int, str]

@dataclass
class AppConfig:
    delete_after_copy: bool
    destination_base: Path
    mount_base: Path
    grabs: List[GrabConfig]
    log_level: int
    chown: Optional[ChownIds]
    home_assistant: Optional[HomeAssistantConfig]


class AppConfigFile(FileSystemEventHandler):
    def __init__(self, path: Path):
        super(FileSystemEventHandler, self).__init__()

        self._lock = threading.Lock()
        self._config = AppConfig(
            delete_after_copy = True,
            destination_base = DEFAULT_DESTINATION_BASE,
            mount_base = DEFAULT_MOUNT_BASE,
            grabs = [],
            log_level = DEFAULT_LOG_LEVEL,
            chown = None,
            home_assistant = None
        )

        # path may be the config file itself,
        #   or a directory containing the config file.
        if path.is_dir():
            possible_config = path / f'{APP_NAME}.yaml'
            if possible_config.is_file():
                self.path = possible_config
            else:
                raise FileNotFoundError(f"No config file found in {path}/{APP_NAME}.yaml")
        elif path.is_file():
            self.path = path
        elif path.suffix == '.yaml' and not path.exists():
            # new config file
            self.path = self.write_new_file(path)
        else:
            LOG.error(f"Invalid config path: {path}")
            raise FileExistsError(f"Invalid config path: {path}")

        self.load()

        self._timer = None
        self._observer = FileSystemObserver(generate_full_events=True)
        self._observer.schedule(self, path.as_posix(), event_filter=[FileModifiedEvent])
        self._observer.start()

    def __str__(self):
        return self._config.__str__()

    def on_modified(self, event):
        # Cancel existing timer if one is running
        if self._timer is not None:
            self._timer.cancel()

        # Schedule reload with a 1-second delay
        self._timer = threading.Timer(1.0, self.reload)
        self._timer.start()

    def load(self):
        """
        Load the application configuration from the YAML file.
        """
        with self._lock:
            with open(self.path.as_posix(), "rb") as f:
                raw_config = yaml.safe_load(f)

        self._config.delete_after_copy = raw_config.get('delete_after_copy', True)
        setattr(self, 'delete_after_copy', self._config.delete_after_copy)

        destination_base = raw_config.get('destination_base')
        self._config.destination_base = Path(destination_base) if destination_base else DEFAULT_DESTINATION_BASE
        setattr(self, 'destination_base', self._config.destination_base)

        mount_base = raw_config.get('mount_base')
        self._config.mount_base = Path(mount_base) if mount_base else DEFAULT_MOUNT_BASE
        setattr(self, 'mount_base', self._config.mount_base)

        log_level = raw_config.get('log_level')
        self._config.log_level = logging._nameToLevel.get(log_level, DEFAULT_LOG_LEVEL)
        setattr(self, 'log_level', self._config.log_level)

        chown = raw_config.get('chown')
        self._config.chown = ChownIds(chown.get('user'), chown.get('group')) if chown else None
        setattr(self, 'chown', self._config.chown)

        grab_configs = []
        self._config.grabs = grab_configs
        setattr(self, 'grabs', grab_configs)

        for path in raw_config['grabs']:
            grab = raw_config['grabs'][path]
            rename_method = RenameMethod.NONE.name
            as_prefix = True
            mtime = False
            media_tag = None

            if grab.get('rename'):
                rename_method = grab['rename'].get('method', rename_method)
                as_prefix = grab['rename'].get('as_prefix', as_prefix)
                mtime = 'mtime' in grab['rename']
                mediainfo = grab.get('rename').get('mediainfo')
                if mediainfo:
                    try:
                        media_tag = MediaInfoTag(
                            group=mediainfo['group'],
                            name=mediainfo['name'],
                            tz=mediainfo['tz'],
                            substrs=mediainfo.get('substrs')
                        )
                    except KeyError as e:
                        media_tag = None
                        LOG.error(f"Missing mediainfo tag key: {e}")

            grab_config = GrabConfig(
                path = path,
                never_delete = grab.get('never_delete', False),
                types = [t.lower() for t in grab.get('types', [])],
                mtime = mtime,
                media_tag = media_tag,
                rename_method = RenameMethod[rename_method.upper()],
                rename_as_prefix = as_prefix
            )
            grab_configs.append(grab_config)

        home_assistant = raw_config.get('home_assistant')
        self._config.home_assistant = HomeAssistantConfig(
            base_url = home_assistant.get('base_url', ""),
            api_token = home_assistant.get('api_token', ""),
        ) if home_assistant else None
        setattr(self, 'home_assistant', self._config.home_assistant)

        LOG.debug(f"Configuration:\n{self._config}")

    def reload(self):
        LOG.info(f"Reloading configuration from {self.path}")

        self.load()

        # update log level
        LOG.setLevel(self._config.log_level)

    def write_new_file(self, path: Path):
        c_dict = asdict(self._config)
        c_dict.pop('home_assistant')
        c_dict['destination_base'] = self._config.destination_base.as_posix()
        c_dict['mount_base'] = self._config.mount_base.as_posix()
        c_dict['log_level'] = logging._levelToName[self._config.log_level]
        config_yaml_s = f"# {APP_NAME} configuration\n" + yaml.dump(c_dict)

        with open(path.as_posix(), "w") as f:
            f.write(config_yaml_s)

        return path

    def lock(self):
        return self._lock.acquire()

    def unlock(self):
        return self._lock.release()

    def is_locked(self):
        return self._lock.locked()

    def get_config(self) -> AppConfig:
        return self._config
