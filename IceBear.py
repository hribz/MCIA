import subprocess
import utils

class IceBearConfig:
    def __init__(self):
        pass

    def to_list(self) -> list:
        ret = []
        return ret

class IceBear:
    def __init__(self, icebear: str):
        self.icebear: str = icebear
        pass

    def run(self, config: IceBearConfig):
        cmd = [self.icebear]
        cmd.extend(config.to_list())
        try:
            subprocess.run(utils.commands_to_shell_script(cmd), shell=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            pass