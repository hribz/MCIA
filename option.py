from enum import Enum, auto
from typing import List
from logger import logger

class OptionType(Enum):
    positive = auto()
    negative = auto()
    options = auto()

    @staticmethod
    def getType(option_type: str):
        if option_type == 'positive':
            return OptionType.positive
        elif option_type == 'negative':
            return OptionType.negative
        else:
            return OptionType.options
    
    def getStr(self):
        if self == OptionType.positive:
            return 'positive'
        elif self == OptionType.negative:
            return 'negative'
        else:
            return 'options'

class Option:
    on_value_set = {'yes', '1', 'on'}
    off_value_set = {'no', '0', 'off'}

    def __init__(self, option, values, switch_values, kind: OptionType, conflict, combination, on_value):
        self.option = option # The name of the config option.
        self.values = values # Possible values of the option, the first element is default value.
        # If this option is a switch, the values of the switch when turn on/off.
        # {"on": "yes", "off": "no"}
        self.switch_values = switch_values
        self.kind = kind     # The kind of the option, determine how to turn on/off it.
        # Options cannot be turn on if this option is turn on.
        self.conflict = set(conflict) if conflict else set()
        # Option must be turn on if this option is tuen on.
        # ["key=value", ...]
        self.combination = combination if combination else set()

        if self.switch_values:
            self.on_value = self.switch_values.get('on')
            self.off_value = self.switch_values.get('off')
        else:
            # No provided values, try to guess from the option.
            self.on_value = '1'
            self.off_value = '0'
            for value in self.values:
                value = str(value)
                if value.lower() in self.on_value_set:
                    self.on_value = value
                elif value.lower() in self.off_value_set:
                    self.off_value = value
        if on_value:
            # Override default on value by specific on value.
            self.on_value = on_value

    def is_switch(self):
        return self.kind == OptionType.positive or self.kind == OptionType.negative

    def turn_on(self):
        if self.is_switch() and self.switch_values:
            if self.on_value is None:
                # This option shouldn't appear in the command line.
                return None
            elif self.on_value == "":
                # This option doesn't have value.
                return self.option
            else:
                return f"{self.option}={self.on_value}"
        if len(self.values) > 0:
            # --enable-foo=yes
            return f"{self.option}={self.on_value}"
        # --enable-foo
        return self.option
    
    def turn_off(self):
        if self.is_switch() and self.switch_values:
            if self.off_value is None:
                # This option shouldn't appear in the command line.
                return None
            elif self.off_value == "":
                # This option doesn't have value.
                return self.option
            else:
                return f"{self.option}={self.off_value}"
        if len(self.values) > 0:
            # --enable-foo=no
            return f"{self.option}={self.off_value}"
        # empty
        return None
    
    def positive(self):
        # value and turn on/off
        if self.kind == OptionType.positive:
            return self.turn_on(), True
        elif self.kind == OptionType.negative:
            return self.turn_off(), False
        else:
            return None, False
    
    def negative(self):
        # value and turn on/off
        if self.kind == OptionType.positive:
            return self.turn_off(), False
        elif self.kind == OptionType.negative:
            return self.turn_on(), True
        else:
            return None, False
        

class ConfigType(Enum):
    default = auto()
    all_positive = auto()
    all_negative = auto()
    one_positive = auto()
    one_negative = auto()

class SamplingConfig:
    def __init__(self, options: List[Option], num):
        self.positive_num = len([i for i in options if i.kind == OptionType.positive])
        self.negative_num = len([i for i in options if i.kind == OptionType.negative])
        self.num = num # The sampling number of one_positive and one_negative.
        self.positive_gap = self.positive_num // self.num
        self.negative_gap = self.negative_num // self.num

    def print(self):
        print(f"positive: (op: {self.positive_num}, gap: {self.positive_gap})\nnegative: (op: {self.negative_num}, gap: {self.negative_gap})")

class ConfigSampling:
    def __init__(self, options: List[Option], sampling_config: SamplingConfig):
        self.positive_idx = 0
        self.negative_idx = 0
        self.options = options
        self.options_set = set()
        self.sampling_config = sampling_config

    def get_options_hash(self, options: List[str]):
        return hash(tuple(options))
    
    def continue_sampling(self, kind: ConfigType):
        if kind == ConfigType.one_positive:
            return self.positive_idx < len(self.options)
        elif kind == ConfigType.one_negative:
            return self.negative_idx < len(self.options)
        else:
            return False

    def get_different_kind_configuration(self, kind: ConfigType):
        options: List[str] = []
        option_to_idx = dict()
        conflict_options = set()

        def add_to_options(op, overwrite):
            nonlocal options, option_to_idx
            if op is not None:
                ops = op.split("=")
                if ops[0] in option_to_idx:
                    if overwrite:
                        options[option_to_idx[ops[0]]] = op
                else:
                    option_to_idx[ops[0]] = len(options)
                    options.append(op)
        
        def handle_option(op, state, option: Option) -> bool:
            nonlocal conflict_options
            if state == True:
                # This option is turn on.
                if option.option not in conflict_options:
                    # Update conflict options set.
                    conflict_options = conflict_options.union(option.conflict)
                    # This option cannot be turn on if any of its combination is in conflict options set.
                    combination_conflict = False
                    for com_op in option.combination:
                        ops = com_op.split("=")
                        if ops[0] in conflict_options:
                            if com_op == option.negative()[0]:
                                # This option is in conflict options set, but it's ok to takes the negative value.
                                continue
                            else:
                                combination_conflict = True
                                break
                    if combination_conflict:
                        return False
                    add_to_options(op, False)
                    # Options in combination must be set to these value.
                    for com_op in option.combination:
                        add_to_options(com_op, True)
                else:
                    add_to_options(option.negative()[0], True)
            else:  
                # This option is turn off.
                add_to_options(op, False)
            return True

        if kind == ConfigType.default:
            pass
        elif kind == ConfigType.one_positive:
            while self.positive_idx < len(self.options) and ((not self.options[self.positive_idx].is_switch()) or self.options[self.positive_idx].option == '--enable-all'):
                self.positive_idx += 1
            if self.positive_idx >= len(self.options):
                return None
            status = False
            while self.positive_idx < len(self.options) and not status:
                option = self.options[self.positive_idx]
                op, state = option.positive()
                status = handle_option(op, state, option)
                self.positive_idx += 1
        elif kind == ConfigType.one_negative:
            while self.negative_idx < len(self.options) and ((not self.options[self.negative_idx].is_switch()) or self.options[self.negative_idx].option == '--disable-all'):
                self.negative_idx += 1
            if self.negative_idx >= len(self.options):
                return None
            status = False
            while self.negative_idx < len(self.options) and not status:
                option = self.options[self.negative_idx]
                op, state = option.negative()
                status = handle_option(op, state, option)
                self.negative_idx += 1
        else:
            for option in self.options:
                if kind == ConfigType.all_positive:
                    op, state = option.positive()
                    if state and option.option == '--enable-all':
                        logger.info(f"[Enable All] --enable-all is turn on, don't need to consider other options.")
                        options = [op]
                        break
                elif kind == ConfigType.all_negative:
                    op, state = option.negative()
                    if state and option.option == '--disable-all':
                        logger.info(f"[Disable All] --disable-all is turn on, don't need to consider other options.")
                        options = [op]
                        break
                else:
                    # TODO: select one value
                    op, state = None, False
                status = handle_option(op, state, option)
                if not status:
                    continue
        
        options_hash = self.get_options_hash(options)
        if options_hash in self.options_set:
            logger.debug(f'skip duplicate options {options}')
            return None
        else:
            self.options_set.add(options_hash)

        if len(conflict_options):
            logger.debug(f"[Conflict Options] {conflict_options}")

        return options
    
    def get_all_options(self, kind: ConfigType):
        all_options = []
        while self.continue_sampling(kind):
            options = self.get_different_kind_configuration(kind)
            if options is not None:
                all_options.append(options)
        return all_options