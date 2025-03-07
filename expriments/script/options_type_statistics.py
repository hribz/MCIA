import json

projects = json.load(open('../config_options.json', 'r'))

FFmpeg = projects[1]

options = FFmpeg['config_options']
positive = 0
negative = 0

for option in options:
    if option['kind'] == 'positive':
        positive+=1
    elif option['kind'] == 'negative':
        negative+=1

print(f"all:{len(options)}")
print(f"positive:{positive}")
print(f"negative:{negative}")