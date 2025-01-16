import logging
import os
import sys
import psutil
import pyudev
import re
import shutil
import subprocess
import threading

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import List, Optional

from config import AppConfigFile
from const import (
    AppStatus,
    APP_NAME,
    APP_VERSION,
    GRABBY_CONFIG_ENV_VAR
)
from homeassistant import HomeAssistantAPI
from organizer import organize_files_in_place


@dataclass
class AppState:
    status: AppStatus
    media_count: int
    progress: int
    card_id: str


LOG = logging.getLogger(APP_NAME)

app_config: AppConfigFile = None
app_state: AppState = None
home_assistant: HomeAssistantAPI = None
processed_devices = set()
device_lock = threading.Lock()


def get_mounts(device_node: str) -> List[str]:
    """
    Retrieve the list of mount points for a given device.

    :param device_node: The device node path (e.g., /dev/sdX, /dev/mmcXpY).
    :returns: List of mount points for the device.
    """
    mounts = []
    for partition in psutil.disk_partitions():
        if partition.device == device_node:
            mounts.append(partition.mountpoint)
    return mounts


def mount_device(device_node: str) -> Path:
    """
    Mount the device to the application's mount base.

    :param device_node: The device node path (e.g., /dev/sdX, /dev/mmcXpY).
    :return: Path where the device was mounted.
    :raises RuntimeError: If the device cannot be mounted.
    """

    # already mounted?
    mounts = get_mounts(device_node)
    if mounts:
        LOG.info(f"Found {device_node} mounted to {mounts[0]}")
        return Path(mounts[0])

    # otherwise, attempt to mount
    try:
        mount_base = app_config.get_config().mount_base
        mount_base.mkdir(parents=True, exist_ok=True)
        subprocess.run(["mount", device_node, mount_base.as_posix()], check=True)
    except Exception as e:
        raise RuntimeError(f"Failed to mount {device_node}: {e}")

    LOG.info(f"Mounted {device_node} to {mount_base.as_posix()}")

    return mount_base


def unmount_device(mountpoint: str):
    """
    Unmount the given mount point.

    :param mountpoint: The mount point path to unmount.
    :raises ValueError: If the mount point is not provided.
    :raises RuntimeError: If the unmount operation fails.
    """

    if mountpoint is None or mountpoint.strip() == "":
        raise ValueError("Must provide path to mountpoint")

    # attempt to unmount
    try:
        subprocess.run(["umount", mountpoint], check=True)
    except Exception as e:
        raise RuntimeError(f"Failed to unmount {mountpoint}: {e}")

    LOG.info(f"Unmounted {mountpoint}")


def remove_directory(path):
    """
    Forcefully removes a directory and all its contents.

    :param path: Path to the directory to be removed.
    """
    try:
        # Forcefully remove the directory and all contents
        shutil.rmtree(path)
        print(f"Successfully removed directory: {path}")
    except FileNotFoundError:
        print(f"Directory not found: {path}")
    except PermissionError:
        print(f"Permission denied while removing directory: {path}")
    except Exception as e:
        print(f"Error while removing directory: {path} - {e}")


def emit_ha_state_update():
    if home_assistant:
        home_assistant.update_state(app_state)


def handle_card_insert(device_node: str, card_id: str):
    """
    Handle the insertion of a new card.

    :param device_node: The device node path (e.g., /dev/sdX, /dev/mmcXpY).
    :param card_id: Name identifier for the card.
    """

    LOG.info(f"Card inserted: {card_id}")

    app_config.lock()

    app_state.status = AppStatus.BUSY
    app_state.card_id = card_id
    app_state.media_count = 0
    app_state.progress = 0
    emit_ha_state_update()

    try:
        mountpoint = mount_device(device_node)
    except RuntimeError:
        # mount failed
        app_state.status = AppStatus.ERROR
        with device_lock:
            processed_devices.remove(device_node)
        emit_ha_state_update()
        return

    try:
        total_progress = 0
        src_file_list = []

        # first pass to get file counts
        for grab in app_config.grabs:
            total_progress += 1                               # 1% for grab overhead
            total_progress += 1 if grab.rename_method.value > 0 else 0  # 1% for grab rename ops

            # count media files
            source_folder = mountpoint / grab.path
            for src_file in source_folder.iterdir():
                LOG.debug(f"FOUND: {src_file}")
                if src_file.name.lower().endswith(tuple(grab.types)):
                    src_file_list.append(src_file)
                    app_state.media_count += 1
                    total_progress += 1

        if app_state.media_count == 0:
            LOG.warning("No media files found to copy.")
        else:
            # create timestamped destination folder
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_path = app_config.destination_base / f"{card_id}-{timestamp}"
            dest_path.mkdir(parents=True, exist_ok=True)
            if app_config.chown:
                shutil.chown(dest_path.as_posix(), app_config.chown.user, app_config.chown.group)

            # second pass to perform copy operation
            progress = 0
            for grab in app_config.grabs:
                source_folder = mountpoint / grab.path
                target_folder = dest_path / grab.path.split(os.sep)[-1]
                target_folder.mkdir(parents=True, exist_ok=True)
                if app_config.chown:
                    shutil.chown(target_folder.as_posix(), app_config.chown.user, app_config.chown.group)

                # for src_file in source_folder.iterdir():
                #     if src_file.name.lower().endswith(tuple(grab.types)):
                for src_file in src_file_list:
                    dest_file = target_folder / src_file.name
                    LOG.info(f"Copying {src_file.as_posix()} -> {dest_file.as_posix()}")
                    shutil.copy2(src_file.as_posix(), dest_file.as_posix())
                    progress += 1
                    LOG.debug(f"PROGRESS -- {int(progress*100/total_progress)}%")
                    if progress % 10 == 0:
                        app_state.progress = progress
                        emit_ha_state_update()

                if app_config.delete_after_copy and not grab.never_delete:
                    LOG.info(f"Deleting files in {source_folder.as_posix()}")
                    remove_directory(source_folder.as_posix())
                    source_folder.mkdir(exist_ok=True)
                    if app_config.chown:
                        shutil.chown(source_folder.as_posix(), app_config.chown.user, app_config.chown.group)
                else:
                    LOG.info(f"Skipping deletion per config: {source_folder.as_posix()}")

                progress += 1
                LOG.debug(f"PROGRESS -- {int(progress*100/total_progress)}%")
                if progress % 10 == 0:
                    app_state.progress = progress
                    emit_ha_state_update()

            # renaming?
            for grab in app_config.grabs:
                target_folder = dest_path / grab.path.split(os.sep)[-1]
                LOG.debug(f"ORGANIZE -- {target_folder}")
                organize_files_in_place(target_folder.as_posix(), grab.rename_method, grab.rename_as_prefix, grab.mtime, grab.media_tag, app_config.chown)
                progress += 1
                LOG.debug(f"PROGRESS -- {int(progress*100/total_progress)}%")
                if progress % 10 == 0:
                    app_state.progress = progress
                    emit_ha_state_update()

        app_state.progress = 100
        app_state.status = AppStatus.READY
        with device_lock:
            processed_devices.remove(device_node)

    except Exception as e:
        LOG.error(f"Error handling card: {e}")
        app_state.status = AppStatus.ERROR
        with device_lock:
            processed_devices.remove(device_node)

    finally:
        emit_ha_state_update()

        if app_config.is_locked():
            app_config.unlock()

        # always attempt to unmount
        try:
            unmount_device(mountpoint.as_posix())
        except:  # ignore not mounted
            pass


def card_event(action: str, device: pyudev.Device):
    """
    Handle card events triggered by the udev monitor.

    :param action: The action type (e.g., "add", "remove").
    :param device: The device object from the udev event.
    """

    drv_match = re.search(r"[hs]d[a-z](\d+)", device.sys_name)
    mmc_match = re.search(r"mmcblk(\d+)p(\d+)", device.sys_name)
    if not drv_match and not mmc_match:
        LOG.warning(f"Unknown device pattern: {device.sys_name}")
        return

    # for k in device.items():
    #     LOG.debug(k)

    device_name = device.properties.get('ID_FS_LABEL', "")
    if not device_name:  # use 'name_serial' when no label
        if 'ID_NAME' in device.properties:
            device_name = device.properties['ID_NAME']
        elif 'ID_MODEL' in device.properties:
            device_name = device.properties['ID_MODEL']

        if 'ID_SERIAL_SHORT' in device.properties:
            if device_name:
                device_name = f"{device_name}_{device.properties['ID_SERIAL_SHORT']}"

    LOG.debug(f"Detected device ({action}): {device_name} ({device.device_node})")

    if action == "add":
        if device.device_node not in processed_devices:
            with device_lock:
                processed_devices.add(device.device_node)
            handle_card_insert(device.device_node, device_name)

    elif action == "remove":
        if device.device_node in processed_devices:
            with device_lock:
                processed_devices.remove(device.device_node)
            LOG.warning(f"Card UNSAFELY removed: {device_name}")
        else:
            LOG.info(f"Card removed: {device_name}")


def init_udev_card_monitor():
    LOG.debug("Initializing udev monitor")

    # insert filter for partition types
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem="block", device_type="partition")

    # setup async callback
    observer = pyudev.MonitorObserver(monitor, card_event)
    observer.start()

    LOG.info("Waiting for events...")
    return observer


if __name__ == "__main__":
    import time

    # load config & init state
    app_config_path = (
        os.getenv(GRABBY_CONFIG_ENV_VAR)                                         # from environ
        or (sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == '-c' else None)  # from cmdline
    )
    if app_config_path:
        app_config = AppConfigFile(Path(app_config_path))
    else:
        app_config = AppConfigFile(Path(f'{APP_NAME}.yaml'))

    app_state = AppState(AppStatus.READY, 0, 0, '')
    if app_config.home_assistant is not None:
        home_assistant = HomeAssistantAPI(app_config.home_assistant)
        home_assistant.update_state(app_state)

    logging.basicConfig(level=app_config.log_level)
    LOG.info(dedent(
    f"""v{APP_VERSION}
      ________            ___.  ___.          
     /  _____/___________ \_ |__\_ |__ ___.__.
    /   \  __\_  __ \__  \ | __ \| __ <   |  |
    \    \_\  \  | \// __ \| \_\ \ \_\ \___  |
     \______  /__|  (____  /___  /___  / ____|
            \/           \/    \/    \/\/     
    """))
    LOG.debug(app_config)

    # run card monitor
    card_monitor = init_udev_card_monitor()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        LOG.info("Stopping monitor...")
        card_monitor.stop()
        app_config._observer.stop()
    finally:
        card_monitor.join()
        app_config._observer.join()
        LOG.info("Done.")
