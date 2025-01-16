# Grabby

`grabby.py` is a Python script designed to handle automated file grabbing from removable storage devices. Its behavior is controlled using a YAML configuration file, allowing users to customize file grabbing rules, paths, and integration options.

---

## Configuration

The script is configured using a `config.yaml` file, which should be located in the same directory as the script. Below are the main sections and options:

### General Configuration

The YAML configuration file includes the following main keys:

- `log_level`: Defines the logging verbosity. e.g. `DEBUG`, `INFO`, `WARNING`, etc.
- `delete_after_copy`: A boolean value (`true` or `false`) indicating whether grabbed files should be deleted after copying.
- `destination_base`: The base directory where files will be copied after grabbing.
- `mount_base`: The main directory where removable devices are mounted.

### Grabs Block

The `grabs` block defines device-specific rules for file grabbing. Each device can include:

- Paths and target directories within the mounted device.
- File types to include/exclude.
- Renaming rules, such as:
  - `mediainfo`: Rename files based on their metadata.
  - `mtime`: Use the file modification time for renaming.

### Optional Home Assistant Integration

The script supports integration with Home Assistant by adding a block in the `config.yaml` file:

- `base_url`: The Home Assistant base URL (e.g., `https://YOUR_HA_URL:8123`).
- `api_token`: A valid long lived token for authenticating with Home Assistant.

---

## Docker Usage

### Building the Docker Image

Run the following command in the terminal to build the Docker image:

```sh
docker build -t grabby .
```

### Running the Container

To execute the script with volumes mounted for accessing media and configuration files, use:

```sh
docker run --rm -it \
  -e LOG_LEVEL=INFO \
  -e GRABBY_CONFIG_PATH=/config \
  -v <path-to-config-dir>/grabby:/config \
  --net=host \
  -v /run/udev/control:/run/udev/control \
  -v /dev:/dev
  grabby
```

### Using Docker Compose

```yaml
services:
  grabby:
    image: grabby
    container_name: grabby

    privileged: true
    network_mode: "host"

    environment:
      LOG_LEVEL: DEBUG

    volumes:
      - $GRABBY_CONFIG_DIR:/config
      - /run/udev/control:/run/udev/control
      - /dev:/dev
```
