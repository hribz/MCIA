from enum import Enum, auto

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
        self.combination = combination if combination else []

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