import re
import zipfile
import sys
sys.path.insert(0, '/home/z/my-project/mini-services/save-parser')
from clausewitz_parser import parse_clausewitz

with zipfile.ZipFile('/home/z/my-project/download/reference.sav', 'r') as z:
    gs = z.read('gamestate').decode('utf-8')

# Test with direct function from server
exec(open('/home/z/my-project/mini-services/save-parser/server.py').read().split('get_delayed_events_from_text')[1].split('\n'))
    pass
print('Compiling...')
    exec(compile(open('/home/z/my-project/mini-services/save-parser/server.py').read()))
    print('Running...')
    result = get_delayed_events_from_text(gs, 0)
    print(f'Result: {result}')
except Exception as e:
    print(f'ERROR: {e}')
    import traceback
    traceback.print_exc()
