import logging
import requests

from dataclasses import dataclass, asdict
from typing import Dict

from const import APP_NAME


LOG = logging.getLogger(__name__)
SENSOR_ENTITY_ID = f"sensor.{APP_NAME}"


@dataclass
class HomeAssistantConfig:
    base_url: str
    api_token: str


class HomeAssistantAPI:
    """
    A class to manage connections and interactions with the Home Assistant API.
    """

    def __init__(self, config: HomeAssistantConfig):
        """
        Initialize the HomeAssistantAPI instance with configuration details.

        :param config: Instance of HomeAssistantConfig containing base_url and api_token.
        """
        self.url = f"{config.base_url}/api"
        self.api_token = config.api_token
        LOG.info(f"HomeAssistantAPI initialized with URL: {self.url}")

    def _get_headers(self) -> Dict[str, str]:
        """
        Internal method to construct the request headers for Home Assistant API calls.

        :return: A dictionary with authorization and content-type headers.
        """
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    def create_or_update_sensor(self, state: str, attributes: Dict):
        """
        Create or update a sensor in Home Assistant with the specified state and attributes.

        :param state: The state to set for the sensor.
        :param attributes: A dictionary of attributes to include with the sensor.
        """
        sensor_entity_id = f"{SENSOR_ENTITY_ID}_{attributes['card_id']}"
        url = f"{self.url}/states/{sensor_entity_id}"
        headers = self._get_headers()
        payload = {
            "state": state,
            "attributes": {
                **attributes,      # preserve other attributes
                "icon": "mdi:sd",  # inject icon
            },
        }

        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            LOG.info(f"Successfully updated sensor {sensor_entity_id}: {response.status_code}")
        except requests.RequestException as e:
            LOG.error(f"Failed to update sensor: {e}")

    def update_state(self, app_state):
        """
        Update the Home Assistant sensor with the current application state.

        :param app_state: The current application state (AppState object).
        """
        attributes = asdict(app_state)
        self.create_or_update_sensor(state=app_state.status.name.capitalize(), attributes=attributes)
