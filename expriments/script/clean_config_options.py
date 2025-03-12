import json

origin_json = '../config_options_QwQ-32B.json'
output_json = '../cleaned_options.json'

origin_config = json.load(open(origin_json, 'r'))

for project in origin_config:
    print(project['project'])
    config = project.get('config_options')
    if not config:
        print('no config options')
        continue
    constants = project['constant_options'] if 'constant_options' in project else []
    key_of_constants = [op.split("=")[0] for op in constants]
    # remove constant options in config
    config = [option for option in config if option['key'] not in key_of_constants]
    # remove ignore options
    if 'ignore_options' in project:
        config = [option for option in config if option['key'] not in project['ignore_options']]
    config = [option for option in config if option['kind'] != 'ignore']

    # clean unneccessary values
    for option in config:
        key = option['key']
        if key.startswith("--enable") or key.startswith('--disable'):
            option['values'] = []
    
    project['config_options'] = config

json.dump(origin_config, open(output_json, 'w'), indent=4)