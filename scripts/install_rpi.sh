#!/usr/bin/env bash

set -euo pipefail

SCRIPT_VERSION="1.1.8"

BOOT_CONFIG_PATH="/boot/config.txt"
BOOT_CONFIG_BACKUP=""
OS_ID="unknown"
OS_VERSION_ID=""
OS_VERSION_CODENAME=""
DEFAULT_SYSTEM_TARGET="multi-user.target"
HAS_GRAPHICAL_TARGET="false"
VIDEO_MODE=""
SDTV_MODE=""
SDL_DRIVER=""
SDL_FALLBACK_DRIVER=""
SDL_DRIVER_NOTE=""
LAUNCH_METHOD="direct"
TARGET_USER=""
TARGET_HOME=""
TARGET_UID=""
declare -a GROUPS_ADDED=()
declare -a REQUIRED_GROUPS=(
    video
    input
    render
)
FRESH_CLONE="false"
MIGRATED_CONFIG="false"
LEGACY_START_SCRIPT_DISABLED=""
LEGACY_PROFILE_BACKUP=""
NON_INTERACTIVE="false"

declare -a BASE_PACKAGES=(
    git
    curl
    python3
    python3-pip
    python3-venv
    python3-dev
    pkg-config
    build-essential
    libatlas-base-dev
    libavformat-dev
    libavcodec-dev
    libswscale-dev
    libopenjp2-7
    libjpeg-dev
    libfreetype6-dev
    libportmidi0
    libsdl2-dev
    libsdl2-image-2.0-0
    libsdl2-mixer-2.0-0
    libsdl2-ttf-2.0-0
    libudev-dev
    libdrm-dev
    libegl1-mesa
    libgbm1
    libxcb1-dev
)

declare -a DESKTOP_PACKAGES=(
    xserver-xorg
    x11-xserver-utils
    lightdm
)

declare -a HEADLESS_PACKAGES=()
declare -a XINIT_PACKAGES=(
    xserver-xorg
    x11-xserver-utils
    xinit
    kbd
)

print_banner() {
    cat <<'BANNER'
============================================================
 Sentinel CRT Raspberry Pi Installer
============================================================
BANNER
    echo "Version: ${SCRIPT_VERSION}"
    echo "This script will install Sentinel CRT and configure it to start on boot."
    echo
}

ensure_interactive_stdin() {
    if [[ -t 0 ]]; then
        return
    fi

    if [[ -e /dev/tty ]]; then
        if exec </dev/tty; then
            return
        fi
    fi

    NON_INTERACTIVE="true"
    echo "[WARN] No interactive TTY detected. Falling back to default responses."
}

detect_os_details() {
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        OS_ID=${ID:-unknown}
        OS_VERSION_ID=${VERSION_ID:-}
        OS_VERSION_CODENAME=${VERSION_CODENAME:-}
    fi

    if [[ -f /boot/firmware/config.txt ]]; then
        BOOT_CONFIG_PATH="/boot/firmware/config.txt"
    elif [[ -f /boot/config.txt ]]; then
        BOOT_CONFIG_PATH="/boot/config.txt"
    else
        echo "[WARN] Unable to locate config.txt. Creating /boot/config.txt placeholder."
        touch /boot/config.txt
        BOOT_CONFIG_PATH="/boot/config.txt"
    fi

    BOOT_CONFIG_BACKUP="${BOOT_CONFIG_PATH}.sentinel-backup"
}

detect_default_target() {
    local target
    if target=$(systemctl get-default 2>/dev/null); then
        DEFAULT_SYSTEM_TARGET=${target}
    else
        DEFAULT_SYSTEM_TARGET="multi-user.target"
    fi

    if [[ ${DEFAULT_SYSTEM_TARGET} == "graphical.target" ]]; then
        HAS_GRAPHICAL_TARGET="true"
    else
        HAS_GRAPHICAL_TARGET="false"
    fi
}

require_root() {
    if [[ $(id -u) -ne 0 ]]; then
        echo "[ERROR] This script must be run with sudo or as root." >&2
        exit 1
    fi
}

prompt_target_user() {
    local default_user="${SUDO_USER:-pi}"
    if [[ ${default_user} == "root" || -z ${default_user} ]]; then
        default_user="pi"
    fi

    local chosen_user=""
    if [[ ${NON_INTERACTIVE} == "true" ]]; then
        echo "[INFO] Defaulting installation owner to '${default_user}'."
    else
        read -rp "Enter the user that should own the installation [${default_user}]: " chosen_user || true
        if [[ -z ${chosen_user} ]]; then
            chosen_user=${default_user}
        fi
    fi

    if [[ -z ${chosen_user} ]]; then
        chosen_user=${default_user}
    fi

    if ! id -u "${chosen_user}" >/dev/null 2>&1; then
        echo "[ERROR] User '${chosen_user}' does not exist. Create the user before running this script." >&2
        exit 1
    fi

    TARGET_USER=${chosen_user}
    TARGET_HOME=$(getent passwd "${TARGET_USER}" | cut -d: -f6)
    TARGET_UID=$(id -u "${TARGET_USER}")
    if [[ -z ${TARGET_HOME} || ! -d ${TARGET_HOME} ]]; then
        echo "[ERROR] Could not determine home directory for '${TARGET_USER}'." >&2
        exit 1
    fi
}

ensure_target_user_groups() {
    local group
    for group in "${REQUIRED_GROUPS[@]}"; do
        if ! getent group "${group}" >/dev/null 2>&1; then
            continue
        fi

        if id -nG "${TARGET_USER}" | tr ' ' '\n' | grep -qx "${group}"; then
            continue
        fi

        if usermod -aG "${group}" "${TARGET_USER}"; then
            GROUPS_ADDED+=("${group}")
            echo "[INFO] Added ${TARGET_USER} to '${group}' group for display access."
        else
            echo "[WARN] Failed to add ${TARGET_USER} to '${group}' group. You may need to adjust group membership manually." >&2
        fi
    done
}

prompt_video_output() {
    if [[ ${NON_INTERACTIVE} == "true" ]]; then
        VIDEO_MODE="hdmi"
        SDTV_MODE=""
        echo "[INFO] Defaulting video output to HDMI."
        return
    fi

    echo "Select the video output for the Raspberry Pi:"
    echo "  1) HDMI / digital display"
    echo "  2) Composite (AV) output"
    local choice
    while true; do
        read -rp "Enter choice [1-2]: " choice || true
        case ${choice:-1} in
            1|"")
                VIDEO_MODE="hdmi"
                SDTV_MODE=""
                break
                ;;
            2)
                VIDEO_MODE="composite"
                prompt_sdtv_mode
                break
                ;;
            *)
                echo "Please enter 1 or 2."
                ;;
        esac
    done
}

prompt_sdtv_mode() {
    if [[ ${NON_INTERACTIVE} == "true" ]]; then
        SDTV_MODE="0"
        echo "[INFO] Defaulting composite video mode to NTSC (sdtv_mode=0)."
        return
    fi

    echo
    echo "Select the composite TV format:"
    echo "  1) NTSC (North America, 60Hz)"
    echo "  2) PAL (Europe, 50Hz)"
    local choice
    while true; do
        read -rp "Enter choice [1-2]: " choice || true
        case ${choice:-1} in
            1|"")
                SDTV_MODE="0"
                break
                ;;
            2)
                SDTV_MODE="2"
                break
                ;;
            *)
                echo "Please enter 1 or 2."
                ;;
        esac
    done
}

determine_sdl_driver() {
    SDL_FALLBACK_DRIVER=""

    if [[ ${VIDEO_MODE} == "composite" ]]; then
        SDL_DRIVER="fbcon"
        return
    fi

    if [[ ${HAS_GRAPHICAL_TARGET} == "true" ]]; then
        SDL_DRIVER="x11"
    else
        if [[ -e /dev/dri/card0 ]]; then
            SDL_DRIVER="kmsdrm"
            SDL_FALLBACK_DRIVER="fbcon"
        else
            SDL_DRIVER="fbcon"
        fi
    fi
}

sdl_driver_self_test() {
    local driver="$1"
    local venv_dir="$2"

    sudo -u "${TARGET_USER}" -H env SDL_VIDEODRIVER="${driver}" "${venv_dir}/bin/python" - <<'PY'
import sys

try:
    import pygame
    pygame.display.init()
    pygame.display.set_mode((1, 1))
except Exception as exc:
    print(exc, file=sys.stderr)
    sys.exit(1)
finally:
    try:
        pygame.display.quit()
    except Exception:
        pass
PY
}

validate_sdl_driver() {
    local install_dir="${TARGET_HOME}/sentinel-crt"
    local venv_dir="${install_dir}/venv"
    local driver="${SDL_DRIVER}"
    local fallback="${SDL_FALLBACK_DRIVER:-}"

    if [[ -z ${driver} ]]; then
        return
    fi

    if [[ ${driver} == "x11" ]]; then
        LAUNCH_METHOD="direct"
        return
    fi

    if [[ ! -x ${venv_dir}/bin/python ]]; then
        echo "[WARN] Unable to validate SDL driver; ${venv_dir}/bin/python not found."
        return
    fi

    local log_file="/tmp/sentinel-sdl-test.log"

    if sdl_driver_self_test "${driver}" "${venv_dir}" 2>"${log_file}"; then
        rm -f "${log_file}"
        LAUNCH_METHOD="direct"
        return
    fi

    SDL_DRIVER_NOTE="SDL driver '${driver}' was unavailable during validation."

    echo "[WARN] SDL driver '${driver}' failed the availability test. Details:" >&2
    sed 's/^/        /' "${log_file}" >&2 || true

    if [[ -z ${fallback} ]]; then
        echo "[WARN] No fallback SDL driver configured; switching to an xinit-managed X11 session." >&2
        SDL_DRIVER_NOTE+=" Installer will launch via xinit-managed X11 fallback."
        rm -f "${log_file}"
        SDL_DRIVER="x11"
        LAUNCH_METHOD="xinit"
        return
    fi

    echo "[INFO] Falling back to SDL driver '${fallback}'."
    SDL_DRIVER="${fallback}"
    SDL_FALLBACK_DRIVER=""

    if sdl_driver_self_test "${SDL_DRIVER}" "${venv_dir}" 2>"${log_file}"; then
        SDL_DRIVER_NOTE+=" Using fallback '${SDL_DRIVER}'."
        rm -f "${log_file}"
        LAUNCH_METHOD="direct"
        return
    fi

    echo "[WARN] Fallback SDL driver '${SDL_DRIVER}' also failed. Installation will continue with an xinit-managed X server." >&2
    SDL_DRIVER_NOTE+=" Fallback '${SDL_DRIVER}' also failed self-test; switching to xinit-managed X11." 
    sed 's/^/        /' "${log_file}" >&2 || true
    rm -f "${log_file}"

    SDL_DRIVER="x11"
    LAUNCH_METHOD="xinit"
}

select_first_available() {
    local candidate
    for candidate in "$@"; do
        if apt-cache show "${candidate}" >/dev/null 2>&1; then
            echo "${candidate}"
            return 0
        fi
    done
    return 1
}

install_if_available() {
    local pkg
    local to_install=()
    for pkg in "$@"; do
        if [[ -z ${pkg} ]]; then
            continue
        fi
        if dpkg -s "${pkg}" >/dev/null 2>&1; then
            continue
        fi
        if apt-cache show "${pkg}" >/dev/null 2>&1; then
            to_install+=("${pkg}")
        else
            echo "[WARN] Package '${pkg}' not found in apt repositories; skipping."
        fi
    done

    if [[ ${#to_install[@]} -gt 0 ]]; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y "${to_install[@]}"
    else
        echo "[INFO] All required system packages are already installed."
    fi
}

ensure_xinit_packages() {
    if [[ ${LAUNCH_METHOD} != "xinit" ]]; then
        return
    fi

    echo
    echo "[INFO] Installing minimal X11 packages for xinit fallback..."
    install_if_available "${XINIT_PACKAGES[@]}"
}

configure_xwrapper_permissions() {
    if [[ ${LAUNCH_METHOD} != "xinit" ]]; then
        return
    fi

    local wrapper_path="/etc/X11/Xwrapper.config"
    local backup_path="${wrapper_path}.sentinel-backup"
    local needs_update="false"

    mkdir -p /etc/X11

    if [[ ! -f ${wrapper_path} ]]; then
        needs_update="true"
    else
        local allowed_line
        allowed_line=$(grep -E '^allowed_users=' "${wrapper_path}" || true)
        if [[ ${allowed_line} != "allowed_users=anybody" ]]; then
            needs_update="true"
        fi

        if ! grep -qE '^needs_root_rights=' "${wrapper_path}"; then
            needs_update="true"
        fi
    fi

    if [[ ${needs_update} != "true" ]]; then
        return
    fi

    if [[ -f ${wrapper_path} && ! -f ${backup_path} ]]; then
        cp "${wrapper_path}" "${backup_path}"
        chown root:root "${backup_path}"
        chmod 0644 "${backup_path}"
    fi

    local tmp_path="${wrapper_path}.tmp"
    {
        echo "allowed_users=anybody"
        echo "needs_root_rights=yes"
        if [[ -f ${wrapper_path} ]]; then
            grep -vE '^(allowed_users|needs_root_rights)=' "${wrapper_path}" || true
        fi
    } > "${tmp_path}"

    mv "${tmp_path}" "${wrapper_path}"
    chmod 0644 "${wrapper_path}"

    echo "[INFO] Configured ${wrapper_path} to allow non-console Xorg sessions."
    if [[ -f ${backup_path} ]]; then
        echo "[INFO] Previous Xwrapper configuration backed up to ${backup_path}."
    fi
}

update_system_packages() {
    echo
    echo "[INFO] Updating apt package index..."
    apt-get update

    echo
    echo "[INFO] Installing system dependencies (this may take a while)..."
    local packages=("${BASE_PACKAGES[@]}")

    local tiff_package
    if tiff_package=$(select_first_available libtiff5 libtiff6); then
        packages+=("${tiff_package}")
    else
        echo "[WARN] Could not determine libtiff package; please install manually if required."
    fi

    if [[ ${HAS_GRAPHICAL_TARGET} == "true" ]]; then
        packages+=("${DESKTOP_PACKAGES[@]}")
    else
        packages+=("${HEADLESS_PACKAGES[@]}")
    fi

    install_if_available "${packages[@]}"
}

clone_or_update_repo() {
    INSTALL_DIR="${TARGET_HOME}/sentinel-crt"
    if [[ -d ${INSTALL_DIR} && ! -d ${INSTALL_DIR}/.git ]]; then
        local backup="${INSTALL_DIR}.backup.$(date +%s)"
        echo "[WARN] Found existing directory without Git metadata. Moving it to ${backup}."
        mv "${INSTALL_DIR}" "${backup}"
        chown -R "${TARGET_USER}:${TARGET_USER}" "${backup}" || true
    fi

    if [[ ! -d ${INSTALL_DIR}/.git ]]; then
        echo
        echo "[INFO] Cloning Sentinel CRT into ${INSTALL_DIR}..."
        sudo -u "${TARGET_USER}" -H git clone https://github.com/e2equiel/sentinel-crt.git "${INSTALL_DIR}"
        FRESH_CLONE="true"
    else
        echo
        echo "[INFO] Updating existing Sentinel CRT repository..."
        pushd "${INSTALL_DIR}" >/dev/null
        sudo -u "${TARGET_USER}" -H git pull --ff-only
        popd >/dev/null
        FRESH_CLONE="false"
    fi
}

setup_python_env() {
    INSTALL_DIR="${TARGET_HOME}/sentinel-crt"
    VENV_DIR="${INSTALL_DIR}/venv"

    if [[ ! -d ${VENV_DIR} ]]; then
        echo
        echo "[INFO] Creating Python virtual environment..."
        sudo -u "${TARGET_USER}" -H python3 -m venv "${VENV_DIR}"
    fi

    echo
    echo "[INFO] Installing Python dependencies..."
    sudo -u "${TARGET_USER}" -H "${VENV_DIR}/bin/python" -m pip install --upgrade pip
    sudo -u "${TARGET_USER}" -H "${VENV_DIR}/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

    if [[ ${FRESH_CLONE} == "true" ]]; then
        ensure_config_stub
        ensure_core_yaml_template
    fi
}

ensure_config_stub() {
    local install_dir="${TARGET_HOME}/sentinel-crt"
    local config_path="${install_dir}/config.py"

    if [[ -f ${config_path} ]]; then
        return
    fi

    cat <<'PY' > "${config_path}"
"""Sentinel CRT legacy configuration stub.

Populate CONFIG or THEME_COLORS only if you need to override values that
cannot live in the modular YAML files under ``settings/``. New installations
should prefer editing ``settings/core.yaml`` and the module/service YAML
fragments documented in ``settings/README.md``.
"""

CONFIG = {}
THEME_COLORS = {}

SENTINEL_CONFIG_STUB = True
PY

    chown "${TARGET_USER}:${TARGET_USER}" "${config_path}"
}

ensure_core_yaml_template() {
    local install_dir="${TARGET_HOME}/sentinel-crt"
    local core_yaml="${install_dir}/settings/core.yaml"

    if [[ -f ${core_yaml} ]]; then
        return
    fi

    cat <<'YAML' > "${core_yaml}"
# Sentinel CRT core settings. Replace the placeholder values with real
# credentials and coordinates for your installation.
mqtt_host: mqtt.local
mqtt_port: 1883
mqtt_user: sentinel
mqtt_password: change-me
frigate_topic: frigate/events
flight_topic: flights/overhead
mqtt_restart_topic: null
mqtt_restart_payload: restart

camera_name: front_door
camera_rtsp_url: rtsp://user:password@camera.local:554/stream
frigate_host: frigate.local
frigate_resolution: [1920, 1080]

mapbox_user: your_mapbox_user
mapbox_style_id: your_style_id
mapbox_token: pk.your_mapbox_token
map_latitude: -34.6037
map_longitude: -58.3816
map_radius_m: 15000
map_distance_rings: 3
map_radial_lines: true
flight_screen_timeout: 10
min_flight_altitude_ft: 1000
YAML

    chown "${TARGET_USER}:${TARGET_USER}" "${core_yaml}"
}

maybe_migrate_legacy_config() {
    local install_dir="${TARGET_HOME}/sentinel-crt"
    local venv_dir="${install_dir}/venv"
    local config_py="${install_dir}/config.py"
    local core_yaml="${install_dir}/settings/core.yaml"

    if [[ ! -f ${config_py} ]]; then
        return
    fi

    if grep -q "SENTINEL_CONFIG_STUB" "${config_py}"; then
        return
    fi

    if [[ -f ${core_yaml} ]]; then
        echo "[INFO] Detected config.py but modular settings already exist; skipping migration."
        return
    fi

    echo
    echo "[INFO] Migrating legacy config.py to modular YAML settings..."
    sudo -u "${TARGET_USER}" -H bash -c "cd '${install_dir}' && '${venv_dir}/bin/python' -m sentinel.tools.migrate_config --output settings"
    MIGRATED_CONFIG="true"
}

configure_boot_config() {
    local boot_config="${BOOT_CONFIG_PATH}"
    local backup="${BOOT_CONFIG_BACKUP}"
    local marker_start="# --- Sentinel CRT video configuration ---"
    local marker_end="# --- End Sentinel CRT video configuration ---"

    if [[ -n ${boot_config} && ! -f ${backup} ]]; then
        echo
        echo "[INFO] Backing up ${boot_config} to ${backup}"
        cp "${boot_config}" "${backup}"
    fi

    if grep -q "${marker_start}" "${boot_config}"; then
        echo "[INFO] Removing existing Sentinel CRT video configuration block..."
        sed -i "/${marker_start}/,/${marker_end}/d" "${boot_config}"
    fi

    if [[ ${VIDEO_MODE} == "composite" ]]; then
        cat <<EOF >> "${boot_config}"
${marker_start}
enable_tvout=1
sdtv_mode=${SDTV_MODE}
sdtv_aspect=1
# Reduce GPU memory usage for lightweight UI rendering
gpu_mem=128
${marker_end}
EOF
        echo "[INFO] Composite video output configured (sdtv_mode=${SDTV_MODE})."
    else
        cat <<EOF >> "${boot_config}"
${marker_start}
# HDMI mode selected. Composite output disabled.
disable_audio_dither=1
${marker_end}
EOF
        echo "[INFO] HDMI output configured."
    fi
}

create_systemd_service() {
    local service_path="/etc/systemd/system/sentinel-crt.service"
    local install_dir="${TARGET_HOME}/sentinel-crt"
    local venv_dir="${install_dir}/venv"
    local wanted_target="multi-user.target"
    local exec_start="${venv_dir}/bin/python ${install_dir}/sentinel_crt.py --fullscreen"
    local user_uid="${TARGET_UID}"
    if [[ -z ${user_uid} ]]; then
        user_uid=$(id -u "${TARGET_USER}")
    fi
    local runtime_dir="/run/user/${user_uid}"

    if [[ ${HAS_GRAPHICAL_TARGET} == "true" ]]; then
        wanted_target="graphical.target"
    fi

    if [[ ${LAUNCH_METHOD} == "xinit" ]]; then
        local vt_number="7"
        exec_start="/usr/bin/xinit ${install_dir}/scripts/run_via_xinit.sh -- :0 vt${vt_number} -nolisten tcp"
    fi

    {
        echo "[Unit]"
        echo "Description=Sentinel CRT Display"
        echo "After=network-online.target systemd-logind.service"
        echo "Wants=network-online.target"
        echo
        echo "[Service]"
        echo "Type=simple"
        echo "User=${TARGET_USER}"
        echo "WorkingDirectory=${install_dir}"
        echo "PermissionsStartOnly=true"
        printf 'Environment=PYTHONUNBUFFERED=1\n'
        printf 'Environment=XDG_RUNTIME_DIR=%s\n' "${runtime_dir}"
        if [[ -n ${SDL_DRIVER} ]]; then
            printf 'Environment=SDL_VIDEODRIVER=%s\n' "${SDL_DRIVER}"
            if [[ ${SDL_DRIVER} == "fbcon" ]]; then
                printf 'Environment=SDL_FBDEV=/dev/fb0\n'
            fi
            if [[ ${SDL_DRIVER} == "x11" ]]; then
                printf 'Environment=DISPLAY=:0\n'
            fi
        fi
        printf 'ExecStartPre=/bin/mkdir -p %s\n' "${runtime_dir}"
        printf 'ExecStartPre=/bin/chown %s:%s %s\n' "${TARGET_USER}" "${TARGET_USER}" "${runtime_dir}"
        echo "ExecStart=${exec_start}"
        echo "Restart=on-failure"
        echo "RestartSec=5"
        echo
        echo "[Install]"
        echo "WantedBy=${wanted_target}"
    } > "${service_path}"

    chmod 0644 "${service_path}"

    echo
    echo "[INFO] Reloading systemd configuration..."
    systemctl daemon-reload
    systemctl enable sentinel-crt.service
}

disable_legacy_autostart() {
    local start_script="${TARGET_HOME}/start.sh"
    local profile_path="${TARGET_HOME}/.bash_profile"

    if [[ -f ${start_script} ]] && grep -q "sentinel-crt" "${start_script}"; then
        local disabled_path="${start_script}.disabled"
        if [[ ! -f ${disabled_path} ]]; then
            mv "${start_script}" "${disabled_path}"
            chown "${TARGET_USER}:${TARGET_USER}" "${disabled_path}"
        fi
        LEGACY_START_SCRIPT_DISABLED="${disabled_path}"
        echo "[INFO] Disabled legacy start script at ${disabled_path}."
    fi

    if [[ -f ${profile_path} ]] && grep -qE "sentinel-crt|start\\.sh|sentinel_crt\\.py|xinit" "${profile_path}"; then
        LEGACY_PROFILE_BACKUP="${profile_path}.sentinel-backup"
        if [[ ! -f ${LEGACY_PROFILE_BACKUP} ]]; then
            cp "${profile_path}" "${LEGACY_PROFILE_BACKUP}"
            chown "${TARGET_USER}:${TARGET_USER}" "${LEGACY_PROFILE_BACKUP}"
        fi

        # Comment individual lines that invoke the legacy launcher while leaving the surrounding
        # shell logic intact so login shells still work normally.
        python3 - <<'PY' "${profile_path}"
import sys
from pathlib import Path

profile_path = Path(sys.argv[1])
patterns = ("sentinel-crt", "start.sh", "sentinel_crt.py", "xinit")

lines = profile_path.read_text().splitlines()
output = []
for line in lines:
    stripped = line.lstrip()
    if stripped.startswith('#'):
        output.append(line)
        continue

    if any(pat in line for pat in patterns):
        output.append(f"# SENTINEL-CRT DISABLED: {line}" if not line.startswith('#') else line)
    else:
        output.append(line)

profile_path.write_text("\n".join(output) + "\n")
PY

        chown "${TARGET_USER}:${TARGET_USER}" "${profile_path}"

        echo "[INFO] Commented legacy auto-start entries in ${profile_path}."
    fi
}

maybe_start_service() {
    echo
    local start_choice=""
    if [[ ${NON_INTERACTIVE} == "true" ]]; then
        start_choice="Y"
    else
        read -rp "Would you like to start Sentinel CRT now? [Y/n]: " start_choice || true
    fi
    case ${start_choice:-Y} in
        [Yy]*)
            if systemctl start sentinel-crt.service; then
                echo "[INFO] Sentinel CRT service started."
            else
                echo "[WARN] Failed to start Sentinel CRT service. Check 'sudo systemctl status sentinel-crt.service' for details." >&2
            fi
            ;;
        *)
            echo "[INFO] Skipping service start. You can start it later with: sudo systemctl start sentinel-crt.service"
            ;;
    esac
}

print_post_install_notes() {
    cat <<EOF

============================================================
 Installation complete!
============================================================
- Repository: ${TARGET_HOME}/sentinel-crt
- Virtualenv: ${TARGET_HOME}/sentinel-crt/venv
- Systemd unit: sentinel-crt.service
- SDL video driver: ${SDL_DRIVER}
- Launch method: ${LAUNCH_METHOD}
- Raspberry Pi OS: ${OS_ID} ${OS_VERSION_ID} (${OS_VERSION_CODENAME:-unknown})
- Boot config: ${BOOT_CONFIG_PATH}
- Default boot target: ${DEFAULT_SYSTEM_TARGET}

EOF

    if [[ -n ${SDL_DRIVER_NOTE} ]]; then
        echo "- SDL driver note: ${SDL_DRIVER_NOTE}"
    fi

    if [[ ${#GROUPS_ADDED[@]} -gt 0 ]]; then
        local joined_groups=""
        printf -v joined_groups '%s, ' "${GROUPS_ADDED[@]}"
        joined_groups=${joined_groups%, }
        echo "- Added ${TARGET_USER} to groups: ${joined_groups}"
    fi

    cat <<EOF

Next steps:
1. Update ${TARGET_HOME}/sentinel-crt/settings/core.yaml with your MQTT credentials,
   Frigate details, and Mapbox token. Additional modules/services can be configured
   via YAML fragments—see settings/README.md for guidance. Secrets that must stay
   out of YAML files can still live in config.py.
2. Restart the service once configuration is complete:
   sudo systemctl restart sentinel-crt.service
3. To check logs:
   sudo journalctl -u sentinel-crt.service -f

EOF

    if [[ ${MIGRATED_CONFIG} == "true" ]]; then
        echo "- A legacy config.py was migrated into settings/*.yaml. Review the generated files before deleting config.py."
    fi

    if [[ -n ${LEGACY_START_SCRIPT_DISABLED} ]]; then
        echo "- Legacy start script disabled: ${LEGACY_START_SCRIPT_DISABLED}"
    fi

    if [[ -n ${LEGACY_PROFILE_BACKUP} ]]; then
        echo "- Legacy .bash_profile entries were commented out. Backup saved at ${LEGACY_PROFILE_BACKUP}."
    fi

    cat <<'EOF'

If you ever need to rerun the installer, it is safe to do so; it will update the repository
and dependencies while preserving your YAML settings and config.py stub.
EOF
}

main() {
    print_banner
    require_root
    ensure_interactive_stdin
    detect_os_details
    detect_default_target
    prompt_target_user
    ensure_target_user_groups
    prompt_video_output
    determine_sdl_driver
    update_system_packages
    clone_or_update_repo
    setup_python_env
    validate_sdl_driver
    ensure_xinit_packages
    configure_xwrapper_permissions
    maybe_migrate_legacy_config
    disable_legacy_autostart
    configure_boot_config
    create_systemd_service
    maybe_start_service
    print_post_install_notes
}

main "$@"
