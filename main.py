import usb_resetter.usb_resetter
import nodes.PoseNode as poseNode
#import nodes.VisionNode as visionNode
import nodes.NodeManager as nodeManager
import nodes.BufferNode as bufferNode
import calculators.OffsetTransform as offsetCalculator
import toolbox
import numpy as np

import time, math

restart_time_minutes = 120 # minutes

def main():
    toolbox.clear_recent_logs()
    
    # Create a manager
    manager = nodeManager.ComputeManager()
    # Node for communication with V5 Brain
    buffer_system = bufferNode.BufferSystem(max_buffer_size=256, port_search_name="VEX Robotics V5 Brain", rate=115200)
    manager.add_compute_node(buffer_system)

    #######################################################
    # Vision System
    #######################################################

    # Create a worker for the manager
    worker = nodeManager.ComputeManager()

    # Messenger to retreive data from odom wheel
    odom_receiver = bufferNode.Messenger(buffer_system, stream="O")

    # Node for T265 Pose (the base)
    t265_pose = poseNode.PoseSystem(serial_odom_messenger=odom_receiver)
    worker.add_compute_node(t265_pose)
    

    # This is for retreiving the pose of the d435i camera as an offset of the T265 transformation (in meters)
    # This of an x y z offset relative to the T265 camera (rigidly attached)
    # If the camera is slightly forward than the T265, then it would be in the -pz direction (meters)
    # If camera is slightly up, it would be in the +py direction (meters)
    # If camera is slightly right, it would be in +px direction (meters)
    # Image of the transformation origins: https://files.readme.io/29080d9-Tracking_Depth_fixture_image.png
    d43i_pose = offsetCalculator.OffsetTransform(t265_pose, px=-16/1000, py=36.40/1000, pz=-4/1000) 

    # This is the pose messenger system for the V5 Brain's Serial Connection.
    pose_messenger = bufferNode.Messenger(buffer_system, stream="P")

    # Register to send the t265 pose to the robot
    t265_pose.register_self_transform_stream(messenger=pose_messenger, max_decimals=5)

    # Object node
    # Note: Enabling laser (laser projection) may cause interference w/ another robot's Realsense camera. Recommended to stay disabled.
    #vision = visionNode.VisionSystem(d43i_pose, version="yolov5n", confidence_minimum=0.2, enable_laser=False, width=640, height=480, fps=6)
    #worker.add_compute_node(vision)
    
    #######################################################
    # Communication and control of Vision System
    #######################################################
    countdown_timer = 0
    worker_started = False

    communication_messenger = bufferNode.Messenger(buffer_system, stream="C", deleteAfterRead=True)

    # Protocol for resetting Realsense USB devices and also protocol for re-scanning USB devices
    # We input that we expect n devices and should try to reset them. If we cannot find n devices, restart/power cycle all USB controllers until we do.
    #toolbox.reset_and_initialize_realsense(expecting_num_realsense_devices=2, messenger=communication_messenger) # We provide the messenger to send "Failed" if failed

    sys_lock = False

    reset_run_once = False
    def message_received(message:str):
        nonlocal countdown_timer
        nonlocal worker_started
        nonlocal sys_lock
        nonlocal reset_run_once
        stripped_message = message.strip()

        if "Initialize" in stripped_message:
            print("Requested to initialize")
            # Restart
            if worker_started:
               communication_messenger.send("ReInitializing")
               worker.restart()
            else:
               communication_messenger.send("Initializing")

        if "Reboot" in stripped_message:
            print("Rebooting")
            communication_messenger.send("Rebooting Jetson")
            time.sleep(1)
            toolbox.reboot_system()
        elif "Shutdown" in stripped_message:
            communication_messenger.send("Shutting Jetson Off")
            print("Shutting down")
            time.sleep(1)
            toolbox.shutdown_system()
        elif "RestartProcess" in stripped_message:
            communication_messenger.send("Restarting process")
            time.sleep(1)
            toolbox.restart_subprocess()

        try:
            asked_time = int(stripped_message.split(" ")[0])
        except:
            communication_messenger.send("Rejected Time Reset")
            return
        communication_messenger.send("Approved")
        
        if asked_time < 0:
            asked_time *= -1

        countdown_timer = asked_time

        if not worker_started:
            if not reset_run_once:
                reset_run_once = True
                sys_lock = True
                toolbox.reset_and_initialize_realsense(expecting_num_realsense_devices=2, max_tries=2, messenger=communication_messenger) # We provide the messenger to send "Failed" if failed
                sys_lock = False
            print("Started working as per request by V5 Brain")
            worker_started = True
            worker.start()

    communication_messenger.on_message(message_received)
    communication_messenger.send("Hello")

    manager.start()

    try:
        print("Running")
        while True:
            try:
                while(sys_lock):
                    time.sleep(0.1)
                countdown_timer -= 1

                if countdown_timer < 0:
                    if worker_started:
                        print("Stopped working as no keep-alive from V5 Brain")
                        worker.stop()
                        worker_started = False

                    # Reboot system every x minutes to clear memory leaks
                    if (-countdown_timer) > restart_time_minutes*60:
                        toolbox.reboot_system()
                # Sleep
                time.sleep(1)
            except Exception as e:
               print(e)
               time.sleep(0.01)
               continue

    finally: # <-- If CTRL + C
        manager.stop()

if __name__ == "__main__":
    main()
