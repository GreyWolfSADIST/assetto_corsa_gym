
class Config(object):
    def __init__(self):
        self.version = "0.0.1"
        # assumed FPS of AC: decimation of telemetry and screen capture (counted in frames);
        # the ego server record rate does not depend on it
        self.sampling_freq = 50  # in Hz
        self.sampling_time = 1 / self.sampling_freq
        self.ego_server_host_name = "0.0.0.0"
        self.ego_server_port = 2345
        # records per second sent to the client; timed on the clock, at most one per graphics frame
        # (ego_server.RecordClock); can be changed while the game runs ('set_ego_sampling_freq <Hz>')
        self.ego_sampling_freq = 25 # in Hz
        self.telemetry_sampling_freq = 0 # in Hz # 0 disables it

        self.opponents_server_host_name = "0.0.0.0"
        self.opponents_server_port = 2346

        self.simulation_management_server_host_name = "0.0.0.0"
        self.simulation_management_server_port = 2347

        self.enable_profiler = False
        self.vjoy_executed_by_server = False

        # Alternative python interpreter
        self.enable_alternative_python_interpreter = False
        # config_python_env_name: Name of the Anaconda environment for constructing the path (default: "p309").
        self.config_python_env_name = "p309"
        # config_python_executable: If provided, uses this path; if None, builds it as:
        #   "<user_home>\AppData\Local\anaconda3\envs\<env_name>\python.exe"
        self.config_python_executable = None
        self.screen_capture_worker = "screen_capture_worker.py"

        # signal events
        self.ego_sampling_freq_event_name = "Local\\EgoSamplingFreqEvent"

        #
        # Camera capture configuration
        #
        self.screen_capture_enable = False
        # This should be a multiple of the resolution set in Assetto Corsa to avoid cropping and padding
        self.final_image_width = 640 // 2       # 320 Final image width in pixels
        self.final_image_height = 480  // 2     # 240 Final image height in pixels
        self.screen_capture_freq = 25 # in Hz
        self.screen_capture_save_to_disk = False
        self.screen_capture_save_path = "captures"  # relative to the AssettoCorsa root folder
        self.screen_capture_verbose = False
        self.relocate_screen = True # relocate screen to 0,0 if True
        self.trigger_image_capture_event_name = "Local\\TriggerImageCapture"
        self.color_mode = "gray"  # Options: "gray" or "bgr"

        if self.vjoy_executed_by_server:
            assert self.sampling_freq == 100, "vJoy is executed by the server. The sampling frequency must be 100 Hz to avoid lagging."
        else:
            assert self.sampling_freq == 50, "vJoy is executed by the client. The sampling frequency must be 50 Hz to avoid lagging."

config = Config()