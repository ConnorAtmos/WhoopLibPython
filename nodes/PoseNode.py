import pyrealsense2 as rs
import numpy as np
from collections import namedtuple
from functools import partial
import threading
import time
from scipy.spatial.transform import Rotation as R
import toolbox

max_initialization_time = 3

attrs = [
    'acceleration',
    'angular_acceleration',
    'angular_velocity',
    'mapper_confidence',
    'rotation',
    'tracker_confidence',
    'translation',
    'velocity',
]

class PoseSystem:
    def __init__(self, debugMode=False):
        """
        Initializes configurations for pose estimation
        """
        self.Pose = namedtuple('Pose', attrs)
        self.pipeline = rs.pipeline()
        self.cfg = rs.config()
        # if only pose stream is enabled, fps is higher (202 vs 30)
        self.cfg.enable_stream(rs.stream.pose)
        self.lock = threading.Lock()
        self.running = False
        self.debugMode = debugMode

    def start_pipeline(self, lock: threading.Lock = None):
        """
        This starts the streaming pipeline for the tracking camera.
        """
        if self.running:
            return
        self.running = True

        self.pipeline.start(self.cfg)

        if lock:
            self.lock = lock

        self.allowable_run = True
        self.first_pass = False

        def runner(self):
            while self.allowable_run:
                if self.debugMode:
                    self.__step()
                else:
                    try:
                        self.__step()
                    except Exception as e:
                        print(f"Thread Pose Estimation: Error occurred - {e}. Restarting thread.")
                        continue
                if not self.first_pass:
                    self.first_pass = True

        self.pipethread = threading.Thread(target=runner, args=[self])
        self.pipethread.daemon = True
        self.pipethread.start()

        t = 0
        while not self.first_pass:
            t += 0.1
            time.sleep(0.1)
            if t >= max_initialization_time:
                break

    def stop_pipeline(self):
        """
        This stops the streaming pipeline for the tracking camera.
        """
        if not self.running:
            return
        self.running = False

        self.allowable_run = False
        self.pipethread.join()
        self.pipeline.stop()

    def __step(self):
        """
        This steps the system and applies p, or a pose
        """
        frames = self.pipeline.wait_for_frames()
        if not frames:
            return

        pose_frame = frames.get_pose_frame()
        if not pose_frame:
            return

        pose = pose_frame.get_pose_data()
        p = self.Pose(*map(partial(getattr, pose), attrs))
        # Lock and update variables
        with self.lock:
            self.p = p


    def get_pose(self):
        return self.p
    
    def get_position_and_euler(self):
        p = self.get_pose()
        return toolbox.get_position_and_euler(p)