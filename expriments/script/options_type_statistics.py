import json

projects = json.load(open('../cleaned_options.json', 'r'))
statistics = {}

for project in projects:
    print(project['project'])
    if 'config_options' not in project:
        continue
    options = project['config_options']
    positive = 0
    negative = 0
    ignore = 0
    optype = 0

    conflict = 0
    combine = 0

    for option in options:
        if option['kind'] == 'positive':
            positive+=1
        elif option['kind'] == 'negative':
            negative+=1
        elif option['kind'] == 'ignore':
            ignore+=1
        elif option['kind'] == 'options':
            optype+=1
        
        if 'conflict' in option:
            conflict+=1
        if 'combination' in option:
            combine+=1

    statistics[project['project']] = {
        "all": len(options),
        "positive": positive,
        "negative": negative,
        "ignore": ignore,
        "options": optype,
        "conflict": conflict,
        "combine": combine
    }

with open('cleaned_options_statistics.json', 'w') as f:
    json.dump(statistics, f, indent=4)