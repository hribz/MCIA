import json

origin_json = '../benchmark.json'
output_json = '../cleaned_options.json'

origin_config = json.load(open(origin_json, 'r'))

# If option startswith these headers, changing its type to switch.
switcher_headers = {
    'autoconf': {
        'positive': ['--with', '--enable'],
        'negative': ['--without', '--disable']
    }
}

for project in origin_config:
    print(project['project'])
    config = project.get('config_options')
    build_type = project['build_type']
    if not config:
        print('no config options')
        continue
    constants = project['constant_options'] if 'constant_options' in project else []
    if constants and build_type == 'cmake':
        # remove all begin "-D"
        constants = [constant[2:] if constant.startswith('-D') else constant for constant in constants]
    key_of_constants = [op.split("=")[0] for op in constants]
    # remove constant options in config
    config = [option for option in config if option['key'] not in key_of_constants]
    # remove ignore options
    if 'ignore_options' in project:
        config = [option for option in config if option['key'] not in project['ignore_options']]
    config = [option for option in config if option['kind'] != 'ignore']

    # Reclassify some options.
    headers = switcher_headers.get(build_type)
    if headers is not None:
        headers_list = headers['positive'].copy()
        headers_list.extend(headers['negative'])
        for option in config:
            key = option['key']
            if option['kind'] != 'positive' and option['kind'] != 'negative':
                for header in headers_list:
                    if key.startswith(header) and len(option['values']) < 2:
                        option['kind'] = 'positive' if header in headers['positive'] else 'negative'
    
    special_turn_on = project.get('special_turn_on', [])
    turn_on_values = {}
    for op in special_turn_on:
        k_and_v = op.split('=')
        key = k_and_v[0]
        val = k_and_v[1] if len(k_and_v)==2 else ""
        turn_on_values[key] = val
    
    for option in config:
        if option['key'] in turn_on_values:
            option['on_value'] = turn_on_values[option['key']]

    project['config_options'] = config

json.dump(origin_config, open(output_json, 'w'), indent=4)