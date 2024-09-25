"""
Lightning Detection and Notification System using Raspberry Pi and AS3935 Sensor
Author: Seth Morrow
Date: 9/25/24

Description:
This script is designed to run on a Raspberry Pi connected to an AS3935 lightning sensor module.
It detects lightning strikes and sends notifications via Slack and Twilio SMS when lightning is detected
within a specified distance threshold.

The script is extensively commented to help users who are unfamiliar with Python or this type of system
understand how it works.

Features:
- Configurable sensor settings (noise floor, watchdog threshold)
- Configurable notification settings (Slack, Twilio SMS)
- Modular design with classes and functions for maintainability
- Error handling and logging for reliability
- Secure handling of sensitive credentials using environment variables
"""

# ==============================
# Import Necessary Libraries
# ==============================

import time  # Provides time-related functions, such as sleep for delays
import RPi.GPIO as GPIO  # Allows interaction with the Raspberry Pi's GPIO pins
from smbus2 import SMBus  # Enables communication over the I2C bus (for the sensor)
import yaml  # Used to read configuration settings from a YAML file
from slack_sdk import WebClient  # Slack SDK for sending messages to Slack channels
from twilio.rest import Client  # Twilio SDK for sending SMS messages
import logging  # Provides logging capabilities to track events and errors
import threading  # Allows for concurrent execution and handling program termination
import os  # Provides a way to access environment variables for secure credentials
import sys  # Used for system-specific parameters and functions

# ==============================
# Configuration Loading Module
# ==============================

def load_config(config_path='config.yaml'):
    """
    Load the configuration from a YAML file.

    :param config_path: Path to the YAML configuration file.
    :return: Parsed configuration as a Python dictionary.
    """
    try:
        with open(config_path, 'r') as config_file:
            config = yaml.safe_load(config_file)
            logging.debug("Configuration loaded successfully from '%s'.", config_path)
            return config
    except FileNotFoundError:
        logging.error("Configuration file '%s' not found.", config_path)
        sys.exit(1)
    except yaml.YAMLError as e:
        logging.error("Error parsing the configuration file: %s", e)
        sys.exit(1)

def validate_config(config):
    """
    Validate the configuration parameters to ensure all required settings are present.

    This function checks for the presence of critical configuration entries and exits the program
    if any are missing.

    :param config: Configuration dictionary to validate.
    """
    # Retrieve the list of required configurations from the config file or use defaults
    required_configs = config.get('required_configs', [
        # Sensor settings
        ('sensor', 'noise_floor'),
        ('sensor', 'watchdog_threshold'),
        ('sensor', 'reset_register'),
        ('sensor', 'reset_command'),
        ('sensor', 'noise_floor_register'),
        ('sensor', 'watchdog_threshold_register'),
        ('sensor', 'interrupt_register'),
        ('sensor', 'distance_register'),
        ('sensor', 'noise_level_bit'),
        ('sensor', 'disturber_bit'),
        ('sensor', 'lightning_bit'),

        # Hardware settings
        ('hardware', 'i2c_bus'),
        ('hardware', 'sensor_address'),
        ('hardware', 'interrupt_pin'),
        ('hardware', 'gpio_mode'),

        # Timing settings
        ('timing', 'sensor_reset_delay'),
        ('timing', 'interrupt_handling_delay'),
        ('timing', 'main_loop_sleep_duration'),
        ('timing', 'gpio_bouncetime'),

        # Notifications settings
        ('notifications', 'message_templates', 'lightning_detected'),
        ('notifications', 'message_templates', 'noise_too_high'),
        ('notifications', 'message_templates', 'disturber_detected'),
        ('notifications', 'threading', 'enabled'),
        ('notifications', 'threading', 'timeout'),

        # User settings
        ('user_settings', 'alert_threshold'),
    ])

    # Check for required configurations
    for keys in required_configs:
        conf = config
        for key in keys:
            if key not in conf:
                logging.error("Configuration parameter '%s' is missing.", '.'.join(keys))
                sys.exit(1)
            conf = conf[key]

    # Additional checks based on enabled notifications
    if config['notifications']['slack']['enabled']:
        slack_required = [
            ('notifications', 'slack', 'channel_id'),
            ('notifications', 'slack', 'api_token_env_var'),
        ]
        for keys in slack_required:
            conf = config
            for key in keys:
                if key not in conf:
                    logging.error("Configuration parameter '%s' is missing.", '.'.join(keys))
                    sys.exit(1)
                conf = conf[key]

    if config['notifications']['twilio']['enabled']:
        twilio_required = [
            ('notifications', 'twilio', 'from_number'),
            ('notifications', 'twilio', 'to_number'),
            ('notifications', 'twilio', 'account_sid_env_var'),
            ('notifications', 'twilio', 'auth_token_env_var'),
        ]
        for keys in twilio_required:
            conf = config
            for key in keys:
                if key not in conf:
                    logging.error("Configuration parameter '%s' is missing.", '.'.join(keys))
                    sys.exit(1)
                conf = conf[key]

# ==============================
# Logging Configuration
# ==============================

def configure_logging(config):
    """
    Configure the logging settings based on the configuration.

    :param config: Configuration dictionary containing logging settings.
    """
    logging_config = config.get('logging', {})
    logging_format = logging_config.get('format', '%(asctime)s - %(levelname)s - %(message)s')
    logging_level_name = logging_config.get('level', 'INFO').upper()
    logging_level = getattr(logging, logging_level_name, logging.INFO)
    log_file = logging_config.get('file')

    if log_file:
        logging.basicConfig(filename=log_file, format=logging_format, level=logging_level)
    else:
        logging.basicConfig(format=logging_format, level=logging_level)

    logging.debug("Logging configured with level '%s', format '%s', and file '%s'.",
                  logging_level_name, logging_format, log_file)

# ==============================
# Notification Initialization
# ==============================

def initialize_notifications(config):
    """
    Initialize notification clients based on the configuration.

    :param config: Configuration dictionary containing notification settings.
    :return: Tuple of (slack_client, twilio_client)
    """
    slack_client = None
    twilio_client = None

    # Slack notification setup
    if config['notifications']['slack']['enabled']:
        slack_env_var = config['notifications']['slack'].get('api_token_env_var', 'SLACK_API_TOKEN')
        slack_api_token = os.environ.get(slack_env_var)
        if not slack_api_token:
            logging.error("Slack API token not found in environment variable '%s'.", slack_env_var)
            sys.exit(1)
        try:
            slack_client = WebClient(token=slack_api_token)
            logging.debug("Slack client initialized successfully.")
        except Exception as e:
            logging.error("Failed to initialize Slack client: %s", e)
            slack_client = None

    # Twilio SMS notification setup
    if config['notifications']['twilio']['enabled']:
        twilio_sid_env_var = config['notifications']['twilio'].get('account_sid_env_var', 'TWILIO_ACCOUNT_SID')
        twilio_token_env_var = config['notifications']['twilio'].get('auth_token_env_var', 'TWILIO_AUTH_TOKEN')
        twilio_account_sid = os.environ.get(twilio_sid_env_var)
        twilio_auth_token = os.environ.get(twilio_token_env_var)
        if not twilio_account_sid or not twilio_auth_token:
            logging.error("Twilio credentials not found in environment variables '%s' and '%s'.",
                          twilio_sid_env_var, twilio_token_env_var)
            sys.exit(1)
        try:
            twilio_client = Client(twilio_account_sid, twilio_auth_token)
            logging.debug("Twilio client initialized successfully.")
        except Exception as e:
            logging.error("Failed to initialize Twilio client: %s", e)
            twilio_client = None

    return slack_client, twilio_client

# ==============================
# Sensor Interaction Class
# ==============================

class LightningSensor:
    """
    Class to interact with the AS3935 lightning sensor.

    This class provides methods to initialize the sensor, read interrupts, and get distance estimates.
    """

    def __init__(self, bus, address, config):
        """
        Initialize the LightningSensor object with the I2C bus, sensor address, and configuration.

        :param bus: An SMBus object representing the I2C bus.
        :param address: The I2C address of the sensor.
        :param config: Configuration dictionary.
        """
        self.bus = bus
        self.address = address
        self.config = config

    def setup(self, noise_floor, watchdog_threshold, reset_delay=0.1):
        """
        Set up the sensor with initial configuration.

        This method resets the sensor to default settings and configures specific parameters
        such as the noise floor level and watchdog threshold based on the configuration.

        :param noise_floor: Noise floor level (0-7).
        :param watchdog_threshold: Watchdog threshold (0-15).
        :param reset_delay: Delay after sensor reset in seconds.
        """
        try:
            # Retrieve sensor register addresses and commands from config
            reset_register = self.config['sensor'].get('reset_register', 0x3C)
            reset_command = self.config['sensor'].get('reset_command', 0x96)
            noise_floor_register = self.config['sensor'].get('noise_floor_register', 0x01)
            watchdog_threshold_register = self.config['sensor'].get('watchdog_threshold_register', 0x01)

            # Reset the sensor to default settings
            self.bus.write_byte_data(self.address, reset_register, reset_command)
            logging.debug("Sensor reset command sent to register 0x%02X with command 0x%02X.", reset_register, reset_command)
            # Wait for the specified reset delay
            time.sleep(reset_delay)

            # Configure the noise floor level
            noise_floor = noise_floor & 0x07  # Ensure it is a 3-bit value
            reg_value = self.bus.read_byte_data(self.address, noise_floor_register)
            reg_value = (reg_value & 0xF8) | noise_floor
            self.bus.write_byte_data(self.address, noise_floor_register, reg_value)
            logging.debug("Noise floor set to %d.", noise_floor)

            # Configure the watchdog threshold
            watchdog_threshold = watchdog_threshold & 0x0F  # Ensure it is a 4-bit value
            reg_value = self.bus.read_byte_data(self.address, watchdog_threshold_register)
            reg_value = (reg_value & 0x0F) | (watchdog_threshold << 4)
            self.bus.write_byte_data(self.address, watchdog_threshold_register, reg_value)
            logging.debug("Watchdog threshold set to %d.", watchdog_threshold)

            # Configure additional sensor settings if provided
            frequency_division_ratio = self.config['sensor'].get('frequency_division_ratio')
            if frequency_division_ratio is not None:
                # Set frequency division ratio (Example: Register 0x02)
                frequency_register = self.config['sensor'].get('frequency_division_register', 0x02)
                self.bus.write_byte_data(self.address, frequency_register, frequency_division_ratio)
                logging.debug("Frequency division ratio set to %d.", frequency_division_ratio)

            spike_rejection = self.config['sensor'].get('spike_rejection')
            if spike_rejection is not None:
                # Set spike rejection (Example: Register 0x02)
                spike_rejection_register = self.config['sensor'].get('spike_rejection_register', 0x02)
                self.bus.write_byte_data(self.address, spike_rejection_register, spike_rejection)
                logging.debug("Spike rejection set to %d.", spike_rejection)

            # Log an informational message indicating successful sensor initialization
            logging.info("Sensor initialized with noise_floor=%d, watchdog_threshold=%d",
                         noise_floor, watchdog_threshold)
        except Exception as e:
            logging.error("Failed to initialize sensor: %s", e)
            sys.exit(1)

    def read_interrupt(self):
        """
        Read the interrupt register from the sensor.

        The interrupt register indicates if certain events have occurred, such as lightning detection,
        noise level too high, or disturber detection.

        :return: The value of the interrupt register, or None if an error occurs.
        """
        try:
            # The interrupt register is located at address 0x03
            interrupt_register = self.config['sensor'].get('interrupt_register', 0x03)
            interrupt = self.bus.read_byte_data(self.address, interrupt_register)
            logging.debug("Interrupt register read: 0x%02X", interrupt)
            return interrupt
        except Exception as e:
            logging.error("Error reading interrupt register: %s", e)
            return None

    def get_distance(self):
        """
        Read the estimated distance to the lightning source.

        The distance estimate is provided by the sensor and indicates how far away the lightning occurred.

        :return: The estimated distance in kilometers, or None if an error occurs or if the distance is out of range.
        """
        try:
            # The distance estimate is stored in register 0x07
            distance_register = self.config['sensor'].get('distance_register', 0x07)
            distance = self.bus.read_byte_data(self.address, distance_register)
            if distance == 0:
                # A value of 0 indicates an out-of-range condition or that the distance is not available
                logging.debug("Distance read as 0 (out of range or unavailable).")
                return None
            else:
                # Return the distance value in kilometers
                logging.debug("Distance read: %d km.", distance)
                return distance
        except Exception as e:
            logging.error("Error reading distance register: %s", e)
            return None

# ==============================
# Notification Functions
# ==============================

def send_notifications(message, config, slack_client, twilio_client):
    """
    Send notifications using the enabled notification methods.

    This function checks which notification methods are enabled in the configuration
    and calls the appropriate functions to send the message.

    :param message: The message to be sent in the notifications.
    :param config: Configuration dictionary containing notification settings.
    :param slack_client: Initialized Slack WebClient or None.
    :param twilio_client: Initialized Twilio Client or None.
    """
    threading_config = config['notifications'].get('threading', {})
    threading_enabled = threading_config.get('enabled', True)
    timeout = threading_config.get('timeout', None)
    threads = []

    if threading_enabled:
        # Check if Slack notifications are enabled and if the Slack client is initialized
        if config['notifications']['slack']['enabled'] and slack_client:
            thread = threading.Thread(target=send_slack_notification, args=(message, config, slack_client))
            threads.append(thread)
            thread.start()

        # Check if Twilio SMS notifications are enabled and if the Twilio client is initialized
        if config['notifications']['twilio']['enabled'] and twilio_client:
            thread = threading.Thread(target=send_sms_notification, args=(message, config, twilio_client))
            threads.append(thread)
            thread.start()

        # Wait for all notification threads to complete with optional timeout
        for thread in threads:
            thread.join(timeout=timeout)
    else:
        # Send notifications without threading
        if config['notifications']['slack']['enabled'] and slack_client:
            send_slack_notification(message, config, slack_client)
        if config['notifications']['twilio']['enabled'] and twilio_client:
            send_sms_notification(message, config, twilio_client)

def send_slack_notification(message, config, slack_client):
    """
    Send a notification message to a Slack channel.

    :param message: The message to send.
    :param config: Configuration dictionary containing Slack settings.
    :param slack_client: Initialized Slack WebClient.
    """
    try:
        response = slack_client.chat_postMessage(
            channel=config['notifications']['slack']['channel_id'],
            text=message
        )
        logging.info("Slack notification sent: %s", message)
    except Exception as e:
        logging.error("Failed to send Slack notification: %s", e)

def send_sms_notification(message, config, twilio_client):
    """
    Send an SMS notification via Twilio.

    :param message: The message to send.
    :param config: Configuration dictionary containing Twilio settings.
    :param twilio_client: Initialized Twilio Client.
    """
    try:
        sms_message = twilio_client.messages.create(
            body=message,
            from_=config['notifications']['twilio']['from_number'],
            to=config['notifications']['twilio']['to_number']
        )
        logging.info("SMS notification sent: SID=%s", sms_message.sid)
    except Exception as e:
        logging.error("Failed to send SMS notification: %s", e)

# ==============================
# Main Execution Function
# ==============================

def main():
    """
    Main function to run the lightning detection system.

    This function initializes the sensor, sets up the GPIO interrupt handling,
    and enters a loop to keep the program running and responsive to sensor events.
    """
    # Load the configuration
    config = load_config()

    # Configure logging based on the loaded configuration
    configure_logging(config)

    # Validate the loaded configuration
    validate_config(config)

    # Initialize notification clients
    slack_client, twilio_client = initialize_notifications(config)

    # Extract hardware configuration from the configuration file
    hardware_config = config.get('hardware', {})
    I2C_BUS = hardware_config.get('i2c_bus')
    SENSOR_ADDR = hardware_config.get('sensor_address')
    INTERRUPT_PIN = hardware_config.get('interrupt_pin')
    gpio_mode = hardware_config.get('gpio_mode', 'BCM')

    # Initialize the I2C bus for communication with the sensor
    try:
        bus = SMBus(I2C_BUS)
        logging.debug("I2C bus %d initialized.", I2C_BUS)
    except Exception as e:
        logging.error("Failed to initialize I2C bus %d: %s", I2C_BUS, e)
        sys.exit(1)

    # Create an instance of the LightningSensor class
    sensor = LightningSensor(bus, SENSOR_ADDR, config)

    # Retrieve sensor configuration with defaults
    sensor_config = config.get('sensor', {})
    noise_floor = sensor_config.get('noise_floor')
    watchdog_threshold = sensor_config.get('watchdog_threshold')

    # Retrieve timing configurations
    timing_config = config.get('timing', {})
    sensor_reset_delay = timing_config.get('sensor_reset_delay', 0.1)
    interrupt_handling_delay = timing_config.get('interrupt_handling_delay', 0.003)
    main_loop_sleep_duration = timing_config.get('main_loop_sleep_duration', 1)
    gpio_bouncetime = timing_config.get('gpio_bouncetime', 500)  # In milliseconds

    # Call the setup method to initialize the sensor with the desired settings
    sensor.setup(noise_floor, watchdog_threshold, reset_delay=sensor_reset_delay)

    # Initialize the GPIO library to control the Raspberry Pi's GPIO pins
    if gpio_mode.upper() == 'BCM':
        GPIO.setmode(GPIO.BCM)  # Use BCM numbering (GPIO pin numbers)
    elif gpio_mode.upper() == 'BOARD':
        GPIO.setmode(GPIO.BOARD)  # Use BOARD numbering (physical pin numbers)
    else:
        logging.error("Invalid GPIO mode '%s' specified in configuration.", gpio_mode)
        sys.exit(1)
    logging.debug("GPIO mode set to %s.", gpio_mode.upper())

    # Set up the interrupt pin as an input with a pull-down resistor
    GPIO.setup(INTERRUPT_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    logging.debug("Interrupt pin %d set as input with pull-down resistor.", INTERRUPT_PIN)

    # Define a function to handle interrupts from the sensor
    def handle_interrupt(channel):
        """
        Callback function to handle sensor interrupts.

        This function is called when the sensor triggers an interrupt, indicating that an event has occurred.

        :param channel: The GPIO channel (pin number) that triggered the interrupt.
        """
        logging.debug("Interrupt detected on channel %d.", channel)
        # Wait for the specified interrupt handling delay
        time.sleep(interrupt_handling_delay)

        # Read the interrupt register from the sensor
        interrupt = sensor.read_interrupt()
        if interrupt is None:
            # If reading the interrupt register failed, we cannot proceed
            logging.warning("Interrupt register read failed.")
            return

        # Retrieve interrupt bit masks from configuration
        sensor_bits = config['sensor']
        noise_level_bit = sensor_bits.get('noise_level_bit', 0x01)
        disturber_bit = sensor_bits.get('disturber_bit', 0x04)
        lightning_bit = sensor_bits.get('lightning_bit', 0x08)

        # Retrieve message templates from configuration
        message_templates = config['notifications'].get('message_templates', {})
        lightning_message_template = message_templates.get(
            'lightning_detected',
            "⚡ Lightning detected approximately {distance} km away!"
        )
        noise_message_template = message_templates.get(
            'noise_too_high',
            "Warning: Noise level too high."
        )
        disturber_message_template = message_templates.get(
            'disturber_detected',
            "Info: Disturber detected (false event)."
        )

        # Interpret the interrupt register value to determine the type of event
        if interrupt & noise_level_bit:
            # Noise level too high
            logging.warning("Noise level too high - consider adjusting the noise floor setting.")
            message = noise_message_template
            send_notifications(message, config, slack_client, twilio_client)
        elif interrupt & disturber_bit:
            # Disturber detected
            logging.info("Disturber detected - false event.")
            message = disturber_message_template
            send_notifications(message, config, slack_client, twilio_client)
        elif interrupt & lightning_bit:
            # Lightning detected
            distance = sensor.get_distance()
            if distance is not None:
                logging.info("Lightning detected at approximately %d km away.", distance)
                # Check if the distance is within the user-defined alert threshold
                alert_threshold = config['user_settings'].get('alert_threshold')
                if distance <= alert_threshold:
                    # Prepare the notification message with the distance information
                    message = lightning_message_template.format(distance=distance)
                    # Send notifications using the enabled methods
                    send_notifications(message, config, slack_client, twilio_client)
            else:
                logging.info("Lightning detected, but distance is unknown.")
                message = "⚡ Lightning detected, but distance is unknown."
                send_notifications(message, config, slack_client, twilio_client)

    # Set up event detection on the interrupt pin
    # Monitor for rising edges (low to high transitions)
    # The 'bouncetime' parameter helps to prevent multiple triggers due to signal bouncing
    GPIO.add_event_detect(
        INTERRUPT_PIN,
        GPIO.RISING,
        callback=handle_interrupt,
        bouncetime=gpio_bouncetime
    )
    logging.debug("Event detection set up on interrupt pin %d with bouncetime %d ms.", INTERRUPT_PIN, gpio_bouncetime)

    # Use a threading event to handle program termination gracefully
    stop_event = threading.Event()

    # Retrieve main loop execution interval from configuration
    main_loop_config = config.get('main_loop', {})
    execution_interval = main_loop_config.get('execution_interval', main_loop_sleep_duration)

    # Use a try-except-finally block to manage the program's execution and cleanup
    try:
        # Log that the lightning detection system has started
        logging.info("Lightning detection system started.")
        # Enter the main loop to keep the program running
        while not stop_event.is_set():
            # You can perform other tasks here if needed
            # For now, we just sleep for the specified execution interval
            time.sleep(execution_interval)
    except KeyboardInterrupt:
        # If the user presses Ctrl+C, a KeyboardInterrupt exception is raised
        logging.info("Program terminated by user.")
        # Set the stop_event to exit the main loop
        stop_event.set()
    finally:
        # Perform cleanup actions to release resources
        GPIO.cleanup()  # Reset the GPIO pins to a safe state
        bus.close()     # Close the I2C bus
        logging.info("Resources cleaned up, exiting program.")

# ==============================
# Script Entry Point
# ==============================

if __name__ == "__main__":
    main()
