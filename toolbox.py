import subprocess
import os
from scipy.spatial.transform import Rotation as R
from typing import List
import pyrealsense2 as rs
import math
import numpy as np
import re
import time
import subprocess

def reset_all_usb_controllers():
    try:
        result = subprocess.run(['usb_resetter', '--reset-all'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = result.stdout.decode()
        if output or len(output) > 0:
            print("Output:", output)

        errors = result.stderr.decode()
        if errors or len(errors) > 0:
            print("Errors:", errors)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"An error occurred: {e}")
        return 1

def clear_recent_logs():
    """Force log rotation and remove older entries beyond a specified time."""
    sudo_path = '/usr/bin/sudo'
    journalctl_path = '/bin/journalctl'
    try:
        # sudo journalctl --flush
        # sudo journalctl --rotate
        # sudo journalctl --vacuum-time=5m
        # Flush the logs
        subprocess.run([sudo_path, journalctl_path, '--flush'], check=True)
        print("Flushed logs")

        # Rotate the journal logs
        subprocess.run([sudo_path, journalctl_path, '--rotate'], check=True)
        print("Logs rotated.")

        # Vacuum logs older than 5 minutes
        subprocess.run([sudo_path, journalctl_path, '--vacuum-time=5m'], check=True)
        print("Old logs vacuumed, only last 5 minutes retained.")

        return 0
    except subprocess.CalledProcessError as e:
        print(f"Error handling logs: {e}")
        return 1

def reboot_system():
    """Reboot the system."""
    sudo_path = '/usr/bin/sudo'
    try:
        subprocess.run([sudo_path, 'reboot', 'now'], check=True)
        print("System is rebooting...")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Error rebooting the system: {e}")
        return 1

def restart_subprocess():
    """Restart a specific service."""
    sudo_path = '/usr/bin/sudo'
    systemctl_path = '/bin/systemctl'
    service_name = "whooplibpython.service"
    try:
        subprocess.run([sudo_path, systemctl_path, 'restart', service_name], check=True)
        print("Restarting service:", service_name)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Error restarting service {service_name}: {e}")
        return 1

def shutdown_system():
    """Shut down the system."""
    sudo_path = '/usr/bin/sudo'
    try:
        subprocess.run([sudo_path, 'shutdown', 'now'], check=True)
        print("System is shutting down...")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Error shutting down the system: {e}")
        return 1


def find_all_indexes(string:str, substring:str) -> List[int]:
    start = 0
    indexes = []
    while True:
        start = string.find(substring, start)
        if start == -1:
            break
        indexes.append(start)
        start += len(substring)  # Move to the next possible start position
    return indexes

def reset_and_initialize_realsense(expecting_num_realsense_devices=2, messenger=None, max_tries=2):

    i = 0
    # Protocol for resetting Realsense USB devices and also protocol for re-scanning USB devices
    realsense_reset_failed = reset_realsense_devices(expecting_num_realsense_devices=expecting_num_realsense_devices) 
    while realsense_reset_failed:
        if messenger:
            messenger.send("Failed")
        print("Realsense Devices Not Detected, Rescanning controllers")
        controllers_reset_error = reset_all_usb_controllers()
        time.sleep(1)
        if controllers_reset_error:
            print("Failed to reset all controllers. Trying again.")
            messenger.send("Rebooting")
            time.sleep(0.5)
            reboot_system()
            continue
        realsense_reset_failed = reset_realsense_devices(expecting_num_realsense_devices=expecting_num_realsense_devices)
        i += 1

def read_messages_from_buffer(buffer:str, start_marker:str, end_marker:str) -> List[str]:
    start_markers = find_all_indexes(buffer, start_marker)
    end_markers = find_all_indexes(buffer, end_marker)

    # Combine and sort the markers
    start_and_end_markers = [(index, start_marker) for index in start_markers] + [(index, end_marker) for index in end_markers]
    start_and_end_markers.sort()

    messages = []

    starter = False
    start_i = -1
    for index, marker in start_and_end_markers:
        if marker == start_marker and not starter:
            starter = True
            start_i = index + len(start_marker)
        elif marker == end_marker and starter:
            starter = False
            messages.append(buffer[start_i: index])
            start_i = -1

    return messages

def get_latest_message_from_buffer(buffer:str, start_marker:str, end_marker:str) -> str:
    messages = read_messages_from_buffer(buffer, start_marker, end_marker)
    if len(messages) == 0:
        return None
    return messages[-1]

def clear_screen():
    """
    This clears the screen
    """
    try:
        # Check if the operating system is Windows
        if os.name == 'nt':
            subprocess.run('cls', check=True, shell=True)
        else:
            subprocess.run('clear', check=True, shell=True)
    except subprocess.CalledProcessError:
        print("Failed to clear the terminal")


class Translation:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

class Rotation:
    def __init__(self, x, y, z, w):
        self.x = x
        self.y = y
        self.z = z
        self.w = w

class Pose:
    def __init__(self, translation:Translation, rotation:Rotation):
        self.translation = translation
        self.rotation = rotation

def radian_wrap(angle):
    """
    Wraps an angle in radians to the range [-pi, pi]
    """
    return (angle + np.pi) % (2 * np.pi) - np.pi

def get_position_and_euler(p):
    """
    This grabs a pose, p, and returns a dictionary
    {'position': (x, y, z), 'euler_angles': (pitch, yaw, roll)}
    In meters and radians
    """
    x, y, z = p.translation.x, p.translation.y, p.translation.z

    # Convert quaternion to Euler angles
    rotation = R.from_quat([p.rotation.x, p.rotation.y, p.rotation.z, p.rotation.w])
    euler_angles = rotation.as_euler('yxz', degrees=False)  # Returns yaw, pitch, roll

    # Reorder to pitch, yaw, roll
    pitch, yaw, roll = euler_angles[1], euler_angles[0], euler_angles[2]

    return {'position': (x, y, z), 'euler_angles': (pitch, yaw, roll)}


def reset_realsense_devices(expecting_num_realsense_devices=2) -> bool:
    # Create a context object. This object owns the handles to all connected realsense devices
    context = rs.context()
    
    # Get a list of all connected devices
    devices = context.query_devices()
    
    if len(devices) < expecting_num_realsense_devices:
        return 1

    i = 0
    if not devices:
        print("No Intel RealSense devices were found.")
    else:
        for dev in devices:
            # The hardware_reset() method sends a hardware reset command that forces the device to disconnect and reconnect
            print(f"Resetting device: {dev.get_info(rs.camera_info.serial_number)}")
            dev.hardware_reset()
            i += 1
            
    if i >= expecting_num_realsense_devices:
        return 0
    return 1