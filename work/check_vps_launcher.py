"""Offline shell orchestration checks; OS/package/service commands are mocked."""
from pathlib import Path
import os
import subprocess
import time

root = Path(__file__).resolve().parents[1]
bash = Path('C:/Program Files/Git/bin/bash.exe')
source = (root / 'start_reminder_vps.sh').read_text(encoding='utf-8')
for block in source.split("<<'PY'\n")[1:]:
    compile(block.split('\nPY\n')[0], '<embedded python>', 'exec')
base = root / 'work' / ('vps_launcher_checks_' + str(time.time_ns()))
base.mkdir()
def unix(path):
    s = path.resolve().as_posix()
    return '/' + s[0].lower() + s[2:]

for case in ('install_and_repeat', 'start_failure'):
    area = base / case
    area.mkdir()
    for name in ('app', 'state', 'units', 'systemd', 'data'):
        (area / name).mkdir()
    for name in ('five_league_reminder.py', 'requirements.txt', '.env.example'):
        (area / name).write_bytes((root / name).read_bytes())
    for name in ('five-league-reminder.service', 'five-league-reminder.timer'):
        (area / 'systemd' / name).write_bytes((root / 'systemd' / name).read_bytes())
    config = area / 'config.env'
    config.write_text('TEST_CONFIGURATION_PRESERVED=1\n', encoding='utf-8')
    (area / 'data' / 'sent.json').write_text('{"test": "dedupe-preserved"}', encoding='utf-8')
    text = source.replace('APP=/opt/five-league-reminder', f'APP={unix(area / "app")}')
    text = text.replace('STATE=/var/lib/five-league-reminder', f'STATE={unix(area / "state")}')
    text = text.replace('CONFIG=/etc/five-league-reminder.env', f'CONFIG={unix(config)}')
    text = text.replace('[[ $EUID -eq 0 ]]', 'true')
    text = text.replace('[[ -d /run/systemd/system ]]', 'true')
    text = text.replace('/run/lock/five-league-reminder-install.lock', unix(area / 'install.lock'))
    text = text.replace('/etc/systemd/system/', unix(area / 'units') + '/')
    (area / 'start_reminder_vps.sh').write_text(text, encoding='utf-8', newline='\n')
    mock_python = '''#!/usr/bin/env bash
if [[ "$1" == -m ]]; then exit 0; fi
body=$(cat)
if [[ "$*" == *config.env* ]]; then printf '%s/state/sent.json\\n' "$TEST_AREA"; fi
'''
    (area / 'mock_python').write_text(mock_python, encoding='utf-8', newline='\n')
    wrapper = r'''#!/usr/bin/env bash
set -e
uname() { echo Linux; }
apt-get() { :; }
flock() { :; }
getent() { return 0; }
chown() { :; }
sleep() { echo wait >> "$TEST_AREA/events"; }
systemctl() {
    echo "$*" >> "$TEST_AREA/events"
    if [[ "$1" == show && "$*" == *ActiveState* ]]; then
        if [[ ! -f "$TEST_AREA/waited" ]]; then touch "$TEST_AREA/waited"; echo activating; else echo inactive; fi
    fi
    if [[ "$1 ${2:-}" == 'start five-league-reminder.service' && "$FAIL_START" == 1 ]]; then return 1; fi
    return 0
}
install() {
    local args=() directory=0
    while (($#)); do
        case "$1" in -o|-g|-m) shift 2;; -d) directory=1; shift;; *) args+=("$1"); shift;; esac
    done
    if [[ "$directory" == 1 ]]; then mkdir -p "${args[@]}"; else cp "${args[@]}"; fi
}
python3() {
    if [[ "$1 $2" == '-m venv' ]]; then
        mkdir -p "$3/bin"
        cp "$TEST_AREA/mock_python" "$3/bin/python"
    fi
}
source "$TEST_AREA/start_reminder_vps.sh"
'''
    (area / 'runner.sh').write_text(wrapper, encoding='utf-8', newline='\n')
    env = {**os.environ, 'TEST_AREA': unix(area), 'FAIL_START': str(int(case == 'start_failure'))}
    run = subprocess.run([str(bash), unix(area / 'runner.sh')], env=env, capture_output=True, text=True, encoding='utf-8')
    (area / 'output.txt').write_text(run.stdout + run.stderr, encoding='utf-8')
    assert run.returncode == (1 if case == 'start_failure' else 0), run.stdout + run.stderr
    events = (area / 'events').read_text()
    assert 'stop five-league-reminder.service' not in events
    assert 'wait\n' in events
    assert ('enable --now five-league-reminder.timer' in events) == (case != 'start_failure')
    assert config.read_text() == 'TEST_CONFIGURATION_PRESERVED=1\n'
    assert (area / 'state' / 'sent.json').read_text() == '{"test": "dedupe-preserved"}'
    if case == 'install_and_repeat':
        (area / 'state' / 'sent.json').write_text('EXISTING VPS STATE', encoding='utf-8')
        run = subprocess.run([str(bash), unix(area / 'runner.sh')], env=env, capture_output=True, text=True, encoding='utf-8')
        assert run.returncode == 0, run.stdout + run.stderr
        assert (area / 'state' / 'sent.json').read_text() == 'EXISTING VPS STATE'
        assert config.read_text() == 'TEST_CONFIGURATION_PRESERVED=1\n'
    print(case + ': PASS')
print('Embedded Python syntax: PASS; all package/service operations mocked; no notifications sent.')
