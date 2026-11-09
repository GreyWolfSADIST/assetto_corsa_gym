import sys
import socket
import json
import logging
import time
import pandas as pd
import numpy as np
import os
from AssettoCorsaEnv.pygame_joystick_handler import JoystickHandler
from AssettoCorsaPlugin.plugins.sensors_par.car_control import Controls

if sys.platform.startswith("win"):
    import AssettoCorsaPlugin.plugins.sensors_par.dual_buffer as dual_buffer

logger = logging.getLogger(__name__)

MAX_MSG_SIZE = 2**18

class SimulationManagement:
    def __init__(self, config):
        self.config = config
        self.host = config.simulation_management_server_host_name
        self.port = config.simulation_management_server_port

        self.max_msg_size = 2**20

    def send_message(self, message, wait_response=False):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.host, self.port))
            s.sendall(message.encode())
            s.settimeout(5)
            if wait_response:
                data = s.recv(self.max_msg_size).decode()
                return data
            else:
                return None

    def send_reset(self):
        logger.info("sending reset to simulation management server")
        self.send_message("reset")
        time.sleep(1)

    def get_track_info(self):
        data = self.send_message("get_track_info", wait_response=True)
        return eval(data)

    def get_static_info(self):
        static_info = eval(self.send_message("get_static_info", wait_response=True))
        track_full_name = f"{static_info['TrackName']}"
        if static_info['TrackConfiguration']:
            track_full_name += f"-{static_info['TrackConfiguration']}"
        static_info["TrackFullName"] = track_full_name
        return static_info

    def get_config(self):
        return eval(self.send_message("get_config", wait_response=True))

    def set_ego_sampling_freq(self, freq_hz):
        """Change the plugin record rate while the game runs; returns the rate the plugin reports."""
        reply = self.send_message("set_ego_sampling_freq {}".format(freq_hz), wait_response=True) or ""
        if not reply.startswith("ok "):
            raise RuntimeError("Plugin did not accept set_ego_sampling_freq {}: {!r} (plugin older than "
                               "this client? deploy sensors_par)".format(freq_hz, reply))
        return float(reply.split()[1])


class Client():
    def __init__(self, config):
        self.config = config
        self.vjoy_executed_by_server = config.vjoy_executed_by_server
        self.server_host = config.ego_server_host_name
        self.server_port = config.ego_server_port
        self.simulation_management_server_host_name = config.simulation_management_server_host_name
        self.simulation_management_server_port = config.simulation_management_server_port
        self.state = ServerState()
        self.simulation_management = SimulationManagement(self.config)
        self.socket = None
        self.controls = DriverControls(self.vjoy_executed_by_server)
        self.record_controls_from_client = config.record_controls_from_client

        # Joystick handler (only used if needed)
        self.joystick_handler = None
        self.screen_capture_enable = self.config.screen_capture_enable
        self.camera = None
        self.current_image = None

        if self.screen_capture_enable:
            self.camera = dual_buffer.GrabberSharedMemoryDualBuffer(self.config.final_image_width,
                                                                       self.config.final_image_height,
                                                                       self.config.color_mode)

        if self.record_controls_from_client:
            self.joystick_handler = JoystickHandler()
            self.joystick_handler.initialize()

    def reply_to_server(self, msg):
        if not self.socket:
            return
        try:
            self.socket.sendto(msg.encode(), (self.server_host, self.server_port))
        except socket.error as emsg:
            logger.error(f"Error sending to server: {emsg}")
            raise TimeoutError

    def setup_connection(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(2)
        logger.info(f"AC Client. Listening at host: {self.server_host} port: {self.server_port}")

        while True:
            self.reply_to_server("connect")
            try:
                # Receive data from server
                data, _ = self.socket.recvfrom(MAX_MSG_SIZE)
                data = data.decode()
                logger.debug(f"Got from server: {data}")
                if data == "identified":
                    logger.info(f"Client connected on {self.server_port}")
                    break
            except socket.timeout:
                continue
        self.get_servers_input()

    def get_current_image(self):
        if self.screen_capture_enable:
            return self.current_image
        else:
            return None

    def get_servers_input(self):
        if not self.socket:
            return

        while True:
            try:
                # Receive data from server
                data, _ = self.socket.recvfrom(MAX_MSG_SIZE)
                data = data.decode()
                logger.debug(f"Got from server: {data}")
                if data == "disconnect":
                    logger.info("Server stopped the connection")
                    self.state["done"] = True
                elif data == "identified":
                    logger.info("Server identified")
                else:
                    self.state.parse_server_str(data)
                    # get current image from the server immediately after receiving the state
                    # to keep the image and state in sync
                    if self.screen_capture_enable:
                        _, _, img_array = self.camera.get_active_image()
                        self.current_image = img_array
                break
            except socket.timeout:
                continue

    def get_pending_inputs(self):
        """States of all records already waiting in the socket buffer, oldest first; never blocks.

        step_sim() reads one datagram per call, so after a pause in reading the following calls return
        records that waited in the buffer (up to about a second old). A controller should act on the
        newest record; a logger can keep them all.
        """
        states = []
        if not self.socket:
            return states
        self.socket.setblocking(False)
        try:
            while True:
                try:
                    data, _ = self.socket.recvfrom(MAX_MSG_SIZE)
                except (BlockingIOError, socket.timeout):
                    break
                data = data.decode()
                if data == "disconnect":
                    logger.info("Server stopped the connection")
                    self.state["done"] = True
                elif data != "identified":
                    self.state.parse_server_str(data)
                    states.append(self.state.copy())
        finally:
            self.socket.settimeout(2)
        if states and self.screen_capture_enable:
            _, _, self.current_image = self.camera.get_active_image()
        return states

    def step_sim_all(self):
        """Like step_sim(), but returns the awaited state and every state queued behind it, oldest first.

        The last state is the newest one: act on it, log all of them.
        """
        self.get_servers_input()
        states = [self.state.copy()] + self.get_pending_inputs()
        if self.record_controls_from_client and self.joystick_handler and self.joystick_handler.is_initialized():
            inputs = self.joystick_handler.read_inputs()
            for state in states:
                state.update(inputs)
        return states

    def respond_to_server(self):
        if not self.vjoy_executed_by_server:
            self.controls.apply_local_controls()
        else:
            if not self.socket:
                return
            self.controls["server_steps"] = self.state["steps"] # send back
            self.reply_to_server(self.controls.export())

    def reset(self, send_reset=True):
        if self.socket:
            self.close()
        if send_reset:
            self.simulation_management.send_reset()
        self.controls.set_defaults()
        self.setup_connection()

    def close(self):
        # Send disconnect message
        if not self.vjoy_executed_by_server:
            self.controls.set_defaults()
            self.controls.apply_local_controls()
            # release vJoy so a later process (e.g. train.py after a notebook) can acquire it;
            # the next apply_local_controls() acquires it again
            self.controls.release_local_controls()
        self.reply_to_server("disconnect")
        time.sleep(0.1)
        if self.socket:
            self.socket.close()
        self.socket = None

    def step_sim(self):
        self.get_servers_input()
        state = self.state.copy()

        if self.record_controls_from_client and self.joystick_handler and self.joystick_handler.is_initialized():
            state.update(self.joystick_handler.read_inputs())
        return state

    def export_track_and_racing_line(self, output_path="."):
        os.makedirs(output_path, exist_ok=True)

        track_info = self.simulation_management.get_track_info()
        static_info = self.simulation_management.get_static_info()

        left_border_x = np.array( track_info['left_lane'] )[:,0]
        left_border_y = np.array( track_info['left_lane'] )[:,1]

        right_border_x = np.array( track_info['right_lane'] )[:,0]
        right_border_y = np.array( track_info['right_lane'] )[:,1]

        fast_lane_x = np.array( track_info['fast_lane'] )[:,0]
        fast_lane_y = np.array( track_info['fast_lane'] )[:,1]

        # save track borders
        track_full_name = f"{static_info['TrackName']}"
        if static_info['TrackConfiguration']:
            track_full_name += f"-{static_info['TrackConfiguration']}"

        track_file_name = f"{output_path}/{track_full_name}.csv"
        df = pd.DataFrame({
            'left_border_x': left_border_x,
            'left_border_y': left_border_y,
            'right_border_x': right_border_x,
            'right_border_y': right_border_y,
            'pos_x': fast_lane_x,
            'pos_y': fast_lane_y
        })
        logger.info(f"Saving track to {track_file_name}")
        df.to_csv(f"{track_file_name}", index=False)

        print(static_info)

        # save racing line for that car -> TODO check if this is car dependent
        racing_line_file_name = f"{output_path}/{static_info['TrackName']}"
        if static_info['TrackConfiguration']:
            racing_line_file_name += f"-{static_info['TrackConfiguration']}"
        #racing_line_file_name += f"-{static_info['CarName']}"
        racing_line_file_name += f"-racing_line.csv"
        logger.info(f"Saving racing line {racing_line_file_name}")

        df = pd.DataFrame({
            'pos_x': fast_lane_x,
            'pos_y': fast_lane_y
        })
        df.to_csv(f"{racing_line_file_name}", index=False)
        return track_full_name, track_file_name, racing_line_file_name, static_info

class ServerState(dict):
    def __init__(self):
        self["done"] = False

    def parse_server_str(self, server_string):
        self.update( eval(server_string) )

class DriverControls(dict):
    def __init__(self, vjoy_executed_by_server=False):
        self.vjoy_executed_by_server = vjoy_executed_by_server

        self.set_defaults()

        if not self.vjoy_executed_by_server:
            logger.warning("Controls will be executed locally and not by the server")
            self.local_controls = Controls()

    def set_defaults(self):
        # steer, acc and brake are in the range [-1, 1]
        self["steer"] = 0
        self["acc"] = -1
        self["brake"] = -1
        self["enable_gear_shift"] = 0
        self["shift_up"] = 0
        self["shift_down"] = 0

    def set_controls(self, steer, acc, brake, enable_gear_shift=False, shift_up=False, shift_down=False):
        self["steer"] = steer
        self["acc"] = acc
        self["brake"] = brake
        self["enable_gear_shift"] = enable_gear_shift
        self["shift_up"] = shift_up
        self["shift_down"] = shift_down

    def apply_local_controls(self):
        self.local_controls.set_controls(steer=self["steer"],
                                         acc=self["acc"],
                                         brake=self["brake"],
                                         enable_gear_shift=self["enable_gear_shift"],
                                         shift_up=self["shift_up"],
                                         shift_down=self["shift_down"])

    def release_local_controls(self):
        self.local_controls.close()

    def export(self):
        return json.dumps(self)