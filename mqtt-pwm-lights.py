#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

__author__ = "Kyle Gordon"
__copyright__ = "Copyright (C) Kyle Gordon"

import os
import csv
import logging
import signal
import time
import socket

import mosquitto
import ConfigParser
import subprocess

# Read the config file
config = ConfigParser.RawConfigParser()
config.read("/etc/mqtt-pwm-lights/mqtt-pwm-lights.cfg")

#Use ConfigParser to pick out the settings
DEBUG = config.getboolean("global", "debug")
LOGFILE = config.get("global", "logfile")
MQTT_HOST = config.get("global", "mqtt_host")
MQTT_PORT = config.getint("global", "mqtt_port")
MQTT_TOPIC = config.get("global", "mqtt_topic")
PIN = config.getint("global", "pin")

client_id = "PWM_Lights_%d" % os.getpid()
mqttc = mosquitto.Mosquitto(client_id)

LOGFORMAT = '%(asctime)-15s %(message)s'

if DEBUG:
    logging.basicConfig(filename=LOGFILE, level=logging.DEBUG, format=LOGFORMAT)
else:
    logging.basicConfig(filename=LOGFILE, level=logging.INFO, format=LOGFORMAT)

logging.info("Starting mqtt-pwm-lights")
logging.info("INFO MODE")
logging.debug("DEBUG MODE")

def cleanup(signum, frame):
     """
     Signal handler to ensure we disconnect cleanly 
     in the event of a SIGTERM or SIGINT.
     """
     logging.info("Disconnecting from broker")
     mqttc.publish("/status/" + socket.getfqdn(), "Offline")
     mqttc.disconnect()
     logging.info("Exiting on signal %d", signum)
     sys.exit(signum)

def connect():
    """
    Connect to the broker, define the callbacks, and subscribe
    """
    result = mqttc.connect(MQTT_HOST, MQTT_PORT, 60, True)
    if result != 0:
        logging.info("Connection failed with error code %s. Retrying", result)
        time.sleep(10)
        connect()


    #define the callbacks
    mqttc.on_message = on_message
    mqttc.on_connect = on_connect
    mqttc.on_disconnect = on_disconnect

    # Subscribe to everything within the heirarchy
    mqttc.subscribe(MQTT_TOPIC + "/#", 2)

def on_connect(result_code):
     """
     Handle connections (or failures) to the broker.
     """
     ## FIXME - needs fleshing out http://mosquitto.org/documentation/python/
     if result_code == 0:
        logging.info("Connected to broker")
        mqttc.publish("/status/" + socket.getfqdn(), "Online")
     else:
        logging.warning("Something went wrong")
        cleanup()

def on_disconnect(result_code):
     """
     Handle disconnections from the broker
     """
     if result_code == 0:
        logging.info("Clean disconnection")
     else:
        logging.info("Unexpected disconnection! Reconnecting in 5 seconds")
        logging.debug("Result code: %s", result_code)
        time.sleep(5)
        connect()
        main_loop()

def on_message(msg):
    """
    What to do when the client recieves a message from the broker
    """
    logging.debug("Received: %s", msg.topic)
    if msg.topic == MQTT_TOPIC + "/state" and msg.payload == "?":
        logging.info("State requested")
        mqttc.publish(MQTT_TOPIC + "/state", str(get_pwm_value()))
    if msg.topic == MQTT_TOPIC + "/level":
        ## FIXME Check payload to ensure it's an integer
        target_pwm = int(msg.payload)
        pwm_value = get_pwm_value()
	while target_pwm != pwm_value:
          logging.debug("target_pwm is : %s, pwm_value is : %s", str(target_pwm), str(pwm_value))
          if target_pwm < pwm_value:
            pwm_value = pwm_value - 5
            if target_pwm > pwm_value - 5:
              pwm_value = target_pwm
              time.sleep(1)
              set_pwm_value(pwm_value)
            command = "/usr/local/bin/gpio -g pwm " + str(PIN) + " " + str(pwm_value)
            logging.debug("Executing : %s", command)
            subprocess.check_output(command, shell=True)
          if target_pwm > pwm_value:
            pwm_value = pwm_value + 5
	    if target_pwm < pwm_value + 5:
              pwm_value = target_pwm
              time.sleep(1)
              set_pwm_value(pwm_value)
            command = "/usr/local/bin/gpio -g pwm " + str(PIN) + " " + str(pwm_value)
            logging.debug("Executing : %s", command)
            subprocess.check_output(command, shell=True)
	logging.info("Finished - target_pwm is : %s, pwm_value is : %s", str(target_pwm), str(pwm_value))
	mqttc.publish(MQTT_TOPIC + "/state", str(pwm_value))

def get_pwm_value():
    """
    Read the PWM value from the system
    """
    logging.debug("Reading PWM value of pin %s", str(PIN))
    try:
      statefile = open('/tmp/pwmstatefile', 'r')
      pwm_value = int(statefile.readline())
      logging.debug("Stored PWM value is %s", str(pwm_value))
      statefile.close()
    except IOError as e:
      pwm_value = 0
      statefile = open('/tmp/pwmstatefile', 'w')
      statefile.write(str(pwm_value))
      statefile.close()
    except ValueError:
      print "Could not convert data to an integer."
      pwm_value = 0
    return pwm_value

def set_pwm_value(pwm_value):
    """
    Set the PWM value
    """
    logging.debug("Setting PWM value of pin %s", str(PIN))
    statefile = open('/tmp/pwmstatefile', 'w')
    statefile.write(str(pwm_value))
    statefile.close()
    command = "/usr/local/bin/gpio -g pwm " + str(PIN) + " " + str(pwm_value)
    logging.debug("Executing : %s", command)
    subprocess.check_output(command, shell=True)


def main_loop():
    """
    The main loop in which we stay connected to the broker
    """
    while mqttc.loop() == 0:
        logging.debug("Looping")


# Use the signal module to handle signals
signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)

#connect to broker
connect()

main_loop()
