#!/usr/bin/env bash
# Ubuntu 22.04+ / Debian 12+, with systemd. Run: sudo bash start_reminder_vps.sh
set -Eeuo pipefail
umask 022

APP=/opt/five-league-reminder
STATE=/var/lib/five-league-reminder
CONFIG=/etc/five-league-reminder.env
UNIT=five-league-reminder
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ACTION=${1:-start}

fail() { printf '错误：%s\n' "$*" >&2; exit 1; }
trap 'printf "操作未完成（第 %s 行）；请处理上方错误后重试。\n" "$LINENO" >&2' ERR

case "$ACTION" in
    help|--help|-h)
        printf '%s\n' \
          '使用：sudo bash start_reminder_vps.sh [start|status|logs|stop]' \
          '默认：安装/更新依赖、保留配置和状态、启动每分钟检查及开机自启。' \
          '首次启动需要粘贴企业微信机器人 Webhook（输入隐藏）。' \
          '支持 Ubuntu 22.04+ / Debian 12+，需要 systemd。'
        exit 0 ;;
    start|status|logs|stop) ;;
    *) fail "未知操作：$ACTION；使用 help 查看帮助。" ;;
esac
[[ $# -le 1 ]] || fail '只能指定一个操作。'
[[ $(uname -s) == Linux ]] || fail '请在 Linux VPS 上运行此脚本。'
[[ $EUID -eq 0 ]] || fail "请使用 sudo bash $0 $ACTION，或以 root 用户运行。"
command -v systemctl >/dev/null && [[ -d /run/systemd/system ]] || fail '需要正在运行的 systemd，普通容器不适用。'

case "$ACTION" in
    status)
        status_code=0
        systemctl status "$UNIT.timer" --no-pager || status_code=$?
        systemctl show "$UNIT.service" -p Result -p ExecMainStatus
        exit "$status_code" ;;
    logs) exec journalctl -u "$UNIT.service" -n 60 -f ;;
    stop)
        systemctl disable --now "$UNIT.timer"
        systemctl stop "$UNIT.service"
        printf '已停止提醒，并关闭开机自启。\n'
        exit 0 ;;
esac

command -v apt-get >/dev/null || fail '自动安装只支持 Ubuntu / Debian。'
for item in five_league_reminder.py requirements.txt .env.example systemd/five-league-reminder.service systemd/five-league-reminder.timer; do
    [[ -f "$SOURCE/$item" ]] || fail "缺少 $item；请完整解压安装包后运行。"
done

# Serialize installs without changing any other application's services.
command -v flock >/dev/null || fail '缺少 flock，请先安装 util-linux。'
exec 9>/run/lock/five-league-reminder-install.lock
flock -n 9 || fail '另一个安装进程正在运行。'

if [[ ! -f "$CONFIG" ]]; then
    printf '首次配置：请粘贴企业微信机器人 Webhook（输入不会显示），然后回车：\n'
    IFS= read -r -s WEBHOOK </dev/tty || fail '无法读取输入；请通过交互式 SSH 终端执行。'
    printf '\n'
    [[ "$WEBHOOK" =~ ^https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[A-Za-z0-9_-]+$ ]] || fail 'Webhook 格式不正确，应为企业微信机器人的完整 HTTPS 地址。'
fi

printf '安装 Python 和运行依赖……\n'
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip ca-certificates tzdata
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "需要 Python 3.10+；请使用 Ubuntu 22.04+ / Debian 12+。")'
if ! getent passwd "$UNIT" >/dev/null; then
    useradd --system --user-group --home-dir "$APP" --shell /usr/sbin/nologin "$UNIT"
fi
install -d -m 755 "$APP" "$APP/systemd"
install -d -o "$UNIT" -g "$UNIT" -m 750 "$STATE"

# Pause scheduling, and let any current send finish writing its dedupe state.
if systemctl cat "$UNIT.timer" >/dev/null 2>&1; then
    systemctl stop "$UNIT.timer"
fi
if systemctl cat "$UNIT.service" >/dev/null 2>&1; then
    for ((attempt=0; attempt<120; attempt++)); do
        service_state=$(systemctl show "$UNIT.service" -p ActiveState --value)
        case "$service_state" in
            inactive|failed) break ;;
        esac
        sleep 1
    done
    [[ "$service_state" == inactive || "$service_state" == failed ]] || fail '当前检查仍未结束，已暂停定时器；请稍后重试，避免中断推送。'
fi
for item in five_league_reminder.py requirements.txt .env.example start_reminder_vps.sh systemd/five-league-reminder.service systemd/five-league-reminder.timer; do
    if [[ ! "$SOURCE/$item" -ef "$APP/$item" ]]; then
        install -m 644 "$SOURCE/$item" "$APP/$item"
    fi
done
if [[ ! -x "$APP/.venv/bin/python" ]]; then
    python3 -m venv "$APP/.venv"
fi
"$APP/.venv/bin/python" -m pip install --disable-pip-version-check -r "$APP/requirements.txt"

if [[ ! -f "$CONFIG" ]]; then
    # Shell builtins keep the secret out of command arguments and process listings.
    (umask 077
     printf 'WECOM_WEBHOOK_URL=%s\n' "$WEBHOOK" > "$CONFIG"
     sed '/^WECOM_WEBHOOK_URL=/d; /^STATE_FILE=/d; /^CACHE_FILE=/d' "$APP/.env.example" >> "$CONFIG"
     printf '\nSTATE_FILE=%s/sent.json\nCACHE_FILE=%s/schedule_cache.json\n' "$STATE" "$STATE" >> "$CONFIG")
    unset WEBHOOK
fi
chown root:root "$CONFIG"
chmod 600 "$CONFIG"

# Parse as data, never source the environment file as shell code.
STATE_TARGET=$("$APP/.venv/bin/python" - "$APP" "$CONFIG" <<'PY'
import sys
from pathlib import Path
from dotenv import dotenv_values
sys.path.insert(0, sys.argv[1])
from five_league_reminder import load_config
values = {k: v for k, v in dotenv_values(sys.argv[2], interpolate=False).items() if v is not None}
config = load_config(values)
if config.dry_run:
    raise SystemExit('配置 DRY_RUN=true，不会发送提醒；请先改为 false 后重试。')
if not config.webhook_url.startswith('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=') or '替换' in config.webhook_url:
    raise SystemExit('请在 /etc/five-league-reminder.env 配置有效 Webhook。')
for path in (config.state_file, config.cache_file):
    if not path.is_absolute():
        raise SystemExit('VPS 的 STATE_FILE 和 CACHE_FILE 必须是 Linux 绝对路径。')
print(config.state_file)
PY
)
printf '配置检查通过。\n'

# Optional, explicitly uploaded migration state. Never replace existing VPS history.
if [[ -f "$SOURCE/data/sent.json" && ! -e "$STATE_TARGET" ]]; then
    "$APP/.venv/bin/python" - "$SOURCE/data/sent.json" "$APP" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from five_league_reminder import load_sent_state
load_sent_state(Path(sys.argv[1]))
PY
    [[ -d $(dirname -- "$STATE_TARGET") ]] || fail 'STATE_FILE 的父目录不存在，请先创建并赋予服务用户写权限。'
    install -o "$UNIT" -g "$UNIT" -m 600 "$SOURCE/data/sent.json" "$STATE_TARGET"
    printf '已导入上传的去重记录。\n'
fi
install -m 644 "$APP/systemd/$UNIT.service" "/etc/systemd/system/$UNIT.service"
install -m 644 "$APP/systemd/$UNIT.timer" "/etc/systemd/system/$UNIT.timer"
systemctl daemon-reload
printf '执行首次赛程检查；进入提醒窗口的比赛将正常推送……\n'
if ! systemctl start "$UNIT.service"; then
    printf '首次检查失败，尚未开启定时器。查看：sudo journalctl -u %s.service -n 40 --no-pager\n' "$UNIT" >&2
    exit 1
fi
systemctl enable --now "$UNIT.timer"
systemctl is-active --quiet "$UNIT.timer"
printf '\n启动成功：每分钟检查、后台运行、开机自启；断开 SSH 不影响提醒。\n'
printf '查看状态：sudo bash %s/start_reminder_vps.sh status\n' "$APP"
printf '查看日志：sudo bash %s/start_reminder_vps.sh logs\n' "$APP"
printf '停止提醒：sudo bash %s/start_reminder_vps.sh stop\n' "$APP"
printf '请确保本机提醒窗口已关闭，避免两个实例重复发送。\n'
