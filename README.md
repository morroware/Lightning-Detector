# Lightning Detection and Notification System using Raspberry Pi and AS3935 Sensor

![Lightning Detection](https://your-image-url-here) <!-- Optional: Add an image related to the project -->

## Overview

This project provides a Python-based lightning detection system designed to run on a Raspberry Pi connected to an **AS3935 lightning sensor module**. The system detects lightning strikes and sends notifications via **Slack** and **Twilio SMS** when lightning is detected within a configurable distance.

The script is structured for easy use, with detailed comments to assist users who are unfamiliar with Python or lightning detection systems.

## Features

- **Configurable Sensor Settings**: Customize sensor sensitivity, noise floor, and watchdog thresholds for optimal lightning detection.
- **Flexible Notification System**: Send real-time alerts through Slack and Twilio SMS with customizable messages.
- **Modular Codebase**: Organized into clear classes and functions for easy modification, expansion, and maintenance.
- **Comprehensive Error Handling**: Includes robust logging and error checking to ensure reliability and troubleshooting support.
- **Secure Credential Management**: Sensitive information such as API keys is stored securely using environment variables.

## Table of Contents

- [Hardware Requirements](#hardware-requirements)
- [Software Requirements](#software-requirements)
- [Hardware Setup](#hardware-setup)
  - [1. Raspberry Pi Preparation](#1-raspberry-pi-preparation)
  - [2. AS3935 Sensor Connection](#2-as3935-sensor-connection)
- [Software Setup](#software-setup)
  - [1. Update the Raspberry Pi](#1-update-the-raspberry-pi)
  - [2. Install System Packages](#2-install-system-packages)
  - [3. Enable I2C Interface](#3-enable-i2c-interface)
  - [4. Clone the Repository](#4-clone-the-repository)
  - [5. Install Python Dependencies](#5-install-python-dependencies)
  - [6. Set Environment Variables](#6-set-environment-variables)
  - [7. Create Configuration File](#7-create-configuration-file)
- [Running the Script](#running-the-script)
- [Configuration Details](#configuration-details)
- [Troubleshooting](#troubleshooting)
- [License](#license)
- [Author](#author)

## Hardware Requirements

- **Raspberry Pi** (any model with GPIO and I2C support)
- **AS3935 Lightning Sensor Module**
- **Breadboard and Jumper Wires** (for prototyping connections)
- **Power Supply** for the Raspberry Pi
- **Internet Connection** (for sending notifications)

## Software Requirements

- **Raspberry Pi OS** (formerly Raspbian), preferably the latest version
- **Python 3.x**
- **Python Libraries**: Listed in [Install Python Dependencies](#5-install-python-dependencies)

## Hardware Setup

### 1. Raspberry Pi Preparation

Ensure your Raspberry Pi is powered off before making any hardware connections to prevent damage.

### 2. AS3935 Sensor Connection

The AS3935 sensor communicates using the **I2C** protocol. Below is the wiring guide to connect the sensor to the Raspberry Pi using **BCM (Broadcom SOC channel) numbering**.

#### Pin Connections

| **AS3935 Sensor Pin** | **Raspberry Pi Pin (BCM)** | **Description** |
|-----------------------|----------------------------|-----------------|
| VCC                   | 3.3V (Pin 1)               | Power           |
| GND                   | GND (Pin 6)                | Ground          |
| SDA                   | SDA (GPIO 2, Pin 3)        | I2C Data        |
| SCL                   | SCL (GPIO 3, Pin 5)        | I2C Clock       |
| IRQ                   | GPIO 4 (Pin 7)             | Interrupt       |

#### Steps

1. **Connect Power**: Connect the **VCC** pin on the sensor to the **3.3V** pin on the Raspberry Pi.
2. **Connect Ground**: Connect the **GND** pin on the sensor to a **GND** pin on the Raspberry Pi.
3. **Connect I2C Data Line**: Connect the **SDA** pin on the sensor to the **SDA** (GPIO 2) pin on the Raspberry Pi.
4. **Connect I2C Clock Line**: Connect the **SCL** pin on the sensor to the **SCL** (GPIO 3) pin on the Raspberry Pi.
5. **Connect Interrupt Line**: Connect the **IRQ** pin on the sensor to **GPIO 4** on the Raspberry Pi.

**Note**: The GPIO pin numbers refer to the BCM numbering scheme used in the script. Ensure that the `gpio_mode` in the configuration is set to `BCM`.

## Software Setup

### 1. Update the Raspberry Pi

Before installing any software, update your package lists and upgrade existing packages:

    sudo apt update
    sudo apt upgrade -y

### 2. Install System Packages

Install essential system packages required for I2C communication and Python development:

    sudo apt install -y python3 python3-pip python3-dev i2c-tools

### 3. Enable I2C Interface

Enable the I2C interface to allow communication with the sensor:

    sudo raspi-config

- Navigate to **Interfacing Options**.
- Select **I2C** and enable it.

Alternatively, you can add `dtparam=i2c_arm=on` to `/boot/config.txt`.

Reboot the Raspberry Pi for the changes to take effect:

    sudo reboot

### 4. Clone the Repository

Clone the GitHub repository to your Raspberry Pi:

    git clone https://github.com/morroware/Lightning-Detector.git
    cd Lightning-Detector

### 5. Install Python Dependencies

Install the required Python libraries using `pip3`:

    pip3 install smbus2 RPi.GPIO pyyaml slack_sdk twilio logging

Alternatively, if a `requirements.txt` file is provided:

    pip3 install -r requirements.txt

### 6. Set Environment Variables

The script uses environment variables to securely handle sensitive credentials.

#### Slack API Token

Set your Slack API token:

    export SLACK_API_TOKEN='your-slack-api-token'

#### Twilio Credentials

Set your Twilio Account SID and Auth Token:

    export TWILIO_ACCOUNT_SID='your-twilio-account-sid'
    export TWILIO_AUTH_TOKEN='your-twilio-auth-token'

**Optional**: Add these lines to your `~/.bashrc` or `~/.profile` to set them automatically on login.

### 7. Create Configuration File

Create a `config.yaml` file in the project directory with the following content:

    # config.yaml

    sensor:
      noise_floor: 2
      watchdog_threshold: 2
      reset_register: 0x3C
      reset_command: 0x96
      noise_floor_register: 0x01
      watchdog_threshold_register: 0x01
      interrupt_register: 0x03
      distance_register: 0x07
      noise_level_bit: 0x01
      disturber_bit: 0x04
      lightning_bit: 0x08

    hardware:
      i2c_bus: 1
      sensor_address: 0x03
      interrupt_pin: 4
      gpio_mode: BCM

    timing:
      sensor_reset_delay: 0.1
      interrupt_handling_delay: 0.003
      main_loop_sleep_duration: 1
      gpio_bouncetime: 500

    notifications:
      slack:
        enabled: true
        channel_id: 'your-slack-channel-id'
        api_token_env_var: SLACK_API_TOKEN

      twilio:
        enabled: true
        from_number: '+1234567890'
        to_number: '+0987654321'
        account_sid_env_var: TWILIO_ACCOUNT_SID
        auth_token_env_var: TWILIO_AUTH_TOKEN

      threading:
        enabled: true
        timeout: null

      message_templates:
        lightning_detected: "⚡ Lightning detected approximately {distance} km away!"
        noise_too_high: "Warning: Noise level too high."
        disturber_detected: "Info: Disturber detected (false event)."

    user_settings:
      alert_threshold: 40

    logging:
      level: INFO
      format: '%(asctime)s - %(levelname)s - %(message)s'
      file: '/var/log/lightning_detection.log'

**Notes**:

- Replace `'your-slack-channel-id'` with your actual Slack channel ID.
- Replace the Twilio phone numbers with your Twilio number and the recipient's number.
- Adjust the `alert_threshold` to your desired maximum distance for notifications.
- Ensure the logging file path is writable by the user running the script.

## Running the Script

Make sure the script is executable:

    chmod +x Lightning-Detector.py

Run the script:

    python3 Lightning-Detector.py

**Tip**: To keep the script running after logging out, consider using `screen`, `tmux`, or setting up a systemd service.

## Configuration Details

The `config.yaml` file allows you to customize the behavior of the system.

### Sensor Settings

- **noise_floor**: Adjusts the sensor's sensitivity to environmental noise (0-7).
- **watchdog_threshold**: Sets the threshold for signal validation (0-10).

### Hardware Settings

- **i2c_bus**: The I2C bus number (usually `1` for newer Raspberry Pi models).
- **sensor_address**: The I2C address of the AS3935 sensor.
- **interrupt_pin**: The GPIO pin connected to the sensor's IRQ pin.
- **gpio_mode**: GPIO numbering mode (`BCM` or `BOARD`).

### Notification Settings

- **Slack**:
  - **enabled**: Set to `true` to enable Slack notifications.
  - **channel_id**: The ID of the Slack channel to send messages to.
  - **api_token_env_var**: Environment variable name storing the Slack API token.
- **Twilio**:
  - **enabled**: Set to `true` to enable Twilio SMS notifications.
  - **from_number**: Your Twilio phone number.
  - **to_number**: Recipient's phone number.
  - **account_sid_env_var**: Environment variable name for Twilio Account SID.
  - **auth_token_env_var**: Environment variable name for Twilio Auth Token.

### User Settings

- **alert_threshold**: Maximum distance (in km) for sending alerts.

### Logging

- **level**: Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).
- **format**: Format of log messages.
- **file**: File path to save logs.

## Troubleshooting

### Common Issues

- **I2C Device Not Found**: Run `i2cdetect -y 1` to check if the sensor is detected.
- **Permission Denied**: Ensure the script has execution permissions and access to necessary resources.
- **Environment Variables Not Set**: Verify that Slack and Twilio environment variables are correctly set.

### Logs

Check the log file specified in the configuration (e.g., `/var/log/lightning_detection.log`) for detailed error messages.

### Sensor Calibration

You may need to adjust the `noise_floor` and `watchdog_threshold` settings to suit your environment.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Author

- **Seth Morrow** - *Initial work* - [GitHub Profile](https://github.com/morroware)

---

*Feel free to contribute to this project by opening issues or submitting pull requests.*
