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
import sys

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

APPNAME = "mqtt-pwm-lights"
PRESENCETOPIC = "clients/" + socket.getfqdn() + "/" + APPNAME + "/state"
client_id = APPNAME + "_%d" % os.getpid()
mqttc = mosquitto.Mosquitto(client_id)

LOGFORMAT = '%(asctime)-15s %(message)s'

if DEBUG:
    logging.basicConfig(filename=LOGFILE,
                        level=logging.DEBUG,
                        format=LOGFORMAT)
else:
    logging.basicConfig(filename=LOGFILE,
                        level=logging.INFO,
                        format=LOGFORMAT)

logging.info("Starting " + APPNAME)
logging.info("INFO MODE")
logging.debug("DEBUG MODE")

# All the MQTT callbacks start here


def on_publish(mosq, obj, mid):
    """
    What to do when a message is published
    """
    logging.debug("MID " + str(mid) + " published.")


def on_subscribe(mosq, obj, mid, qos_list):
    """
    What to do in the event of subscribing to a topic"
    """
    logging.debug("Subscribe with mid " + str(mid) + " received.")


def on_unsubscribe(mosq, obj, mid):
    """
    What to do in the event of unsubscribing from a topic
    """
    logging.debug("Unsubscribe with mid " + str(mid) + " received.")


def on_connect(mosq, obj, result_code):
    """
    Handle connections (or failures) to the broker.
    This is called after the client has received a CONNACK message
    from the broker in response to calling connect().
    The parameter rc is an integer giving the return code:

    0: Success
    1: Refused – unacceptable protocol version
    2: Refused – identifier rejected
    3: Refused – server unavailable
    4: Refused – bad user name or password (MQTT v3.1 broker only)
    5: Refused – not authorised (MQTT v3.1 broker only)
    """
    logging.debug("on_connect RC: " + str(result_code))
    if result_code == 0:
        logging.info("Connected to %s:%s", MQTT_HOST, MQTT_PORT)
        # Publish retained LWT as per
        # http://stackoverflow.com/q/97694
        # See also the will_set function in connect() below
        mqttc.publish(PRESENCETOPIC, "1", retain=True)
        process_connection()
    elif result_code == 1:
        logging.info("Connection refused - unacceptable protocol version")
        cleanup()
    elif result_code == 2:
        logging.info("Connection refused - identifier rejected")
        cleanup()
    elif result_code == 3:
        logging.info("Connection refused - server unavailable")
        logging.info("Retrying in 30 seconds")
        time.sleep(30)
    elif result_code == 4:
        logging.info("Connection refused - bad user name or password")
        cleanup()
    elif result_code == 5:
        logging.info("Connection refused - not authorised")
        cleanup()
    else:
        logging.warning("Something went wrong. RC:" + str(result_code))
        cleanup()


def on_disconnect(mosq, obj, result_code):
    """
    Handle disconnections from the broker
    """
    if result_code == 0:
        logging.info("Clean disconnection")
    else:
        logging.info("Unexpected disconnection! Reconnecting in 5 seconds")
        logging.debug("Result code: %s", result_code)
        time.sleep(5)


def on_message(mosq, obj, msg):
    """
    What to do when the client recieves a message from the broker
    """
    logging.debug("Received: " + msg.payload +
                  " received on topic " + msg.topic +
                  " with QoS " + str(msg.qos))
    process_message(msg)


def on_log(mosq, obj, level, string):
    """
    What to do with debug log output from the MQTT library
    """
    logging.debug(string)

# End of MQTT callbacks


def cleanup(signum, frame):
    """
    Signal handler to ensure we disconnect cleanly
    in the event of a SIGTERM or SIGINT.
    """
    logging.info("Disconnecting from broker")
    # Publish a retained message to state that this client is offline
    mqttc.publish(PRESENCETOPIC, "0", retain=True)
    mqttc.disconnect()
    logging.info("Exiting on signal %d", signum)
    sys.exit(signum)


def connect():
    """
    Connect to the broker, define the callbacks, and subscribe
    This will also set the Last Will and Testament (LWT)
    The LWT will be published in the event of an unclean or
    unexpected disconnection.
    """
    logging.debug("Connecting to %s:%s", MQTT_HOST, MQTT_PORT)
    # Set the Last Will and Testament (LWT) *before* connecting
    mqttc.will_set(PRESENCETOPIC, "0", qos=0, retain=True)
    result = mqttc.connect(MQTT_HOST, MQTT_PORT, 60, True)
    if result != 0:
        logging.info("Connection failed with error code %s. Retrying", result)
        time.sleep(10)
        connect()

    # Define the callbacks
    mqttc.on_connect = on_connect
    mqttc.on_disconnect = on_disconnect
    mqttc.on_publish = on_publish
    mqttc.on_subscribe = on_subscribe
    mqttc.on_unsubscribe = on_unsubscribe
    mqttc.on_message = on_message
    if DEBUG:
        mqttc.on_log = on_log


def process_connection():
    """
    What to do when a new connection is established
    """
    logging.debug("Subscribing to %s", MQTT_TOPIC)
    mqttc.subscribe(MQTT_TOPIC + "/#", 2)


def process_message(msg):
    """
    What to do when the client recieves a message from the broker
    """
    print "in procesS_message"
    logging.debug("Received: %s", msg.topic)
    if msg.topic == MQTT_TOPIC + "/state" and msg.payload == "?":
        logging.info("State requested")
        mqttc.publish(MQTT_TOPIC + "/state", str(get_pwm_value()))
    if msg.topic == MQTT_TOPIC + "/level":
        ## FIXME Check payload to ensure it's an integer
        target_pwm = int(msg.payload)
        pwm_value = get_pwm_value()
        while target_pwm != pwm_value:
            logging.debug("target_pwm is : %s, pwm_value is : %s",
                          str(target_pwm),
                          str(pwm_value))
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
		logging.info("Finished - target_pwm is : %s, pwm_value is : %s",
                	 str(target_pwm),
                	 str(pwm_value))
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


# Use the signal module to handle signals
signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)

#connect to broker
connect()

# Try to loop_forever until interrupted
try:
    mqttc.loop_forever()
except KeyboardInterrupt:
    logging.info("Interrupted by keypress")
    sys.exit(0)
