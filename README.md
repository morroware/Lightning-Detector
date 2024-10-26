# Raspberry Pi Lightning Detector

A complete system for detecting lightning strikes using a Raspberry Pi Zero and CJMCU-339 AS3935 lightning sensor. Get notifications via Slack and SMS when lightning is detected in your area!

## Table of Contents
- [Overview](#overview)
- [Hardware Requirements](#hardware-requirements)
- [Hardware Setup](#hardware-setup)
- [Software Setup](#software-setup)
- [Configuration](#configuration)
- [Running the System](#running-the-system)
- [Troubleshooting](#troubleshooting)
- [Maintenance](#maintenance)

## Overview

This project creates a lightning detection system that can:
- Detect lightning strikes up to 40km away
- Estimate the distance to lightning strikes
- Send notifications via Slack and SMS
- Filter out false positives and noise
- Run reliably 24/7

## Hardware Requirements

### Required Components
1. Raspberry Pi Zero W (or any Raspberry Pi model)
   - Cost: ~$10-15
   - Where to buy: [Official Resellers](https://www.raspberrypi.com/resellers/)

2. CJMCU-339 AS3935 Lightning Sensor
   - Cost: ~$10-20
   - Where to buy: Amazon, AliExpress, etc.

3. MicroSD Card (8GB or larger)
   - Cost: ~$5-10
   - Recommended: SanDisk or Samsung brand

4. Power Supply for Raspberry Pi
   - 5V 2.5A micro-USB power supply
   - Cost: ~$8-10

### Additional Components
5. Jumper Wires (Female-to-Female)
   - At least 6 wires needed
   - Cost: ~$3-5

6. Optional: Case for Raspberry Pi
   - Cost: ~$5-10

### Tools Needed
- Small Phillips head screwdriver
- Computer with SD card reader
- Internet connection

Total Budget: Approximately $45-70

## Hardware Setup

### Step 1: Prepare the Raspberry Pi

1. Insert the MicroSD card into your computer
2. Download the Raspberry Pi Imager:
   - Visit: https://www.raspberrypi.com/software/
   - Download and install for your operating system

3. Install Raspberry Pi OS:
   - Launch Raspberry Pi Imager
   - Choose OS: "Raspberry Pi OS (32-bit) Lite" (no desktop needed)
   - Choose Storage: Select your MicroSD card
   - Click "Write"

4. Enable SSH and WiFi (before ejecting SD card):
   - Create empty file named `ssh` in boot partition
   - Create `wpa_supplicant.conf` in boot partition:
   ```
   country=US
   ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
   network={
       ssid="YOUR_WIFI_NAME"
       psk="YOUR_WIFI_PASSWORD"
       key_mgmt=WPA-PSK
   }
   ```

### Step 2: Wire the AS3935 Sensor

Connect the CJMCU-339 to Raspberry Pi using jumper wires:

| AS3935 Pin | Raspberry Pi Pin | Description |
|------------|------------------|-------------|
| VDD        | Pin 1 (3.3V)    | Power       |
| GND        | Pin 6 (GND)     | Ground      |
| SCL        | Pin 5 (SCL)     | I2C Clock   |
| SDA        | Pin 3 (SDA)     | I2C Data    |
| IRQ        | Pin 7 (GPIO4)   | Interrupt   |
| EN_V       | Pin 1 (3.3V)    | Enable      |

![Wiring Diagram](wiring_diagram.png)

WARNING: Double-check all connections before powering on! Incorrect wiring can damage your devices.

### Step 3: Power Up

1. Insert the MicroSD card into Raspberry Pi
2. Connect the power supply
3. Wait 1-2 minutes for boot

## Software Setup

### Step 1: Connect to Raspberry Pi

1. Find your Pi's IP address:
   - Check your router's DHCP client list, or
   - Use a network scanner like "Advanced IP Scanner"

2. Connect via SSH:
   ```bash
   ssh pi@YOUR_PI_IP_ADDRESS
   # Default password: raspberry
   ```

3. Change default password:
   ```bash
   passwd
   ```

### Step 2: System Configuration

1. Update system:
   ```bash
   sudo apt update
   sudo apt upgrade -y
   ```

2. Enable I2C:
   ```bash
   sudo raspi-config
   # Navigate to: Interface Options > I2C > Enable
   ```

3. Install required packages:
   ```bash
   sudo apt install -y python3-pip python3-smbus i2c-tools git
   ```

4. Verify I2C connection:
   ```bash
   sudo i2cdetect -y 1
   # Should show device at address 0x03
   ```

### Step 3: Install Python Dependencies

```bash
pip3 install smbus2 RPi.GPIO slack_sdk twilio
```

### Step 4: Download Project Code

```bash
git clone https://github.com/morroware/Lightning-Detector.git
cd lightning-detector
```

## Configuration

### Step 1: Set Up External Services

1. Slack Setup:
   - Create new Slack workspace or use existing
   - Create new Slack App: https://api.slack.com/apps
   - Add Bot Token Scopes: `chat:write`
   - Install app to workspace
   - Copy Bot User OAuth Token

2. Twilio Setup:
   - Create Twilio account: https://www.twilio.com/try-twilio
   - Get Account SID and Auth Token
   - Get or buy a phone number

### Step 2: Configure the Application

1. Create configuration file:
   ```bash
   cp config.ini.example config.ini
   nano config.ini
   ```

2. Edit configuration:
   ```ini
   [Slack]
   bot_token = xoxb-your-slack-bot-token
   channel = #your-channel

   [Twilio]
   account_sid = your-twilio-account-sid
   auth_token = your-twilio-auth-token
   from_number = +1234567890
   to_number = +0987654321

   [Sensor]
   i2c_bus_number = 1
   as3935_i2c_addr = 0x03
   irq_pin = 4
   ```

## Running the System

### Start the Detector

1. Run manually:
   ```bash
   python3 lightning-detector.py
   ```

2. Run as service:
   ```bash
   sudo nano /etc/systemd/system/lightning-detector.service
   ```
   
   Add content:
   ```ini
   [Unit]
   Description=Lightning Detector Service
   After=network.target

   [Service]
   ExecStart=/usr/bin/python3 /home/pi/lightning-detector/lightning-detector.py
   WorkingDirectory=/home/pi/lightning-detector
   StandardOutput=inherit
   StandardError=inherit
   Restart=always
   User=pi

   [Install]
   WantedBy=multi-user.target
   ```

3. Enable and start service:
   ```bash
   sudo systemctl enable lightning-detector
   sudo systemctl start lightning-detector
   ```

### Monitor the System

1. Check service status:
   ```bash
   sudo systemctl status lightning-detector
   ```

2. View logs:
   ```bash
   tail -f lightning_detector.log
   ```

## Troubleshooting

### Common Issues

1. **Sensor Not Detected**
   - Check wiring connections
   - Verify I2C is enabled: `sudo raspi-config`
   - Check I2C address: `sudo i2cdetect -y 1`
   - Verify power supply is adequate

2. **No Notifications**
   - Check internet connection
   - Verify Slack/Twilio credentials
   - Check logs for errors
   - Ensure correct channel/phone numbers

3. **False Positives**
   - Place sensor away from electrical interference
   - Adjust noise floor level in code
   - Keep wires short and away from power sources

4. **System Crashes**
   - Check power supply stability
   - Monitor CPU temperature: `vcgencmd measure_temp`
   - Check available memory: `free -h`
   - Review logs for errors

### Debug Commands

```bash
# Check system logs
journalctl -u lightning-detector

# Test I2C connection
i2cget -y 1 0x03 0x00

# Monitor CPU usage
top

# Check network connectivity
ping 8.8.8.8
```

## Maintenance

### Regular Tasks

1. Weekly:
   - Check log files
   - Verify notifications working
   - Monitor system temperature

2. Monthly:
   - Update system packages
   ```bash
   sudo apt update
   sudo apt upgrade -y
   ```
   - Check for project updates
   ```bash
   cd lightning-detector
   git pull
   ```

3. As Needed:
   - Clean dust from hardware
   - Check wire connections
   - Rotate log files
   - Update configuration

### Backup System

1. Back up configuration:
   ```bash
   cp config.ini config.ini.backup
   ```

2. Back up SD card (from another computer):
   - Use Raspberry Pi Imager
   - Choose "Custom" > "Backup"
   - Select your Pi's SD card
   - Save the image file

## Performance Tuning

### Reducing False Positives

1. Adjust noise floor level in code
2. Place sensor in optimal location:
   - Away from electronics
   - Away from metal objects
   - Higher elevation preferred

3. Modify sensitivity settings:
   - Edit `AFE_GB_INDOOR` value
   - Adjust `INTERRUPT_COOLDOWN_SECONDS`

### Improving Reliability

1. Use high-quality power supply
2. Add UPS backup power
3. Monitor system resources
4. Implement watchdog timer

## Contributing

Found a bug or want to contribute? Please open an issue or submit a pull request!

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- AMS AS3935 Franklin Lightning Sensor
- Raspberry Pi Foundation
- Open-source community
