from enum import Enum, auto
import subprocess
import os
import re

from utils import *
from logger import logger

class GlobalConfig:
    cmake = 'cmake'
    bear = 'bear'
    build_jobs = 16

    def __init__(self):
        def get_bear_version(bear):
            try:
                result = subprocess.run([bear, "--version"], capture_output=True, text=True, check=True)
                match = re.match(r'bear (\d+)\.', result.stdout)
                if match:
                    return int(match.group(1))
                return 2
            except (subprocess.CalledProcessError, OSError):
                return 2
        self.bear_version = get_bear_version(GlobalConfig.bear)

global_config = GlobalConfig()

class BuildType(Enum):
    CMake = auto()
    AutoConf = auto()
    Unknown = auto()

    @staticmethod
    def getType(build_type: str):
        if build_type == 'cmake':
            return BuildType.CMake
        elif build_type == 'autoconf':
            return BuildType.AutoConf
        else:
            return BuildType.Unknown

class Option:
    def __init__(self, option, values):
        self.option = option # Name of the config option.
        self.values = values # Possible values of the option, the first element is default value.

class Configuration:
    def __init__(self, build_type, options, src_path, build_path, cache_path):
        self.options: list[list[str]] = options
        self.build_type = build_type
        self.src_path = src_path
        self.cache_path = cache_path
        self.build_path = build_path
        self.compile_database = os.path.join(self.build_path, "compile_commands.json")

    def option_cmd(self):
        cmd = []
        if self.build_type == BuildType.CMake:
            cmd = [
                "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
            ]
        for option in self.options:
            option_str = option[0]
            if len(option) == 2:
                option_str += f"={option[1]}"
            if self.build_type == BuildType.CMake:
                option_str = f"-D{option_str}"
            cmd.append(option_str)
        return cmd

    def config_cmd(self):
        cmd = []
        if self.build_type == BuildType.CMake:
            cmd = [GlobalConfig.cmake]
            cmd.extend(["-S", self.src_path])
            cmd.extend(["-B", self.build_path])
        elif self.build_type == BuildType.AutoConf:
            cmd = [f'{self.src_path}/configure']
            cmd.append(f"--prefix={self.build_path}")
        cmd.extend(self.option_cmd())
        return cmd
    
    def build_cmd(self):
        cmd = []
        if self.build_type == BuildType.CMake:
            cmd = ["cmake"]
            cmd.extend(["--build", f"{self.build_path}"])
            cmd.append(f"-j{GlobalConfig.build_jobs}")
        elif self.build_type == BuildType.AutoConf:
            cmd = ['make', f"-j{GlobalConfig.build_jobs}"]
            cmd.extend(['-C', self.build_path])
        cmd.extend(self.option_cmd())
        return cmd

class Project:
    def __init__(self, workspace, build_dir, options, build_type):
        self.workspace = workspace # Directory to store cache and analysis results. 
        self.build_dir = build_dir # Directory to build project.
        self.config_list: list[Configuration] = []
        self.config_options: list[Option] = options
        self.build_type = build_type


    def configure(self, config: Configuration) -> bool:
        return run(config.config_cmd(), config.build_path, "Configure Script")            
        
    def build(self, config: Configuration) -> bool:
        if global_config.bear_version == 2:
            cmd = [GlobalConfig.bear, '--cdb', str(config.compile_database)]
        else:
            cmd = [GlobalConfig.bear, '--output', str(config.compile_database), '--']
        cmd.extend(config.build_cmd())
        return run(cmd, config.build_path, "Build Script")

    def build_clean(self, config: Configuration):
        run_without_check(["make", "clean"], config.build_path, "Make Clean")

    def process_every_configuraion(self):
        for config in self.config_list:
            self.build_clean(config)
            self.configure(config)
            self.build(config)