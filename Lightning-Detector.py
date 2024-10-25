#!/usr/bin/env python3
"""
Lightning Detector Script for Raspberry Pi Zero using CJMCU-339 AS3935 Sensor.
Sends alerts via Slack and SMS using Twilio when lightning is detected.
"""

# Import standard Python modules
import os
import time
import signal
import logging
import logging.handlers
import threading
import queue
import traceback
from datetime import datetime, timedelta
import configparser  # Module to read configurations from a file

# Import third-party modules
import smbus2  # For I2C communication
import RPi.GPIO as GPIO  # For GPIO pin control on Raspberry Pi
from slack_sdk import WebClient  # Slack client to send messages
from slack_sdk.errors import SlackApiError  # For handling Slack API errors
from twilio.rest import Client as TwilioClient  # Twilio client to send SMS
from twilio.base.exceptions import TwilioRestException  # For handling Twilio errors

# ----------------------------
# Constants and Configuration
# ----------------------------

# Constants for AS3935 Register Addresses (as per datasheet)
REG_AFE_GAIN = 0x00            # Register for AFE gain settings
REG_INT_MASK_ANT = 0x03        # Register for interrupt mask and antenna tuning
REG_LIGHTNING_DISTANCE = 0x07  # Register that holds the estimated lightning distance
REG_INT = 0x03                 # Register that holds the interrupt source
REG_NOISE_FLOOR = 0x01         # Register for noise floor level settings

# Bit Masks for interpreting register values
MASK_DISTURBER = 0x20          # Mask for disturber events
MASK_LIGHTNING = 0x08          # Mask for lightning detection events
MASK_DISTURBER_EVENT = 0x04    # Mask for disturber detection events
MASK_NOISE_HIGH = 0x01         # Mask for high noise level events

# Constants for AFE (Analog Front End) Gain settings
AFE_GB_INDOOR = 0x12           # Gain value for indoor settings
AFE_GB_OUTDOOR = 0x0E          # Gain value for outdoor settings

# Debounce Configuration to prevent multiple rapid interrupts
INTERRUPT_COOLDOWN_SECONDS = 1  # Time in seconds to wait before processing another interrupt

# ----------------------------
# Logging Configuration
# ----------------------------

# Configure logging with rotation to handle log file sizes
LOG_FILENAME = 'lightning_detector.log'
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # Set the logging level to INFO

# Create a rotating file handler to manage log files
handler = logging.handlers.RotatingFileHandler(
    LOG_FILENAME, maxBytes=5*1024*1024, backupCount=5)  # Rotate logs at 5 MB, keep 5 backups

# Define the format for log messages
formatter = logging.Formatter(
    '[%(asctime)s] %(levelname)s:%(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')

# Apply the formatter to the handler and add the handler to the logger
handler.setFormatter(formatter)
logger.addHandler(handler)

# ----------------------------
# Configuration File Loading
# ----------------------------

# Create a ConfigParser object to read the configuration file
config = configparser.ConfigParser()

# Read the configuration file 'config.ini' located in the same directory
config.read('config.ini')

def get_config_value(section, option, default=None, required=False):
    """
    Retrieves a configuration value from the config.ini file.

    Args:
        section (str): The section in the config file (e.g., 'Slack').
        option (str): The option key within the section (e.g., 'bot_token').
        default: The default value to return if the option is not found.
        required (bool): If True, raises an error if the option is not found.

    Returns:
        The value of the configuration option.

    Raises:
        ValueError: If the required option is not found in the config file.
    """
    if config.has_option(section, option):
        return config.get(section, option)
    elif default is not None:
        return default
    elif required:
        logger.error(f"Configuration option '{option}' in section '{section}' is required but not set.")
        raise ValueError(f"Configuration option '{option}' in section '{section}' is required but not set.")
    else:
        return None

def parse_i2c_address(addr_str):
    """
    Parses the I2C address string and converts it to an integer.

    Args:
        addr_str (str): The I2C address as a string (e.g., '0x03').

    Returns:
        int: The I2C address as an integer.

    Raises:
        ValueError: If the address string is invalid.
    """
    try:
        return int(addr_str, 0)  # The '0' base allows for automatic base detection (hex, dec, octal)
    except ValueError:
        raise ValueError(f"Invalid I2C address format: {addr_str}")

# ----------------------------
# Load and Validate Configurations
# ----------------------------

try:
    # Load Slack configurations
    SLACK_BOT_TOKEN = get_config_value('Slack', 'bot_token', required=True)
    SLACK_CHANNEL = get_config_value('Slack', 'channel', required=True)

    # Load Twilio configurations
    TWILIO_ACCOUNT_SID = get_config_value('Twilio', 'account_sid', required=True)
    TWILIO_AUTH_TOKEN = get_config_value('Twilio', 'auth_token', required=True)
    TWILIO_FROM_NUMBER = get_config_value('Twilio', 'from_number', required=True)
    TWILIO_TO_NUMBER = get_config_value('Twilio', 'to_number', required=True)

    # Load Sensor configurations
    I2C_BUS_NUMBER = int(get_config_value('Sensor', 'i2c_bus_number', '1'))
    AS3935_I2C_ADDR = parse_i2c_address(get_config_value('Sensor', 'as3935_i2c_addr', '0x03'))
    IRQ_PIN = int(get_config_value('Sensor', 'irq_pin', '4'))

    # Validate I2C address range (valid addresses for I2C devices)
    if not (0x03 <= AS3935_I2C_ADDR <= 0x77):
        raise ValueError(f"I2C address {AS3935_I2C_ADDR:#04x} is out of valid range (0x03 to 0x77).")

    # Validate GPIO pin number range (valid GPIO pins on Raspberry Pi)
    if not (2 <= IRQ_PIN <= 27):
        raise ValueError(f"GPIO pin {IRQ_PIN} is out of valid range (2 to 27).")

except ValueError as e:
    # Log the error and exit if configuration is invalid
    logger.error(e)
    exit(1)

# ----------------------------
# Initialize Clients
# ----------------------------

# Initialize the Slack client with the provided bot token
slack_client = WebClient(token=SLACK_BOT_TOKEN)

# Initialize the Twilio client with the provided credentials
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ----------------------------
# LightningDetector Class Definition
# ----------------------------

class LightningDetector:
    """
    Class to handle the lightning detection logic.
    This class encapsulates all functionality related to the AS3935 sensor,
    event processing, alert sending, and graceful shutdown.
    """

    def __init__(self):
        """
        Initializes the LightningDetector instance by setting up the I2C bus,
        GPIO pins, and various synchronization primitives.
        """
        # Initialize a lock for synchronized access to the I2C bus
        self.i2c_lock = threading.Lock()

        # Initialize a lock for synchronized access to interrupt handling
        self.interrupt_lock = threading.Lock()

        # Initialize the I2C bus using the bus number from the configuration
        try:
            self.bus = smbus2.SMBus(I2C_BUS_NUMBER)
            logger.info("I2C bus initialized.")
        except FileNotFoundError:
            logger.error("I2C bus not found. Is I2C enabled?")
            raise
        except Exception as e:
            logger.error(f"Unexpected error initializing I2C bus: {e}")
            raise

        # Set up GPIO pins using Broadcom (BCM) numbering
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(IRQ_PIN, GPIO.IN)  # Set the IRQ pin as input

        # Calibration parameters for the noise floor level
        self.noise_floor_level = 2  # Initial noise floor level (0-7)
        self.noise_floor_lock = threading.Lock()  # Lock for thread-safe noise floor adjustments

        # Queue to hold interrupt events for processing
        self.event_queue = queue.Queue()

        # Event to signal the processor thread to exit
        self.stop_event = threading.Event()

        # Thread to process events from the event queue
        self.processor_thread = threading.Thread(target=self.process_events, daemon=False)

        # Flag to control the main loop in the run method
        self.running = True

        # Set up signal handling for graceful shutdown on SIGINT or SIGTERM
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)

        # Variables for interrupt debounce
        self.last_interrupt_time = datetime.min  # Initialize to the earliest possible datetime
        self.interrupt_cooldown = timedelta(seconds=INTERRUPT_COOLDOWN_SECONDS)  # Cooldown duration

    def __enter__(self):
        """
        Allows the LightningDetector to be used with the 'with' statement.

        Returns:
            self: The LightningDetector instance.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Ensures resources are cleaned up when exiting the 'with' block.

        Args:
            exc_type: Exception type if an exception was raised.
            exc_val: Exception value.
            exc_tb: Traceback.
        """
        self.shutdown(None, None)

    # ----------------------------
    # Sensor Communication Methods
    # ----------------------------

    def read_register(self, reg_addr):
        """
        Reads a byte from a specified register of the AS3935 sensor.

        Args:
            reg_addr (int): The register address to read from.

        Returns:
            int: The value read from the register, or None if an error occurs.
        """
        with self.i2c_lock:
            try:
                return self.bus.read_byte_data(AS3935_I2C_ADDR, reg_addr)
            except Exception as e:
                logger.error(f"I2C read error at register {reg_addr:#04x}: {e}\n{traceback.format_exc()}")
                return None

    def write_register(self, reg_addr, data):
        """
        Writes a byte to a specified register of the AS3935 sensor.

        Args:
            reg_addr (int): The register address to write to.
            data (int): The data byte to write.
        """
        with self.i2c_lock:
            try:
                self.bus.write_byte_data(AS3935_I2C_ADDR, reg_addr, data)
                logger.debug(f"Wrote {data:#04x} to register {reg_addr:#04x}")
            except Exception as e:
                logger.error(f"I2C write error at register {reg_addr:#04x}: {e}\n{traceback.format_exc()}")

    # ----------------------------
    # Sensor Configuration Methods
    # ----------------------------

    def configure_sensor(self):
        """
        Configures the AS3935 sensor with initial settings.
        Retries configuration if temporary errors occur.

        This method sets the AFE gain, masks disturbers, and sets the initial noise floor level.
        """
        logger.info("Configuring the AS3935 sensor.")
        retries = 3  # Number of retries for configuration
        delay = 1    # Initial delay between retries in seconds
        for attempt in range(retries):
            try:
                # Set the AFE gain to indoor mode (can be set to outdoor if needed)
                self.set_afe_gain(indoor=True)

                # Mask disturber events to reduce false positives
                self.mask_disturbers(mask=True)

                # Set the initial noise floor level
                self.set_noise_floor_level(self.noise_floor_level)

                logger.info("Sensor configuration complete.")
                return
            except Exception as e:
                logger.error(f"Sensor configuration failed: {e}\n{traceback.format_exc()}")
                if attempt < retries - 1:
                    logger.info(f"Retrying sensor configuration in {delay} seconds...")
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff for subsequent retries
                else:
                    logger.error("Max retries reached for sensor configuration.")
                    # Send alerts if configuration fails after retries
                    self.send_alerts("⚠️ Lightning Detector failed to configure the sensor.")
                    self.shutdown(None, None)

    def set_afe_gain(self, indoor=True):
        """
        Sets the AFE gain for indoor or outdoor use.

        Args:
            indoor (bool): If True, sets gain for indoor use; otherwise, for outdoor use.
        """
        reg_value = self.read_register(REG_AFE_GAIN)
        if reg_value is not None:
            if indoor:
                # Set bits 5 and 6 to '01' for indoor mode
                reg_value = (reg_value & 0x9F) | 0x20
            else:
                # Set bits 5 and 6 to '10' for outdoor mode
                reg_value = (reg_value & 0x9F) | 0x40
            self.write_register(REG_AFE_GAIN, reg_value)
            logger.debug(f"Set AFE gain to {'indoor' if indoor else 'outdoor'} mode.")
        else:
            raise Exception("Failed to read AFE_GAIN register.")

    def mask_disturbers(self, mask=True):
        """
        Masks or unmasks disturber events to reduce false positives.

        Args:
            mask (bool): If True, masks disturber events; otherwise, unmasks them.
        """
        reg_value = self.read_register(REG_INT_MASK_ANT)
        if reg_value is not None:
            if mask:
                reg_value |= MASK_DISTURBER  # Set the mask disturber bit
                logger.debug("Masking disturbers.")
            else:
                reg_value &= ~MASK_DISTURBER  # Clear the mask disturber bit
                logger.debug("Unmasking disturbers.")
            self.write_register(REG_INT_MASK_ANT, reg_value)
        else:
            raise Exception("Failed to read INT_MASK_ANT register.")

    def set_noise_floor_level(self, level):
        """
        Sets the noise floor level to filter out background noise.

        Args:
            level (int): The noise floor level (0-7).

        Raises:
            Exception: If the noise floor register cannot be read.
        """
        if 0 <= level <= 7:
            reg_value = self.read_register(REG_NOISE_FLOOR)
            if reg_value is not None:
                # Clear the lower 3 bits and set the new noise floor level
                reg_value = (reg_value & 0xF8) | level
                self.write_register(REG_NOISE_FLOOR, reg_value)
                logger.debug(f"Noise floor level set to {level}.")
            else:
                raise Exception("Failed to read NOISE_FLOOR register.")
        else:
            logger.warning("Invalid noise floor level. Must be between 0 and 7.")

    # ----------------------------
    # Interrupt Handling Methods
    # ----------------------------

    def handle_interrupt(self, channel):
        """
        Interrupt handler for the AS3935 sensor.
        Implements debounce to prevent multiple rapid interrupts.

        Args:
            channel (int): The GPIO channel that triggered the interrupt.
        """
        with self.interrupt_lock:
            now = datetime.now()
            if now - self.last_interrupt_time > self.interrupt_cooldown:
                # If enough time has passed since the last interrupt, queue the event
                self.event_queue.put('interrupt')
                self.last_interrupt_time = now
                logger.debug("Interrupt queued for processing.")
            else:
                logger.debug("Interrupt received but ignored due to cooldown.")

    # ----------------------------
    # Event Processing Methods
    # ----------------------------

    def process_events(self):
        """
        Processes events from the event queue.
        This method runs in a separate thread and handles interrupts and other events.
        """
        while not self.stop_event.is_set():
            try:
                # Wait for an event with a longer timeout to reduce CPU usage
                event = self.event_queue.get(timeout=1.0)
                if event == 'interrupt':
                    self.process_interrupt()
            except queue.Empty:
                # If the queue is empty, continue the loop
                continue
            except Exception as e:
                logger.error(f"Unexpected error in event processing: {e}\n{traceback.format_exc()}")

    def process_interrupt(self):
        """
        Processes the interrupt by reading the interrupt source from the sensor.
        Determines the type of event (lightning, disturber, noise) and takes appropriate action.
        """
        int_source = self.read_register(REG_INT)
        if int_source is None:
            logger.error("Failed to read interrupt source.")
            return

        # Check which type of event has occurred based on interrupt source bits
        if int_source & MASK_LIGHTNING:
            # Lightning detected
            distance = self.read_register(REG_LIGHTNING_DISTANCE)
            if distance is not None:
                distance_km = distance & 0x3F  # Lower 6 bits represent distance in km
                message = f"⚡ Lightning detected! Estimated distance: {distance_km} km."
                logger.info("Lightning event detected.")
                # Send alerts via Slack and SMS
                self.send_alerts(message)
            else:
                logger.error("Failed to read lightning distance.")
        elif int_source & MASK_DISTURBER_EVENT:
            # Disturber (false event) detected
            logger.info("Disturber detected. Adjusting settings.")
            # Optionally adjust settings to reduce sensitivity
            self.adjust_noise_floor(increase=True)
        elif int_source & MASK_NOISE_HIGH:
            # Noise level too high
            logger.warning("Noise level too high. Adjusting noise floor level.")
            self.adjust_noise_floor(increase=True)
        else:
            # Unexpected interrupt source
            logger.warning(f"Unexpected interrupt source: {int_source:#04x}")

    def adjust_noise_floor(self, increase=True):
        """
        Adjusts the noise floor level up or down based on sensor feedback.
        This helps filter out background noise or false events.

        Args:
            increase (bool): If True, increases the noise floor level; otherwise, decreases it.
        """
        with self.noise_floor_lock:
            if increase and self.noise_floor_level < 7:
                self.noise_floor_level += 1
                self.set_noise_floor_level(self.noise_floor_level)
                logger.info(f"Increased noise floor level to {self.noise_floor_level}.")
            elif not increase and self.noise_floor_level > 0:
                self.noise_floor_level -= 1
                self.set_noise_floor_level(self.noise_floor_level)
                logger.info(f"Decreased noise floor level to {self.noise_floor_level}.")
            else:
                logger.warning("Noise floor level is at its limit.")

    # ----------------------------
    # Alert Sending Methods
    # ----------------------------

    def send_alerts(self, message):
        """
        Sends alerts via Slack and Twilio SMS.
        Implements retries with exponential backoff in case of temporary failures.

        Args:
            message (str): The message to send in the alerts.
        """
        max_retries = 3  # Maximum number of retries for sending alerts
        delay = 1        # Initial delay between retries in seconds

        # Send Slack message
        for attempt in range(max_retries):
            try:
                response = slack_client.chat_postMessage(channel=SLACK_CHANNEL, text=message)
                logger.info(f"Slack alert sent: {response['ts']}")
                break  # Break out of the loop if successful
            except SlackApiError as e:
                logger.error(f"Slack API error: {e.response['error']}\n{traceback.format_exc()}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying Slack message in {delay} seconds...")
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    logger.error("Max retries reached for Slack message.")

        # Reset delay for Twilio retries
        delay = 1

        # Send SMS via Twilio
        for attempt in range(max_retries):
            try:
                message_obj = twilio_client.messages.create(
                    body=message,
                    from_=TWILIO_FROM_NUMBER,
                    to=TWILIO_TO_NUMBER
                )
                logger.info(f"SMS alert sent: SID {message_obj.sid}")
                break  # Break out of the loop if successful
            except TwilioRestException as e:
                logger.error(f"Twilio error: {e.msg}\n{traceback.format_exc()}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying SMS message in {delay} seconds...")
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    logger.error("Max retries reached for SMS message.")

    # ----------------------------
    # Periodic Sensor Check Method
    # ----------------------------

    def periodic_sensor_check(self):
        """
        Periodically checks the sensor status to ensure it's functioning correctly.
        This method can detect if the sensor has become unresponsive and take corrective action.
        """
        logger.debug("Performing periodic sensor check.")
        try:
            with self.i2c_lock:
                # Example: Read a register that should have a constant value
                reg_value = self.read_register(REG_INT_MASK_ANT)
            if reg_value is None:
                logger.error("Sensor check failed: Unable to read INT_MASK_ANT register.")
                # Handle sensor error, possibly reinitialize the sensor
            else:
                logger.debug("Sensor check passed.")
        except Exception as e:
            logger.error(f"Error during sensor check: {e}\n{traceback.format_exc()}")

    # ----------------------------
    # Shutdown and Cleanup Methods
    # ----------------------------

    def shutdown(self, signum, frame):
        """
        Handles shutdown signals to clean up resources.
        This method is called when a SIGINT or SIGTERM signal is received.

        Args:
            signum (int): The signal number.
            frame: The current stack frame (unused).
        """
        logger.info("Shutdown signal received. Cleaning up.")
        self.running = False         # Stop the main loop in the run method
        self.stop_event.set()        # Signal the processor thread to exit
        try:
            if GPIO.event_detected(IRQ_PIN):
                GPIO.remove_event_detect(IRQ_PIN)  # Remove the interrupt detection
            GPIO.cleanup()                     # Clean up GPIO resources
            logger.debug("GPIO cleanup completed.")
        except Exception as e:
            logger.error(f"Error during GPIO cleanup: {e}\n{traceback.format_exc()}")

        if hasattr(self, 'bus'):
            try:
                self.bus.close()  # Close the I2C bus
                logger.debug("I2C bus closed.")
            except Exception as e:
                logger.error(f"Error closing I2C bus: {e}\n{traceback.format_exc()}")

        if self.processor_thread.is_alive():
            self.processor_thread.join()  # Wait for the processor thread to finish
            logger.debug("Processor thread joined.")

        logger.info("Cleanup complete. Exiting.")
        # Exit the program
        exit(0)

    # ----------------------------
    # Main Execution Method
    # ----------------------------

    def run(self):
        """
        Main loop to keep the script running.
        This method configures the sensor, starts the processor thread, and enters a loop
        that periodically checks the sensor status.
        """
        self.configure_sensor()
        logger.info("Waiting for lightning strikes...")

        # Start the processor thread to handle events
        self.processor_thread.start()

        try:
            while self.running:
                # Periodically check the sensor every 5 seconds
                self.periodic_sensor_check()
                time.sleep(5)
        except KeyboardInterrupt:
            # Handle Ctrl+C interrupt
            self.shutdown(None, None)
        finally:
            if self.processor_thread.is_alive():
                self.processor_thread.join()  # Ensure the processor thread is cleaned up

# ----------------------------
# Script Entry Point
# ----------------------------

if __name__ == '__main__':
    try:
        # Use context manager to ensure resources are cleaned up
        with LightningDetector() as detector:
            # Register the interrupt handler after initializing the detector
            try:
                GPIO.add_event_detect(IRQ_PIN, GPIO.RISING, callback=detector.handle_interrupt)
                logger.debug("GPIO event detection registered.")
            except Exception as e:
                logger.error(f"Failed to register GPIO event detect: {e}\n{traceback.format_exc()}")
                detector.shutdown(None, None)

            # Run the main loop
            detector.run()

    except Exception as e:
        logger.error(f"Failed to initialize LightningDetector: {e}\n{traceback.format_exc()}")
        exit(1)
