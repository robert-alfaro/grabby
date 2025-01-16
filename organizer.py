import logging
import shutil

from dataclasses import dataclass
from datetime import datetime
from dateutil.parser import parse as dateutil_parse
from dateutil.tz import tzlocal, gettz
from enum import IntEnum
from pathlib import Path
from pymediainfo import MediaInfo
from typing import List, Optional


@dataclass
class MediaInfoTag:
    group: str = "General"
    name: str = "Encoded date"
    tz: str = "UTC"
    substrs: List[str] = None


class RenameMethod(IntEnum):
    NONE = 0       # no renaming
    TREE = 1       # rename by move to dated tree
    OVERWRITE = 2  # rename in place


LOG = logging.getLogger(__name__)


def sanitize_datetime_string(datetime_str, substrs: Optional[List[str]]):
    """
    Sanitizes a datetime string by removing specified substrings.

    Args:
        datetime_str (str): The original datetime string.
        substrs (list): A list of substrings to remove from the datetime string.

    Returns:
        str: The sanitized datetime string.
    """
    for item in substrs or []:
        datetime_str = datetime_str.replace(item, "")
    return datetime_str.strip()


def get_local_date_from_media_info(file_path: str, media_tag: MediaInfoTag):
    """
    Extracts and converts a date tag from media file metadata into a local timezone.

    :param file_path: The path to the media file whose metadata is being processed.
    :param media_tag: The MediaInfo tag descriptor.
    :return: A tuple containing the year, month, and day of the converted date if parsing is successful,
             otherwise None.
    :raises ValueError: If no tag format is provided or an invalid timezone string is encountered.
    """
    try:
        tag_tz_info = gettz(media_tag.tz)
        local_tz_info = tzlocal()
    except Exception as e:
        raise ValueError(f"Invalid timezone string, err: {e}")

    media_info = MediaInfo.parse(file_path)

    # look for the tag
    for track in media_info.tracks:
        if track.track_type == media_tag.group:
            date_string = getattr(track, media_tag.name.replace(" ", "_").lower(), None)  # e.g. encoded_date
            if date_string:
                try:
                    # parse the date tag
                    date_string = sanitize_datetime_string(date_string, media_tag.substrs)
                    tag_date = dateutil_parse(date_string)

                    # if no timezone is found, use provided (default: UTC)
                    if tag_date.tzinfo is None:
                        tag_date = tag_date.replace(tzinfo=tag_tz_info)

                    # convert to local timezone
                    local_date = tag_date.astimezone(local_tz_info)
                    return local_date.year, local_date.month, local_date.day
                except ValueError as e:
                    LOG.error(f"Error parsing date '{date_string}': {e}")
                    return None

    LOG.warning(f"Tag '{media_tag.name}' not found in the media file.")
    return None


def organize_files_in_place(directory: str, rename_method: RenameMethod = RenameMethod.TREE, rename_as_prefix: bool = True, mtime: bool = True, media_tag: Optional[MediaInfoTag] = None, chown: Optional["ChownIds"] = None):
    """
    Organizes files in the given directory by creating subfolders (year/month/day)
    based on each file's datestamp and copying the files into the appropriate folders.

    :param directory: Path to the directory containing files to organize.
    :param mtime: Renames files with the modified datestamp when True.
    :param media_tag: Renames files using a media info date tag, when True.

    If both `mtime` and `media_tag` are set to True, the MediaInfoTag date takes precedence.
    The file's modified datestamp is only used if the MediaInfoTag date is unavailable.
    """
    # Convert the directory to a Path object and ensure it exists
    directory = Path(directory)
    if not directory.exists() or not directory.is_dir():
        raise FileNotFoundError(f"The directory '{directory}' does not exist or is not a directory.")

    # Iterate through all files in the directory
    file_idx = 0
    for file_path in directory.iterdir():
        # Skip directories, process only files
        if not file_path.is_file():
            continue

        file_idx += 1

        # Get the file's modified time (or creation time, if preferred)
        file_datestamp = datetime.fromtimestamp(file_path.stat().st_mtime)

        # Construct the year, month, and day folder structure
        year_folder = str(file_datestamp.year)
        month_folder = f"{file_datestamp.month:02d}"  # Zero-padded month
        day_folder = f"{file_datestamp.day:02d}"  # Zero-padded day

        # Build the full folder path in the same directory
        if rename_method == RenameMethod.TREE:
            destination_folder = directory / year_folder / month_folder / day_folder
            destination_folder.mkdir(parents=True, exist_ok=True)  # Create folders if they don't exist
            if chown:
                shutil.chown(destination_folder.as_posix(), chown.user, chown.group)
        elif rename_method == RenameMethod.OVERWRITE:
            destination_folder = directory
        else:
            raise ValueError(f"Invalid rename method: {rename_method}")

        p = file_path.name
        for suf in file_path.suffixes:
            p = p.replace(suf, '')
        single_ext_file_name = f"{p}{file_path.suffixes[-1]}"

        new_file_name = None

        # generate name from media info date tag?
        if media_tag:
            date_info = get_local_date_from_media_info(file_path, media_tag)
            if date_info:
                year, month, day = date_info
                date_str = f"{year}{month:02d}{day:02d}"
                if rename_as_prefix:
                    new_file_name = f"{date_str}_{single_ext_file_name}"
                else:
                    new_file_name = f"{date_str}-{file_idx:05d}{file_path.suffix}"
                LOG.debug(f"Using mediainfo based name:  {new_file_name}")

        # or, generate name from file modified datestamp?
        if mtime is True and new_file_name is None:
            formatted_date = f"{file_datestamp.year}{file_datestamp.month:02d}{file_datestamp.day:02d}"
            if rename_as_prefix:
                new_file_name = f"{formatted_date}_{single_ext_file_name}"
            else:
                new_file_name = f"{formatted_date}-{file_idx:05d}{file_path.suffix}"
            LOG.debug(f"Using mtime based name:  {new_file_name}")

        # otherwise, use original name
        if new_file_name is None:
            new_file_name = single_ext_file_name
            LOG.debug(f"Using original name: {new_file_name}")

        # Build the destination file path
        dest_file_path = destination_folder / new_file_name

        # Move the file into the appropriate day folder with the new name
        shutil.move(file_path.as_posix(), dest_file_path.as_posix())
        if chown:
            shutil.chown(dest_file_path.as_posix(), chown.user, chown.group)

        LOG.info(f"Moved: '{file_path}' -> '{dest_file_path}'")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # example usage
    # target_directory = "/mnt/seshat/download/card-grab/20250104_174554/CLIP"
    # target_directory = "/mnt/seshat/download/card-grab/20250104_174554/100MSDCF"
    target_directory = "/mnt/seshat/download/grabby/6BCHO_0xa45a0240-20250108_124018/CLIP"

    sony_media_tag = MediaInfoTag(
        group="General",
        name="Encoded date",
        tz="UTC",
        substrs=["UTC "]
    )

    organize_files_in_place(
        target_directory,
        mtime=True,
        media_tag=sony_media_tag
    )
