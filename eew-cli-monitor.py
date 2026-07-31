import requests
import time
import sys
import os
import winsound
import ctypes
import random
import json
import threading
import socket
import csv
import re
import math
import subprocess
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text
from rich.prompt import Prompt
from rich.panel import Panel

from geo import geo_ascii

try:
    import msvcrt
    WINDOWS = True
except ImportError:
    WINDOWS = False

DEBUG = False

try:
    import websocket
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False
    print("[警告] websocket-client 未安装，WebSocket 数据源将无法连接")


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


SOUND_ALERT = resource_path("sounds/alert.wav")
SOUND_COUNTDOWN = resource_path("sounds/countdown.wav")
SOUND_EEW0 = resource_path("sounds/EEW0.wav")
SOUND_EEW1 = resource_path("sounds/EEW1.wav")
SOUND_EEW2 = resource_path("sounds/EEW2.wav")


from ctypes import (
    Structure, POINTER, byref, cast, c_float, c_void_p, c_long,
    windll, CFUNCTYPE
)
from ctypes.wintypes import DWORD, WORD, BYTE, LPVOID, BOOL


class GUID(Structure):
    _fields_ = [('Data1', DWORD), ('Data2', WORD), ('Data3', WORD),
                ('Data4', BYTE * 8)]


CLSID_MMDeviceEnumerator = GUID(
    0xBCDE0395, 0xE52F, 0x467C,
    (BYTE * 8)(0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69, 0x2E))
IID_IMMDeviceEnumerator = GUID(
    0xA95664D2, 0x9614, 0x4F35,
    (BYTE * 8)(0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6))
IID_IAudioEndpointVolume = GUID(
    0x5CDF2C82, 0x841E, 0x4546,
    (BYTE * 8)(0x97, 0x22, 0x0C, 0xF7, 0x40, 0x78, 0x22, 0x9A))


QueryInterfaceFunc = CFUNCTYPE(c_long, LPVOID, POINTER(GUID), POINTER(LPVOID))
ReleaseFunc = CFUNCTYPE(c_void_p, LPVOID)
GetDefaultAudioEndpointFunc = CFUNCTYPE(c_long, LPVOID, DWORD, DWORD, POINTER(LPVOID))
ActivateFunc = CFUNCTYPE(c_long, LPVOID, POINTER(GUID), DWORD, POINTER(LPVOID), POINTER(LPVOID))
GetScalarFunc = CFUNCTYPE(c_long, LPVOID, POINTER(c_float))
SetScalarFunc = CFUNCTYPE(c_long, LPVOID, c_float, POINTER(GUID))
GetMuteFunc = CFUNCTYPE(c_long, LPVOID, POINTER(BOOL))
SetMuteFunc = CFUNCTYPE(c_long, LPVOID, BOOL, POINTER(GUID))

_SavedVolume = None
_SavedMuteState = None
_EndpointVolume = None


def _init_audio():
    global _EndpointVolume
    if _EndpointVolume is not None:
        return True
    try:
        hr = windll.ole32.CoInitializeEx(None, 0)
        if hr not in (0, 1):
            return False

        enum_ptr = LPVOID()
        hr = windll.ole32.CoCreateInstance(
            byref(CLSID_MMDeviceEnumerator), None, 1,
            byref(IID_IMMDeviceEnumerator), byref(enum_ptr))
        if hr != 0:
            return False

        enum_vtbl = cast(enum_ptr, POINTER(POINTER(c_void_p)))[0]
        get_default = GetDefaultAudioEndpointFunc(enum_vtbl[4])
        device_ptr = LPVOID()
        hr = get_default(enum_ptr, 0, 1, byref(device_ptr))
        if hr != 0:
            ReleaseFunc(enum_vtbl[2])(enum_ptr)
            return False

        dev_vtbl = cast(device_ptr, POINTER(POINTER(c_void_p)))[0]
        activate = ActivateFunc(dev_vtbl[3])
        epv_ptr = LPVOID()
        hr = activate(device_ptr, byref(IID_IAudioEndpointVolume), 0, None, byref(epv_ptr))
        if hr != 0:
            ReleaseFunc(dev_vtbl[2])(device_ptr)
            ReleaseFunc(enum_vtbl[2])(enum_ptr)
            return False

        ReleaseFunc(dev_vtbl[2])(device_ptr)
        ReleaseFunc(enum_vtbl[2])(enum_ptr)
        _EndpointVolume = epv_ptr
        return True
    except Exception:
        return False


def _save_volume():
    global _SavedVolume, _SavedMuteState
    if not _init_audio():
        _SavedVolume = _SavedMuteState = None
        return
    try:
        vtbl = cast(_EndpointVolume, POINTER(POINTER(c_void_p)))[0]
        get_scalar = GetScalarFunc(vtbl[9])
        vol = c_float()
        hr = get_scalar(_EndpointVolume, byref(vol))
        _SavedVolume = vol.value if hr == 0 else None
        get_mute = GetMuteFunc(vtbl[16])
        muted = BOOL()
        hr = get_mute(_EndpointVolume, byref(muted))
        _SavedMuteState = bool(muted.value) if hr == 0 else None
    except Exception:
        _SavedVolume = _SavedMuteState = None


def _set_max_volume():
    if not _init_audio():
        return
    try:
        vtbl = cast(_EndpointVolume, POINTER(POINTER(c_void_p)))[0]
        SetScalarFunc(vtbl[7])(_EndpointVolume, 1.0, None)

        # 检查是否静音，如果静音则尝试取消
        muted = BOOL()
        GetMuteFunc(vtbl[16])(_EndpointVolume, byref(muted))
        if muted.value:
            # Method 1: IAudioEndpointVolume::SetMute
            SetMuteFunc(vtbl[15])(_EndpointVolume, 0, None)

            # 验证是否取消成功
            muted2 = BOOL()
            GetMuteFunc(vtbl[16])(_EndpointVolume, byref(muted2))
            if muted2.value and DEBUG:
                console.print("[dim][DEBUG] 无法取消系统静音（当前音频设备不支持）[/dim]")
    except Exception:
        pass


def _restore_volume():
    global _SavedMuteState
    if _SavedVolume is None or not _init_audio():
        return
    try:
        vtbl = cast(_EndpointVolume, POINTER(POINTER(c_void_p)))[0]
        set_scalar = SetScalarFunc(vtbl[7])
        set_scalar(_EndpointVolume, _SavedVolume, None)
        if _SavedMuteState is not None:
            set_mute = SetMuteFunc(vtbl[15])
            set_mute(_EndpointVolume, BOOL(_SavedMuteState), None)
    except Exception:
        pass


def play_sound(file_path, sync=False):
    if not os.path.exists(file_path):
        return
    try:
        flags = winsound.SND_FILENAME | (0 if sync else winsound.SND_ASYNC)
        winsound.PlaySound(file_path, flags)
        if DEBUG:
            console.print(f"[dim][DEBUG] 播放音效: {os.path.basename(file_path)}[/dim]")
    except Exception:
        pass


def is_high_intensity(intensity_str):
    if not intensity_str:
        return False
    s = intensity_str.strip().lower()
    if s == '7':
        return True
    if s.startswith('6'):
        high_patterns = ['弱', '-', 'lower', '强', '+', 'upper', '強']
        for pat in high_patterns:
            if pat in s:
                return True
    return False


def safe_get(dic, *keys, default='N/A'):
    for key in keys:
        val = dic.get(key)
        if val is not None:
            if isinstance(val, str):
                return val
            return val
    return default


def to_roman(num):
    """将数字（1~12）转换为罗马数字"""
    if num is None:
        return 'N/A'
    try:
        n = int(round(float(num)))
        if n < 1 or n > 12:
            return str(n)
        roman_map = {
            1: 'I', 2: 'II', 3: 'III', 4: 'IV', 5: 'V',
            6: 'VI', 7: 'VII', 8: 'VIII', 9: 'IX',
            10: 'X', 11: 'XI', 12: 'XII'
        }
        return roman_map.get(n, str(n))
    except:
        return str(num)


def estimate_intensity(magnitude, depth_km, output_type='number'):
    try:
        if magnitude is None or magnitude == 'N/A' or magnitude == '':
            return 'N/A'
        M = float(magnitude)
        if depth_km and depth_km != 'N/A':
            if isinstance(depth_km, str):
                match = re.search(r'(\d+\.?\d*)', depth_km)
                d = float(match.group(1)) if match else 15.0
            else:
                d = float(depth_km)
        else:
            d = 15.0
        intensity = M + 1.5 - 0.05 * d
        if intensity < 1:
            intensity = 1
        elif intensity > 12:
            intensity = 12
        if output_type == 'roman':
            return f"{to_roman(intensity)}(估算)"
        else:
            return f"{round(intensity, 1)}度(估算)"
    except:
        return 'N/A'


def get_intensity_display(data, source_type=None):
    official = safe_get(data, 'epiIntensity', 'maxIntensity', 'MaxIntensity')
    if official != 'N/A' and official not in (None, '', '未知'):
        return official
    mag = safe_get(data, 'magnitude', 'Magunitude')
    depth = safe_get(data, 'depth', 'Depth')
    if source_type in ('jma', 'nied', 'p2p', 'p2pjson'):
        return estimate_intensity(mag, depth, 'number')
    else:
        return estimate_intensity(mag, depth, 'roman')


# ================== 用户位置 / 距离 / 烈度 / 波到着 工具函数 ==================

def haversine(lat1, lon1, lat2, lon2):
    try:
        lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
        radius = 6378.137
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return radius * c
    except Exception:
        return None


def estimate_local_intensity(magnitude, distance_km):
    try:
        M = float(magnitude)
        D = float(distance_km)
        if M <= 0 or D < 0:
            return 0.0
        intensity = 1.363 * M + 2.941 - 1.494 * math.log(D + 7.0)
        return round(max(intensity, 0.0), 1)
    except Exception:
        return None


def calc_wave_arrival(distance_km):
    try:
        d = float(distance_km)
        p_sec = d / 6.0
        s_sec = d / 3.5
        return (round(p_sec), round(s_sec))
    except Exception:
        return (None, None)


def add_location_rows(rows, lat, lon, mag):
    if USER_LATITUDE is None or USER_LONGITUDE is None:
        return False
    if not lat or not lon or not mag:
        return False
    dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE)
    if dist is None:
        return False
    loc_name = USER_LOCATION_NAME or f"{USER_LATITUDE},{USER_LONGITUDE}"
    rows.append(["到达距离", f"{dist:.0f}km (距{loc_name})"])

    intensity = estimate_local_intensity(mag, dist)
    if intensity is not None:
        if intensity > 0:
            rows.append(["本地烈度(估值)", f"{intensity}度"])
        else:
            rows.append(["本地烈度(估值)", "无感"])

    p_sec, s_sec = calc_wave_arrival(dist)
    mag_num = None
    try:
        mag_num = float(mag)
    except (TypeError, ValueError):
        pass
    is_no_sense = (NO_SENSATION_REPORT and intensity is not None and intensity <= 0
                   and mag_num is not None and mag_num >= NO_SENSATION_MAG_THRESHOLD)
    if p_sec is not None:
        p_label = "P波传播时间" if is_no_sense else "P波到达"
        rows.append([p_label, f"{p_sec}秒"])
    if s_sec is not None:
        s_label = "S波传播时间" if is_no_sense else "S波到达"
        rows.append([s_label, f"{s_sec}秒"])

    show_epicenter_map(lat, lon, mag)
    return True


def _in_china(lon, lat):
    xmin, ymin, xmax, ymax = geo_ascii.CHINA_BBOX
    return xmin <= lon <= xmax and ymin <= lat <= ymax

def _colorize_world(ascii_str, mag=None, epi_lat=None, epi_lon=None):
    t = Text()
    bbox = geo_ascii.WORLD_BBOX
    pixel_w = geo_ascii.WORLD_WIDTH
    pixel_h = geo_ascii.WORLD_HEIGHT
    x_min, y_min, x_max, y_max = bbox
    cell_size = (x_max - x_min) / pixel_w
    for row, line in enumerate(ascii_str.splitlines()):
        for tc, ch in enumerate(line):
            if ch == '#':
                if mag and epi_lat is not None and epi_lon is not None:
                    pixel_col = tc // 2
                    char_lon = x_min + (pixel_col + 0.5) * cell_size
                    char_lat = y_max - (row + 0.5) * cell_size
                    dist = haversine(epi_lat, epi_lon, char_lat, char_lon)
                    if dist is not None:
                        intensity = estimate_local_intensity(mag, dist)
                        if intensity is not None and intensity > 0:
                            style = _intensity_style(intensity)
                            if style:
                                t.append(str(int(round(intensity))), style=style)
                                continue
                t.append('#', style='grey54')
            elif ch == '*':
                t.append('*', style='bold white on red')
            elif ch == '@':
                t.append('@', style='bold white on green')
            else:
                t.append(ch, style='dim' if ch.strip() else '')
        t.append('\n')
    return t

def _colorize_china_with_intensity(epi_lon, epi_lat, mon_lon, mon_lat, mag=None):
    rows = [list(r) for r in geo_ascii.CHINA_COLORED.splitlines()]
    ph = len(rows)
    for lon, lat, ch in [(epi_lon, epi_lat, '*'), (mon_lon, mon_lat, '@')]:
        r, c = geo_ascii.lonlat_to_rc(lon, lat, geo_ascii.CHINA_BBOX, geo_ascii.MAP_WIDTH, ph)
        tc = c * 2
        if 0 <= r < ph and 0 <= tc < len(rows[r]):
            rows[r][tc] = ch
    bbox = geo_ascii.CHINA_BBOX
    pixel_w = geo_ascii.MAP_WIDTH
    pixel_h = ph
    x_min, y_min, x_max, y_max = bbox
    cell_size = (x_max - x_min) / pixel_w
    t = Text()
    for row, line in enumerate(rows):
        for tc, ch in enumerate(line):
            if ch == '*':
                t.append('*', style='bold white on red')
            elif ch == '@':
                t.append('@', style='bold white on green')
            elif ch == ' ':
                t.append(' ', style='')
            elif mag and epi_lat is not None and epi_lon is not None:
                pixel_col = tc // 2
                char_lon = x_min + (pixel_col + 0.5) * cell_size
                char_lat = y_max - (row + 0.5) * cell_size
                dist = haversine(epi_lat, epi_lon, char_lat, char_lon)
                if dist is not None:
                    intensity = estimate_local_intensity(mag, dist)
                    if intensity is not None and intensity > 0:
                        style = _intensity_style(intensity)
                        if style:
                            t.append(str(int(round(intensity))), style=style)
                            continue
                if ch in geo_ascii.CHINA_COLORMAP:
                    t.append(ch, style=geo_ascii.CHINA_COLORMAP[ch])
                else:
                    t.append(ch, style='dim')
            else:
                if ch in geo_ascii.CHINA_COLORMAP:
                    t.append(ch, style=geo_ascii.CHINA_COLORMAP[ch])
                else:
                    t.append(ch, style='dim')
        t.append('\n')
    return t


def show_epicenter_map(lat, lon, mag=None):
    if not lat or not lon:
        return
    try:
        lon_f = float(lon)
        lat_f = float(lat)
        try:
            mag_f = float(mag) if mag and str(mag).strip() not in ('N/A', '', 'None') else None
        except (ValueError, TypeError):
            mag_f = None
        mon_lon = USER_LONGITUDE if USER_LATITUDE is not None else None
        mon_lat = USER_LATITUDE if USER_LONGITUDE is not None else None

        # World map — markers + intensity-colored land
        console.print("[bold cyan] (*震中 @监控点)[/bold cyan]")
        points = [(lon_f, lat_f, '*')]
        if mon_lon is not None and mon_lat is not None:
            points.append((mon_lon, mon_lat, '@'))
        world_mapped = geo_ascii.plot_on_map(
            geo_ascii.WORLD_MAP, geo_ascii.WORLD_BBOX,
            geo_ascii.WORLD_WIDTH, geo_ascii.WORLD_HEIGHT, points
        )
        console.print(_colorize_world(world_mapped, mag_f, lat_f, lon_f))

        # China map — intensity-colored provinces, only if epicenter in China
        if _in_china(lon_f, lat_f) and mon_lon is not None and mon_lat is not None:
            china_t = _colorize_china_with_intensity(lon_f, lat_f, mon_lon, mon_lat, mag_f)
            console.print("[bold cyan] (*震中 @监控点)[/bold cyan]")
            console.print(china_t)
    except Exception:
        pass


# ================== P/S波动态倒计时 ==================

def _parse_origin_time(time_str):
    if not time_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(time_str, fmt).timestamp()
        except ValueError:
            continue
    try:
        return float(time_str) / 1000
    except (ValueError, TypeError):
        pass
    return None


def _countdown_worker():
    while True:
        time.sleep(1)
        with _countdown_lock:
            if not _countdown_active:
                continue
            now = time.time()
            parts = []
            finished = []
            for eid, info in _countdown_active.items():
                elapsed = now - info['start_time']
                p_rem = info['p_seconds'] - elapsed
                s_rem = info['s_seconds'] - elapsed
                loc = info.get('user_loc', '')
                oname = info.get('origin_name', '未知')
                mag = info.get('magnitude', '?')
                dkm = info.get('distance_km', 0)
                inten = info.get('intensity', 0)
                prefix = f"{oname}M{mag}级 {dkm:.0f}km 预估烈度{inten}度 "
                if s_rem <= 0:
                    parts.append(f"[{prefix}S波已抵达]{loc}")
                    finished.append(eid)
                elif p_rem <= 0:
                    parts.append(f"[{oname}M{mag}级 P波已抵达 | S波 {int(s_rem)}秒]{loc}")
                else:
                    parts.append(f"[{prefix}P波 {int(p_rem)}秒 | S波 {int(s_rem)}秒]{loc}")
            for eid in finished:
                del _countdown_active[eid]
            if parts:
                sys.stdout.write('\r' + ' | '.join(parts))
                sys.stdout.flush()


def start_countdown(event_id, origin_time_str, distance_km, user_loc, magnitude, origin_name=''):
    if USER_LATITUDE is None or USER_LONGITUDE is None:
        return
    if distance_km is None or distance_km <= 0:
        return
    intensity = estimate_local_intensity(magnitude, distance_km)
    if intensity is None or intensity <= 0:
        return
    global _countdown_thread
    p_sec, s_sec = calc_wave_arrival(distance_km)
    if p_sec is None:
        return
    start_ts = _parse_origin_time(origin_time_str)
    if start_ts is None:
        start_ts = time.time()
    with _countdown_lock:
        if event_id in _countdown_active:
            return
        _countdown_active[event_id] = {
            'p_seconds': p_sec,
            's_seconds': s_sec,
            'start_time': start_ts,
            'user_loc': user_loc or USER_LOCATION_NAME or '',
            'origin_name': origin_name or '未知',
            'magnitude': magnitude,
            'distance_km': distance_km,
            'intensity': intensity,
        }
    if _countdown_thread is None or not _countdown_thread.is_alive():
        _countdown_thread = threading.Thread(target=_countdown_worker, daemon=True)
        _countdown_thread.start()


# ================== 预警通知系统 ==================

def get_alert_tier(intensity, tiers=None):
    if intensity is None:
        return None
    if tiers is None:
        tiers = ALERT_TIERS
    if intensity == 0:
        return 0
    t1 = tiers.get('tier1', {})
    if t1 and t1.get('min', 1.0) <= intensity < t1.get('max', 2.0):
        return 1
    t2 = tiers.get('tier2', {})
    if t2 and t2.get('min', 2.0) <= intensity < t2.get('max', 3.0):
        return 2
    t3 = tiers.get('tier3', {})
    if t3 and intensity >= t3.get('min', 3.0):
        return 3
    if intensity > 0:
        return -1
    return None


def send_bark(title, subtitle, body, level='passive', **extras):
    url = ALERT_BARK_URL
    if not url:
        return False
    payload = {
        'title': title,
        'subtitle': subtitle,
        'body': body,
        'group': '灾害预警-CLI',
        'level': level,
    }
    payload.update(extras)
    try:
        resp = requests.post(url, json=payload, timeout=5)
        if DEBUG:
            console.print(f"[dim][DEBUG] Bark推送结果: HTTP {resp.status_code}[/dim]")
        return resp.ok
    except Exception as e:
        if DEBUG:
            console.print(f"[dim][DEBUG] Bark推送失败: {e}[/dim]")
        return False


def show_windows_notification(title, message):
    if not WINDOWS:
        return False
    try:
        ps = f'''
$title = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName("text")
$textNodes.Item(0).AppendChild($template.CreateTextNode("{title}")) > $null
$textNodes.Item(1).AppendChild($template.CreateTextNode("{message}")) > $null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("EEW-CLI-Monitor").Show($toast)
'''
        subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=10)
        return True
    except Exception as e:
        if DEBUG:
            console.print(f"[dim][DEBUG] Windows通知失败: {e}[/dim]")
        return False


# def bark_countdown_loop(event_id, initial_seconds, title_base, subtitle, body_source, level, **extras):
#     for remaining in range(initial_seconds, -1, -1):
#         if BARK_COUNTDOWN_THREADS.get(event_id) != threading.current_thread():
#             return
#         body = f"预计 {remaining}秒后到达 {body_source}"
#         send_bark(
#             title=f"{title_base} {remaining}秒后到达",
#             subtitle=subtitle,
#             body=body,
#             level=level,
#             **extras
#         )
#         time.sleep(1)
#     BARK_COUNTDOWN_THREADS.pop(event_id, None)


def trigger_alert(source_label, origin_name, magnitude, depth,
                  distance_km, local_intensity, max_intensity,
                  origin_time, p_seconds, s_seconds, event_id):
    loc_name = USER_LOCATION_NAME or f"{USER_LATITUDE},{USER_LONGITUDE}"
    tier = get_alert_tier(local_intensity)
    tiers_config = ALERT_TIERS

    # 音效
    if tier == 0:
        play_sound(SOUND_COUNTDOWN)
    elif tier is None or tier == -1:
        play_sound(SOUND_ALERT)
    elif tier == 1:
        _save_volume()
        _set_max_volume()
        play_sound(SOUND_EEW0, sync=True)
        _restore_volume()
    elif tier == 2:
        _save_volume()
        _set_max_volume()
        play_sound(SOUND_EEW1, sync=True)
        _restore_volume()
    elif tier == 3:
        _save_volume()
        _set_max_volume()
        play_sound(SOUND_EEW2, sync=True)
        _restore_volume()

    # Windows通知
    mag_num = None
    try:
        mag_num = float(magnitude)
    except (TypeError, ValueError):
        pass
    no_sense = (local_intensity is not None and local_intensity == 0
                and mag_num is not None and mag_num >= NO_SENSATION_MAG_THRESHOLD)
    if no_sense and not NO_SENSATION_REPORT:
        pass
    elif no_sense and NO_SENSATION_REPORT:
        win_msg = (f"{origin_time} {origin_name} 深度{depth}km M{magnitude}级\n"
                   f"P波传播时间 {p_seconds}秒 | S波传播时间 {s_seconds}秒\n"
                   f"距离{distance_km:.0f}km (距{loc_name})，订阅位置预估烈度0\n"
                   f"信号源: {source_label}")
        show_windows_notification("无感地震通报", win_msg)
    else:
        win_msg = (f"{origin_time} {origin_name} 深度{depth}km M{magnitude}级 烈度{local_intensity}\n"
                   f"P波 {p_seconds}秒后到达 | S波 {s_seconds}秒后到达\n"
                   f"到达{loc_name}距离{distance_km:.0f}km，订阅位置预估烈度{local_intensity}\n"
                   f"信号源: {source_label}")
        show_windows_notification(f"地震预警预计烈度{local_intensity}", win_msg)

    # Bark
    if no_sense and not NO_SENSATION_REPORT:
        pass
    elif no_sense and NO_SENSATION_REPORT:
        if ALERT_BARK_URL:
            send_bark(
                title="无感地震通报",
                subtitle=f"震级 M{magnitude} 深度 {depth}km，距离{distance_km:.0f}km, {loc_name}预估烈度 0",
                body=f"距离震中 {distance_km:.0f}km，P波传播时间 {p_seconds}秒 | S波传播时间 {s_seconds}秒，信号源: {source_label}",
                level="passive"
            )
    else:
        tier_cfg = tiers_config.get(f'tier{tier}', {}) if tier is not None and tier > 0 else {}
        bark_enabled = tier_cfg.get('bark', True) if tier is not None and tier > 0 else True
        if ALERT_BARK_URL and bark_enabled:
            title_base = f"地震预警 {origin_name}"
            if tier is None or tier == -1 or tier == 0:
                send_bark(
                    title=f"{title_base} {s_seconds}秒后到达",
                    subtitle=f"震级 M{magnitude} 深度 {depth}km，距离{distance_km:.0f}km, {loc_name}预估烈度 {local_intensity}",
                    body=f"距离震中 {distance_km:.0f}km，S波预计 {s_seconds}秒后到达，信号源: {source_label}",
                    level="passive"
                )
            elif tier == 1:
                send_bark(
                    title=f"{title_base} {s_seconds}秒后到达",
                    subtitle=f"震级 M{magnitude} 深度 {depth}km，距离{distance_km:.0f}km, {loc_name}预估烈度 {local_intensity}",
                    body=f"S波预计 {s_seconds}秒后到达 信号源: {source_label}",
                    level="active"
                )
            elif tier >= 2:
                send_bark(
                    title=f"{title_base} {s_seconds}秒后到达",
                    subtitle=f"震级 M{magnitude} 深度 {depth}km，距离{distance_km:.0f}km, {loc_name}预估烈度 {local_intensity}",
                    body=f"S波预计 {s_seconds}秒后到达 信号源: {source_label}",
                    level="critical",
                    volume=10, call="1", sound="alarm"
                )


# ================== 配置文件路径（持久化） ==================
CONFIG_FILE = "config.json"


def build_default_config():
    config = {
        'sources': {},
        'filters': {key: dict(val) for key, val in FILTER_DETAIL.items()},
        'export_path': None,
        'debug': False,
        'location': {'name': None, 'latitude': None, 'longitude': None},
        'alert': {
            'bark_url': None,
            'no_sensation_report': False,
            'no_sensation_mag_threshold': 4.5,
            'tiers': {
                'tier1': {'min': 1.0, 'max': 2.0, 'windows': True, 'bark': True},
                'tier2': {'min': 2.0, 'max': 3.0, 'windows': True, 'bark': True},
                'tier3': {'min': 3.0, 'max': 12.0, 'windows': True, 'bark': True},
            }
        }
    }
    for key, cfg in SOURCE_CONFIG.items():
        src = {'enabled': cfg['enabled']}
        if 'url' in cfg:
            src['url'] = cfg['url']
        if 'fallback_urls' in cfg:
            src['fallback_urls'] = cfg['fallback_urls']
        config['sources'][key] = src
    return config


def deep_merge(default, override):
    merged = {}
    for key in default:
        if key in override:
            if isinstance(default[key], dict) and isinstance(override[key], dict):
                merged[key] = deep_merge(default[key], override[key])
            else:
                merged[key] = override[key]
        else:
            merged[key] = default[key]
    for key in override:
        if key not in merged:
            merged[key] = override[key]
    return merged


def load_config():
    default = build_default_config()
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
            merged = deep_merge(default, user_config)
            if DEBUG:
                console.print(f"[dim][DEBUG] config.json 已加载 (sources:{len(merged.get('sources',{}))}, filters:{len(merged.get('filters',{}))})[/dim]")
            return merged, True
    except json.JSONDecodeError:
        console.print(f"[red]config.json 格式错误，使用默认配置[/red]")
    except Exception:
        pass
    return default, False


def get_location_by_ip():
    try:
        resp = requests.get('http://ip-api.com/json/', timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') == 'success':
                lat = data.get('lat')
                lon = data.get('lon')
                city = data.get('city', '')
                return lat, lon, city
    except Exception:
        pass
    return None, None, None


def _prompt_coord(prompt_text, default, min_val, max_val, label):
    while True:
        raw = Prompt.ask(f"  {prompt_text}", default=str(default))
        try:
            val = float(raw)
        except ValueError:
            console.print(f"[red]输入无效：'{raw}' 不是数字，请重新输入[/red]")
            continue
        if min_val <= val <= max_val:
            return val
        console.print(f"[red]超出范围：{label} 应在 {min_val} ~ {max_val} 之间，请重新输入[/red]")


def setup_wizard():
    global SOURCE_CONFIG, FILTER_DETAIL, USER_LOCATION_NAME, USER_LATITUDE, USER_LONGITUDE
    global ALERT_BARK_URL, ALERT_TIERS, DEBUG, EXPORT_FILE_PATH, EXPORT_ENABLED, NO_SENSATION_REPORT, NO_SENSATION_MAG_THRESHOLD

    console.print("\n[bold cyan]========== 交互式配置向导 ==========[/bold cyan]")
    console.print("[dim]请根据提示依次完成配置，直接回车使用默认值[/dim]")

    # ---------- 1. 位置 ----------
    console.print("\n[bold]--- 位置设置 ---[/bold]")
    has_loc = USER_LATITUDE is not None and USER_LONGITUDE is not None and bool(USER_LOCATION_NAME)
    ip_lat, ip_lon, ip_city = get_location_by_ip()
    use_ip = False
    if ip_lat is None or ip_lon is None:
        console.print("[yellow]无法通过 IP 获取位置" + ("" if has_loc else "，请手动输入") + "[/yellow]")
    elif has_loc:
        answer = Prompt.ask("  是否从 IP 获取位置？", choices=['y', 'n'], default='n')
        use_ip = (answer == 'y')
    else:
        loc_preview = f"{ip_city} ({ip_lat:.4f}, {ip_lon:.4f})" if ip_city else f"({ip_lat:.4f}, {ip_lon:.4f})"
        console.print(f"[green]通过 IP 获取到位置:[/green] {loc_preview}")
        answer = Prompt.ask("  使用这个位置？可以用 https://lbs.qq.com/getPoint/ 获取精确坐标", choices=['y', 'n'], default='y')
        use_ip = (answer == 'y')

    if use_ip:
        USER_LATITUDE = ip_lat
        USER_LONGITUDE = ip_lon
        USER_LOCATION_NAME = ip_city or Prompt.ask("  请输入位置名称", default=USER_LOCATION_NAME or "未设置")
    else:
        lat_default = str(USER_LATITUDE) if USER_LATITUDE is not None else (str(ip_lat) if ip_lat is not None else "30.0")
        lon_default = str(USER_LONGITUDE) if USER_LONGITUDE is not None else (str(ip_lon) if ip_lon is not None else "120.0")
        USER_LATITUDE = _prompt_coord("请输入纬度 (latitude)", lat_default, -90.0, 90.0, "纬度")
        USER_LONGITUDE = _prompt_coord("请输入经度 (longitude)", lon_default, -180.0, 180.0, "经度")
        USER_LOCATION_NAME = Prompt.ask("  请输入位置名称（如城市名）", default=USER_LOCATION_NAME or "未设置")

    # ---------- 2. Bark URL ----------
    console.print("\n[bold]--- Bark 推送设置 ---[/bold]")
    console.print("[dim]Bark 是一个 iOS 推送工具，可在 App Store 获取[/dim]")
    console.print("[dim]例如: https://api.day.app/YourKey/[/dim]")
    bark_input = Prompt.ask("  请输入 Bark 推送 URL（留空则不设置）", default=ALERT_BARK_URL or "")
    ALERT_BARK_URL = bark_input.strip() or None

    # ---------- 3. 数据源 ----------
    console.print("\n[bold]--- 数据源设置 ---[/bold]")
    for key, cfg in SOURCE_CONFIG.items():
        name = cfg.get('name', key)
        default_enabled = 'y' if cfg.get('enabled', False) else 'n'
        url_str = f" ({cfg.get('url', '')})" if 'url' in cfg else ""
        remark = SOURCE_REMARKS.get(key)
        remark_str = f" ({remark})" if remark else ""
        answer = Prompt.ask(f"  启用 {name} ({key}){remark_str}{url_str}", choices=['y', 'n'], default=default_enabled)
        SOURCE_CONFIG[key]['enabled'] = (answer == 'y')

    # ---------- 4. Wolfx 过滤器 ----------
    if SOURCE_CONFIG['wolfx']['enabled']:
        console.print("\n[bold]--- Wolfx 过滤器设置 ---[/bold]")
        for sub_key, default_val in FILTER_DETAIL['wolfx'].items():
            default_str = 'y' if default_val else 'n'
            remark = SOURCE_REMARKS.get(sub_key)
            remark_str = f" ({remark})" if remark else ""
            answer = Prompt.ask(f"  启用 wolfx/{sub_key}{remark_str}", choices=['y', 'n'], default=default_str)
            FILTER_DETAIL['wolfx'][sub_key] = (answer == 'y')

    # ---------- 5. FAN 过滤器 ----------
    if SOURCE_CONFIG['fan']['enabled']:
        console.print("\n[bold]--- FAN 过滤器设置 ---[/bold]")
        for sub_key in FILTER_DETAIL['fan']:
            default_val = FILTER_DETAIL['fan'][sub_key]
            default_str = 'y' if default_val else 'n'
            remark = SOURCE_REMARKS.get(sub_key)
            remark_str = f" ({remark})" if remark else ""
            answer = Prompt.ask(f"  启用 fan/{sub_key}{remark_str}", choices=['y', 'n'], default=default_str)
            FILTER_DETAIL['fan'][sub_key] = (answer == 'y')

    # ---------- 6. 预警分级 ----------
    console.print("\n[bold]--- 预警分级设置 ---[/bold]")
    console.print("[dim]按烈度(估值)范围分级，各分级可分别控制 Windows 弹窗和 Bark 推送[/dim]")
    default_tiers = ALERT_TIERS if ALERT_TIERS else {
        'tier1': {'min': 1.0, 'max': 2.0, 'windows': True, 'bark': True},
        'tier2': {'min': 2.0, 'max': 3.0, 'windows': True, 'bark': True},
        'tier3': {'min': 3.0, 'max': 12.0, 'windows': True, 'bark': True},
    }
    use_default_tiers = Prompt.ask("  使用当前预警分级设置？", choices=['y', 'n'], default='y')
    if use_default_tiers == 'y':
        ALERT_TIERS = default_tiers
    else:
        ALERT_TIERS = {}
        for i in range(1, 4):
            key = f'tier{i}'
            cur = default_tiers.get(key, {})
            min_val = Prompt.ask(f"  {key} 最小烈度", default=str(cur.get('min', 1.0)))
            max_val = Prompt.ask(f"  {key} 最大烈度（留空表示不限制）", default=str(cur.get('max', '')))
            win = Prompt.ask(f"  {key} 启用 Windows 弹窗", choices=['y', 'n'], default='y' if cur.get('windows', True) else 'n')
            bark = Prompt.ask(f"  {key} 启用 Bark 推送", choices=['y', 'n'], default='y' if cur.get('bark', True) else 'n')
            tier_cfg = {'min': float(min_val), 'windows': (win == 'y'), 'bark': (bark == 'y')}
            if max_val.strip():
                tier_cfg['max'] = float(max_val)
            ALERT_TIERS[key] = tier_cfg

    # ---------- 7. 调试模式 ----------
    console.print("\n[bold]--- 调试模式 ---[/bold]")
    debug_answer = Prompt.ask("  开启调试模式？", choices=['y', 'n'], default='y' if DEBUG else 'n')
    DEBUG = (debug_answer == 'y')

    # ---------- 7.5 无震感地震通报 ----------
    console.print("\n[bold]--- 无震感地震通报 ---[/bold]")
    console.print("[dim]烈度为 0 的无感地震是否通过 Windows 弹窗和 Bark 推送进行通报？[/dim]")
    ns_answer = Prompt.ask("  是否开启无震感地震信息通报？", choices=['y', 'n'], default='y' if NO_SENSATION_REPORT else 'n')
    NO_SENSATION_REPORT = (ns_answer == 'y')
    if NO_SENSATION_REPORT:
        default_mag = str(NO_SENSATION_MAG_THRESHOLD)
        mag_input = Prompt.ask("  无感地震最小震级（仅通报 ≥ 该震级的无感地震）", default=default_mag)
        try:
            NO_SENSATION_MAG_THRESHOLD = float(mag_input)
        except ValueError:
            NO_SENSATION_MAG_THRESHOLD = 4.5

    # ---------- 8. 保存 ----------
    save_config()
    console.print("\n[bold green]配置已保存到 config.json[/bold green]")
    console.print("[bold cyan]========================================[/bold cyan]\n")


def save_config():
    config = {
        'sources': {},
        'filters': {key: dict(val) for key, val in FILTER_DETAIL.items()},
        'export_path': EXPORT_FILE_PATH,
        'debug': DEBUG,
        'location': {
            'name': USER_LOCATION_NAME,
            'latitude': USER_LATITUDE,
            'longitude': USER_LONGITUDE
        },
        'alert': {
            'bark_url': ALERT_BARK_URL,
            'no_sensation_report': NO_SENSATION_REPORT,
            'no_sensation_mag_threshold': NO_SENSATION_MAG_THRESHOLD,
            'tiers': {k: dict(v) for k, v in ALERT_TIERS.items()}
        }
    }
    for key, cfg in SOURCE_CONFIG.items():
        src = {'enabled': cfg['enabled']}
        if 'url' in cfg:
            src['url'] = cfg['url']
        if 'fallback_urls' in cfg:
            src['fallback_urls'] = cfg['fallback_urls']
        config['sources'][key] = src
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        if DEBUG:
            console.print(f"[dim][DEBUG] config.json 已保存[/dim]")
    except Exception as e:
        console.print(f"[red]保存配置失败: {e}[/red]")


def apply_config(config):
    global SOURCE_CONFIG, FILTER_DETAIL, EXPORT_FILE_PATH, FAN_RECONNECT_DELAY, DEBUG
    global USER_LOCATION_NAME, USER_LATITUDE, USER_LONGITUDE
    global ALERT_BARK_URL, ALERT_TIERS, NO_SENSATION_REPORT, NO_SENSATION_MAG_THRESHOLD
    sources_cfg = config.get('sources', {})
    for key, src_cfg in sources_cfg.items():
        if key in SOURCE_CONFIG:
            if 'enabled' in src_cfg:
                SOURCE_CONFIG[key]['enabled'] = src_cfg['enabled']
            if 'url' in src_cfg and src_cfg['url'] is not None:
                SOURCE_CONFIG[key]['url'] = src_cfg['url']
            if 'fallback_urls' in src_cfg and src_cfg['fallback_urls'] is not None:
                SOURCE_CONFIG[key]['fallback_urls'] = src_cfg['fallback_urls']
    filters_cfg = config.get('filters', {})
    for src, sub_filters in filters_cfg.items():
        if src in FILTER_DETAIL:
            for sub, enabled in sub_filters.items():
                if sub in FILTER_DETAIL[src]:
                    FILTER_DETAIL[src][sub] = enabled
    if 'export_path' in config:
        EXPORT_FILE_PATH = config['export_path']
    if 'fan_reconnect_delay' in config:
        FAN_RECONNECT_DELAY = config['fan_reconnect_delay']
    if 'debug' in config:
        DEBUG = config['debug']
    loc = config.get('location', {})
    if loc:
        USER_LOCATION_NAME = loc.get('name') or None
        try:
            USER_LATITUDE = float(loc['latitude']) if loc.get('latitude') is not None else None
        except (ValueError, TypeError):
            USER_LATITUDE = None
        try:
            USER_LONGITUDE = float(loc['longitude']) if loc.get('longitude') is not None else None
        except (ValueError, TypeError):
            USER_LONGITUDE = None
        if DEBUG:
            console.print(f"[dim][DEBUG] 用户位置: {USER_LOCATION_NAME} ({USER_LATITUDE}, {USER_LONGITUDE})[/dim]")
    alert_cfg = config.get('alert', {})
    ALERT_BARK_URL = alert_cfg.get('bark_url') or None
    NO_SENSATION_REPORT = alert_cfg.get('no_sensation_report', False)
    NO_SENSATION_MAG_THRESHOLD = alert_cfg.get('no_sensation_mag_threshold', 4.5)
    ALERT_TIERS = alert_cfg.get('tiers', {})
    if DEBUG:
        console.print(f"[dim][DEBUG] 预警配置: bark_url={'已设置' if ALERT_BARK_URL else '未设置'}, tiers={list(ALERT_TIERS.keys())}[/dim]")


# ================== 数据源配置 ==================
SOURCE_CONFIG = {
    'wolfx': {
        'name': 'Wolfx',
        'url': 'wss://ws-api.wolfx.jp/all_eew',
        'enabled': True,
        'type': 'all',
        'need_subscribe': False,
        'fallback_urls': []
    },
    'p2p': {
        'name': 'P2PQuake (EPSP)',
        'enabled': False,
        'type': 'jma_only'
    },
    'p2pjson': {
        'name': 'P2PQuake (JSON API v2)',
        'url': 'wss://api.p2pquake.net/v2/ws',
        'enabled': False,
        'type': 'websocket',
        'need_subscribe': True,
        'subscribe_msg': '{"type":"subscribe","topic":"all"}'
    },
    'nied': {
        'name': 'NIED (日本防灾科学技术研究所)',
        'url': 'wss://sismotide.top/nied',
        'enabled': False,
        'type': 'jma_only',
        'need_subscribe': False,
        'fallback_urls': []
    },
    'fan': {
        'name': 'FAN Studio (地震)',
        'url': 'wss://ws.fanstudio.tech/all',
        'enabled': True,
        'type': 'all',
        'need_subscribe': False,
        'fallback_urls': ['wss://ws.fanstudio.hk/all']
    }
}

SOURCE_DISPLAY = {
    'wolfx': 'Wolfx',
    'p2p': 'P2PQuake (EPSP)',
    'p2pjson': 'P2PQuake (JSON API)',
    'nied': 'NIED',
    'fan': 'FAN Studio'
}

SOURCE_REMARKS = {
    'wolfx': '日本Wolfx数据聚合',
    'p2p': 'P2PQuake EPSP',
    'p2pjson': 'P2PQuake官方JSON API',
    'nied': '日本防灾科学技术研究所',
    'fan': '多机构聚合',
    'jma': '日本气象厅',
    'cenc': '中国地震台网中心',
    'sc': '四川省地震局',
    'fj': '福建省地震局',
    'cq': '重庆市地震局',
    'cenc_eqlist': '中国地震台网中心(目录)',
    'jma_eqlist': '日本气象厅(目录)',
    'cea': '中国地震预警网',
    'cea-pr': '中国地震预警网省级网地震预警',
    'cwa-eew': '台湾气象署地震预警',
    'cwa': '台湾气象署地震报告',
    'hko': '香港天文台地震信息',
    'usgs': '美国地质调查局',
    'sa': '美国ShakeAlert地震预警',
    'emsc': '欧洲地中海地震中心地震信息',
    'bcsf': '法国中央地震研究所地震信息',
    'gfz': '德国地学研究中心地震信息',
    'usp': '巴西圣保罗大学地震信息',
    'kma': '韩国气象厅地震信息',
    'kma-eew': '韩国气象厅地震预警',
    'fssn': 'FSSN地震信息',
    'fssn-cmt': 'FSSN矩心矩张量解(CMT)',
    'ningxia': '宁夏自治区地震局地震信息',
    'guangxi': '广西壮族自治区地震局地震信息',
    'shanxi': '山西省地震局地震信息',
    'beijing': '北京市地震局地震信息',
    'yunnan': '云南省地震局地震信息',
}

HTTP_URLS = {
    'jma': 'https://api.wolfx.jp/jma_eew.json',
    'cenc': 'https://api.wolfx.jp/cenc_eew.json',
    'sc': 'https://api.wolfx.jp/sc_eew.json',
    'fj': 'https://api.wolfx.jp/fj_eew.json',
    'cq': 'https://api.wolfx.jp/cq_eew.json',
    'cenc_eqlist': 'https://api.wolfx.jp/cenc_eqlist.json',
    'jma_eqlist': 'https://api.wolfx.jp/jma_eqlist.json'
}

FAN_SUBTYPES = [
    'cea', 'cwa-eew', 'jma',
    'cenc', 'cwa',
    'usgs', 'sa', 'emsc', 'bcsf', 'gfz', 'usp',
    'kma', 'kma-eew',
    'fssn', 'fssn-cmt',
    'cea-pr',
    'ningxia', 'guangxi', 'shanxi', 'beijing', 'yunnan',
    'hko'
]

FILTER_DETAIL = {
    'wolfx': {
        'jma': False,
        'cenc': True,
        'sc': True,
        'fj': True,
        'cq': True,
        'cenc_eqlist': True,
        'jma_eqlist': False
    },
    'p2p': {
        'jma': False
    },
    'p2pjson': {},
    'nied': {},
    'fan': {
        'cea': True,
        'cwa-eew': True,
        'jma': False,
        'cenc': True,
        'cwa': True,
        'cea-pr': True,
        'ningxia': True,
        'guangxi': True,
        'shanxi': True,
        'beijing': True,
        'yunnan': True,
        'hko': True,
        'usgs': False,
        'sa': False,
        'emsc': False,
        'bcsf': False,
        'gfz': False,
        'usp': False,
        'kma': False,
        'kma-eew': False,
        'fssn': True,
        'fssn-cmt': True,
    }
}
for sub in FAN_SUBTYPES:
    if sub not in FILTER_DETAIL['fan']:
        FILTER_DETAIL['fan'][sub] = False

# FAN 重连冷却时间：改为 5 分钟
FAN_RECONNECT_DELAY = 300
fan_last_reconnect_time = 0

# P2P JSON 重连配置
p2pjson_reconnect_delay = 5

processed_events = set()

# 用户所在地配置（用于距离/烈度/波到着计算）
USER_LOCATION_NAME = None
USER_LATITUDE = None
USER_LONGITUDE = None

# 预警配置
ALERT_BARK_URL = None
ALERT_TIERS = {}
NO_SENSATION_REPORT = False
NO_SENSATION_MAG_THRESHOLD = 4.5
BARK_COUNTDOWN_THREADS = {}

# 动态P/S波倒计时管理
_countdown_active = {}
_countdown_thread = None
_countdown_lock = threading.Lock()

console = Console()
_console_print = console.print

def _ts_print(*args, **kwargs):
    now = datetime.now().strftime("%H:%M:%S")
    _console_print(f"[dim]{now}[/dim]", *args, **kwargs)

console.print = _ts_print
ws_running = True
ws_connections = {}
ws_status = {}

# ================== 导出功能全局变量 ==================
EXPORT_ENABLED = False
EXPORT_FILE = None
EXPORT_FILE_PATH = None
# ==================================================


# ---------- 表格显示与导出 ----------
def write_table_to_csv(title, rows):
    global EXPORT_FILE, EXPORT_FILE_PATH
    if not EXPORT_ENABLED:
        return
    try:
        if EXPORT_FILE is None:
            if EXPORT_FILE_PATH:
                filename = EXPORT_FILE_PATH
            else:
                prog_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(prog_dir, f"quake_export_{timestamp}.csv")
            os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)
            EXPORT_FILE = open(filename, 'a', newline='', encoding='utf-8-sig')
            if os.path.getsize(filename) == 0:
                writer = csv.writer(EXPORT_FILE)
                writer.writerow(["表格标题", "项目", "信息"])
        writer = csv.writer(EXPORT_FILE)
        for row in rows:
            writer.writerow([title, row[0], row[1]])
        EXPORT_FILE.flush()
    except Exception as e:
        console.print(f"[red]写入CSV失败: {e}[/red]")


def _intensity_style(val):
    roman_map = {'I':1,'II':2,'III':3,'IV':4,'V':5,'VI':6,'VII':7,'VIII':8,'IX':9,'X':10}
    desc_map = {'无感':0,'微':1,'弱':2,'中':3,'较强':4,'强':5,'很强':6,'超强':7}
    s = str(val).strip()
    m = re.search(r'[\d.]+', s)
    if m:
        v = float(m.group())
    else:
        for r, iv in roman_map.items():
            if r in s.upper():
                v = iv
                break
        else:
            for k, iv in desc_map.items():
                if k in s:
                    v = iv
                    break
            else:
                return None
    if v <= 0.5:
        return None                           # 灰色 (默认)
    if v <= 1.5:
        return "black on light_cyan"          # 1度 - 浅蓝
    if v <= 2.5:
        return "white on green"               # 2度 - 绿
    if v <= 3.5:
        return "black on yellow"              # 3度 - 黄
    if v <= 4.5:
        return "white on dark_orange"         # 4度 - 橙
    if v <= 5.5:
        return "bold white on red"            # 5度 - 红
    if v <= 6.5:
        return "bold white on magenta"        # 6度 - 紫红
    return "bold white on bright_magenta"     # 7+  - 深紫


def print_earthquake_table(title, rows, source_label):
    if not rows:
        return
    table = Table(title=title, box=box.ROUNDED, border_style="bold yellow")
    table.add_column("项目", style="cyan", no_wrap=True, width=12)
    table.add_column("信息", no_wrap=False, width=48)
    rows_with_src = rows.copy()
    rows_with_src.append(["信号源", source_label])
    for row in rows_with_src:
        label = str(row[0])
        val = str(row[1])
        if '本地烈度(估值)' in label:
            cell_style = _intensity_style(val)
            if cell_style:
                table.add_row(Text(label, style="cyan"), Text(val, style=cell_style))
            else:
                table.add_row(Text(label, style="cyan"), Text(val))
        else:
            table.add_row(Text(label, style="cyan"), Text(val))
    console.print(table)
    write_table_to_csv(title, rows_with_src)


def _intensity_bg(v):
    if v is None or v < 0.5:
        return None
    if v <= 1.5:
        return "light_cyan"
    if v <= 2.5:
        return "green"
    if v <= 3.5:
        return "yellow"
    if v <= 4.5:
        return "dark_orange"
    if v <= 5.5:
        return "red"
    if v <= 6.5:
        return "magenta"
    return "bright_magenta"


def _normalize_ts(raw):
    if not raw:
        return ""
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return s


def print_eqlist_compact(items, title):
    if not items:
        return
    table = Table(title=title, box=box.ROUNDED, border_style="bold yellow")
    table.add_column("预估烈度", justify="center", vertical="middle", no_wrap=True, width=4)
    table.add_column("信息", no_wrap=False, width=42)
    for local_int, lines in items:
        if local_int is None:
            cell = Text("-", style="white on grey23")
        elif local_int <= 0:
            cell = Text("0", style="white on grey23")
        else:
            bg = _intensity_bg(local_int) or "grey23"
            cell = Text(str(int(round(local_int))), style=f"white on {bg}")
        table.add_row(cell, Text("\n".join(lines)))
    console.print(table)

def print_weather_table(title, rows, source_label):
    if not rows:
        return
    table = Table(title=title, box=box.ROUNDED, border_style="bold blue")
    table.add_column("项目", style="cyan", no_wrap=True, width=12)
    table.add_column("信息", style="white", no_wrap=False, width=48)
    rows_with_src = rows.copy()
    rows_with_src.append(["信号源", source_label])
    for row in rows_with_src:
        table.add_row(str(row[0]), str(row[1]))
    console.print(table)
    write_table_to_csv(title, rows_with_src)


# ---------- 海啸预警 (FAN tsunami) ----------
def process_tsunami(data, source_label):
    try:
        rows = []
        wi = data.get('warningInfo', {})
        si = data.get('shockInfo', {})
        ti = data.get('timeInfo', {})
        rows.append(["标题", wi.get('title', 'N/A')])
        rows.append(["级别", wi.get('level', 'N/A')])
        rows.append(["发布机构", wi.get('orgUnit', 'N/A')])
        rows.append(["发震时刻", si.get('shockTime', 'N/A')])
        rows.append(["震中位置", si.get('placeName', '未知地区')])
        lat, lon = si.get('latitude'), si.get('longitude')
        rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
        rows.append(["震级", si.get('magnitude', 'N/A')])
        rows.append(["深度(km)", si.get('depth', 'N/A')])
        rows.append(["发布时间", ti.get('alarmDate', 'N/A')])
        rows.append(["更新时间", ti.get('updateDate', 'N/A')])

        forecasts = data.get('forecasts', [])
        if forecasts:
            first = forecasts[0]
            province = first.get('province', '')
            area = first.get('forecastArea', '')
            rows.append(["预报区域", f"{province} {area}".strip() or 'N/A'])
            rows.append(["预计到达", first.get('estimatedArrivalTime', 'N/A')])
            rows.append(["最大波高(cm)", first.get('maxWaveHeight', 'N/A')])
        else:
            rows.append(["预报区域", "无"])
        wl = data.get('waterLevelMonitoring', [])
        if wl:
            first_wl = wl[0]
            rows.append(["监测站", first_wl.get('stationName', 'N/A')])
            rows.append(["最大波高(cm)", first_wl.get('maxWaveHeight', 'N/A')])
        else:
            rows.append(["监测站", "无"])

        if rows:
            table = Table(title="海啸预警 (自然资源部)", box=box.ROUNDED, border_style="bold red")
            table.add_column("项目", style="cyan", no_wrap=True, width=12)
            table.add_column("信息", style="white", no_wrap=False, width=48)
            rows.append(["信号源", source_label])
            for row in rows:
                table.add_row(row[0], str(row[1]))
            console.print(table)
            write_table_to_csv("海啸预警 (自然资源部)", rows)
            play_sound(SOUND_ALERT)
    except Exception as e:
        console.print(f"[red]海啸预警解析错误: {e}[/red]")


# ---------- FAN 各子源独立处理 ----------
def process_fan_data(data, sub_type, source_label):
    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime', 'origin_time')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter', 'region_name')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    add_location_rows(rows, lat, lon, safe_get(data, 'magnitude', 'Magunitude'))
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    if sub_type in ('jma', 'nied', 'p2p', 'p2pjson'):
        rows.append(["最大震度/烈度", get_intensity_display(data, 'jma')])
    else:
        rows.append(["最大震度/烈度", get_intensity_display(data, 'cenc')])
    rows.append(["最终报", "是" if data.get('final', False) else "否"])
    rows.append(["取消报", "是" if data.get('cancel', False) else "否"])
    rows.append(["更新报数", str(data.get('updates', 1))])
    info_type = safe_get(data, 'infoTypeName', 'info_type')
    if info_type == 'N/A' or info_type == '' or info_type is None:
        info_type = '地震测定报'
    rows.append(["信息类型", info_type])
    affected = data.get('locationDesc', [])
    rows.append(["影响区域", ', '.join(affected) if affected else '无'])

    title_map = {
        'jma': '地震预警速报 (日本气象厅 JMA)',
        'cenc': '地震情报 (中国地震台网中心 CENC)',
        'cwa': '地震报告 (台湾气象署 CWA)',
        'cwa-eew': '地震预警速报 (台湾气象署 CWA-EEW)',
        'cea': '地震预警速报 (中国地震预警网 CEA)',
    }
    title = title_map.get(sub_type, f"地震报告 ({sub_type})")

    province_map = {
        'cea-pr': '省级', 'ningxia': '宁夏', 'guangxi': '广西',
        'shanxi': '山西', 'beijing': '北京', 'yunnan': '云南'
    }
    if sub_type in province_map:
        title = f"地震测定报 ({province_map[sub_type]}省地震局)"

    if rows:
        print_earthquake_table(title, rows, source_label)


# ---------- Wolfx 各处理函数 ----------
def process_jma_eew(data, source_key, source_label):
    event_id = safe_get(data, 'EventID', 'id', default='')
    if not event_id:
        if DEBUG:
            console.print("[dim]JMA 数据缺少 EventID/id，跳过[/dim]")
        return
    origin_time = safe_get(data, 'OriginTime', 'origin_time', 'shockTime', default='')
    if not origin_time:
        if DEBUG:
            console.print(f"[dim]JMA 数据缺少发震时刻，跳过 (EventID: {event_id})[/dim]")
        return

    serial = data.get('Serial', 1)
    report_key = f"jma_{event_id}_serial_{serial}"
    if report_key in processed_events:
        return
    processed_events.add(report_key)

    max_intensity = safe_get(data, 'MaxIntensity', 'epiIntensity', default='N/A')

    rows = []
    rows.append(["发震时刻", origin_time])
    rows.append(["震中位置", safe_get(data, 'Hypocenter', 'placeName', 'region_name')])
    lat = safe_get(data, 'Latitude', 'latitude')
    lon = safe_get(data, 'Longitude', 'longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    add_location_rows(rows, lat, lon, safe_get(data, 'Magunitude', 'magnitude'))
    rows.append(["震级(M)", safe_get(data, 'Magunitude', 'magnitude')])
    rows.append(["深度(km)", safe_get(data, 'Depth', 'depth')])
    rows.append(["最大震度(日本)", max_intensity])
    rows.append(["速报序号", str(serial)])
    rows.append(["発表時刻", safe_get(data, 'AnnouncedTime', 'announced_time')])
    issue = data.get('Issue', {})
    rows.append(["発表機関", issue.get('Source', 'N/A')])
    rows.append(["発表状態", issue.get('Status', 'N/A')])
    rows.append(["最終报", "是" if data.get('isFinal', False) else "否"])
    rows.append(["取消报", "是" if data.get('isCancel', False) else "否"])
    rows.append(["警报触发", "是" if data.get('isWarn', False) else "否"])
    rows.append(["海域推定", "是" if data.get('isSea', False) else "否"])

    acc = data.get('Accuracy', {})
    rows.append(["震央精度", acc.get('Epicenter', 'N/A')])
    rows.append(["深度精度", acc.get('Depth', 'N/A')])
    rows.append(["震级精度", acc.get('Magnitude', 'N/A')])

    max_int_change = data.get('MaxIntChange', {}).get('String', '无')
    rows.append(["震度变化", max_int_change])

    warn_areas = data.get('WarnArea', [])
    if warn_areas:
        first = warn_areas[0]
        rows.append(["警报区域示例", f"{first.get('Chiiki', '')} 震度 {first.get('Shindo1', 'N/A')}"])
    else:
        rows.append(["警报区域示例", "无具体区域"])

    print_earthquake_table("地震预警速报 (日本气象厅 JMA)", rows, source_label)
    dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and USER_LATITUDE else None
    if dist is not None:
        mag_val = safe_get(data, 'Magunitude', 'magnitude')
        origin_name = safe_get(data, 'Hypocenter', 'placeName', 'region_name')
        depth_val = safe_get(data, 'Depth', 'depth')
        p_sec, s_sec = calc_wave_arrival(dist)
        local_int = estimate_local_intensity(mag_val, dist)
        trigger_alert(source_label, origin_name, mag_val, depth_val, dist,
                      local_int, max_intensity, origin_time, p_sec, s_sec, event_id)
        if local_int and local_int > 0:
            start_countdown(f"jma_{event_id}", origin_time, dist, USER_LOCATION_NAME, mag_val, origin_name)


def process_cenc_eew(data, source_key, source_label):
    event_id = safe_get(data, 'EventID', 'event_id', 'eventId', default='')
    if not event_id:
        if DEBUG:
            console.print("[dim]CENC 数据缺少 EventID，跳过[/dim]")
        return
    if event_id in processed_events:
        return
    processed_events.add(event_id)

    rows = []
    rows.append(["ID", safe_get(data, 'ID', default='N/A')])
    rows.append(["发报时间", safe_get(data, 'ReportTime', 'report_time')])
    rows.append(["发震时刻", safe_get(data, 'OriginTime', 'origin_time', 'shockTime')])
    rows.append(["震中位置", safe_get(data, 'HypoCenter', 'Hypocenter', 'hypocenter', 'placeName')])
    lat = safe_get(data, 'Latitude', 'latitude')
    lon = safe_get(data, 'Longitude', 'longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    add_location_rows(rows, lat, lon, safe_get(data, 'Magnitude', 'Magunitude', 'magnitude'))
    rows.append(["震级(M)", safe_get(data, 'Magnitude', 'Magunitude', 'magnitude')])
    rows.append(["深度(km)", safe_get(data, 'Depth', 'depth')])
    rows.append(["速报序号", str(data.get('ReportNum', 'N/A'))])
    rows.append(["最大烈度(中国)", get_intensity_display(data, 'cenc')])
    rows.append(["最终报", "是" if data.get('isFinal', data.get('is_final', False)) else "否"])

    print_earthquake_table("地震情报 (中国地震台网中心 CENC)", rows, source_label)
    dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and USER_LATITUDE else None
    if dist is not None:
        mag_val = safe_get(data, 'Magnitude', 'Magunitude', 'magnitude')
        origin_name = safe_get(data, 'HypoCenter', 'Hypocenter', 'hypocenter', 'placeName')
        ot = safe_get(data, 'OriginTime', 'origin_time', 'shockTime')
        depth_val = safe_get(data, 'Depth', 'depth')
        max_int = safe_get(data, 'MaxIntensity', 'epiIntensity', default='N/A')
        p_sec, s_sec = calc_wave_arrival(dist)
        local_int = estimate_local_intensity(mag_val, dist)
        trigger_alert(source_label, origin_name, mag_val, depth_val, dist,
                      local_int, max_int, ot, p_sec, s_sec, event_id)
        if local_int and local_int > 0:
            start_countdown(f"cenc_{event_id}", ot, dist, USER_LOCATION_NAME, mag_val, origin_name)


def process_sc_eew(data, source_key, source_label):
    event_id = data.get('EventID', '')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)

    rows = []
    rows.append(["ID", safe_get(data, 'ID', default='N/A')])
    rows.append(["发报时间", safe_get(data, 'ReportTime', 'report_time')])
    rows.append(["发震时刻", safe_get(data, 'OriginTime', 'origin_time')])
    rows.append(["震中位置", safe_get(data, 'HypoCenter', 'Hypocenter', 'placeName')])
    lat = safe_get(data, 'Latitude', 'latitude')
    lon = safe_get(data, 'Longitude', 'longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    add_location_rows(rows, lat, lon, safe_get(data, 'Magunitude', 'magnitude'))
    rows.append(["震级(M)", safe_get(data, 'Magunitude', 'magnitude')])
    rows.append(["深度(km)", safe_get(data, 'Depth', 'depth')])
    rows.append(["速报序号", str(data.get('ReportNum', 'N/A'))])
    rows.append(["最大烈度(中国)", get_intensity_display(data, 'cenc')])
    rows.append(["警报触发", "是" if data.get('isWarn', False) else "否"])

    print_earthquake_table("地震测定报 (四川省地震局 SC)", rows, source_label)
    dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and USER_LATITUDE else None
    if dist is not None:
        mag_val = safe_get(data, 'Magunitude', 'magnitude')
        origin_name = safe_get(data, 'HypoCenter', 'Hypocenter', 'placeName')
        ot = safe_get(data, 'OriginTime', 'origin_time')
        depth_val = safe_get(data, 'Depth', 'depth')
        max_int = safe_get(data, 'MaxIntensity', 'epiIntensity', default='N/A')
        p_sec, s_sec = calc_wave_arrival(dist)
        local_int = estimate_local_intensity(mag_val, dist)
        trigger_alert(source_label, origin_name, mag_val, depth_val, dist,
                      local_int, max_int, ot, p_sec, s_sec, event_id)
        if local_int and local_int > 0:
            start_countdown(f"sc_{event_id}", ot, dist, USER_LOCATION_NAME, mag_val, origin_name)


def process_fj_eew(data, source_key, source_label):
    event_id = data.get('EventID', '')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)

    rows = []
    rows.append(["ID", safe_get(data, 'ID', default='N/A')])
    rows.append(["发报时间", safe_get(data, 'ReportTime', 'report_time')])
    rows.append(["发震时刻", safe_get(data, 'OriginTime', 'origin_time')])
    rows.append(["震中位置", safe_get(data, 'HypoCenter', 'Hypocenter', 'placeName')])
    lat = safe_get(data, 'Latitude', 'latitude')
    lon = safe_get(data, 'Longitude', 'longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    add_location_rows(rows, lat, lon, safe_get(data, 'Magunitude', 'magnitude'))
    rows.append(["震级(M)", safe_get(data, 'Magunitude', 'magnitude')])
    rows.append(["速报序号", str(data.get('ReportNum', 'N/A'))])
    rows.append(["最终报", "是" if data.get('isFinal', False) else "否"])

    print_earthquake_table("地震测定报 (福建省地震局 FJ)", rows, source_label)
    dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and USER_LATITUDE else None
    if dist is not None:
        mag_val = safe_get(data, 'Magunitude', 'magnitude')
        origin_name = safe_get(data, 'HypoCenter', 'Hypocenter', 'placeName')
        ot = safe_get(data, 'OriginTime', 'origin_time')
        depth_val = safe_get(data, 'Depth', 'depth')
        p_sec, s_sec = calc_wave_arrival(dist)
        local_int = estimate_local_intensity(mag_val, dist)
        trigger_alert(source_label, origin_name, mag_val, depth_val, dist,
                      local_int, None, ot, p_sec, s_sec, event_id)
        if local_int and local_int > 0:
            start_countdown(f"fj_{event_id}", ot, dist, USER_LOCATION_NAME, mag_val, origin_name)


def process_cq_eew(data, source_key, source_label):
    event_id = data.get('EventID', '')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)

    rows = []
    rows.append(["ID", safe_get(data, 'ID', default='N/A')])
    rows.append(["发报时间", safe_get(data, 'ReportTime', 'report_time')])
    rows.append(["发震时刻", safe_get(data, 'OriginTime', 'origin_time')])
    rows.append(["震中位置", safe_get(data, 'HypoCenter', 'Hypocenter', 'placeName')])
    lat = safe_get(data, 'Latitude', 'latitude')
    lon = safe_get(data, 'Longitude', 'longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    add_location_rows(rows, lat, lon, safe_get(data, 'Magnitude', 'Magunitude', 'magnitude'))
    rows.append(["震级(M)", safe_get(data, 'Magnitude', 'Magunitude', 'magnitude')])
    rows.append(["深度(km)", safe_get(data, 'Depth', 'depth')])
    rows.append(["速报序号", str(data.get('ReportNum', 'N/A'))])
    rows.append(["最大烈度(中国)", get_intensity_display(data, 'cenc')])

    print_earthquake_table("地震测定报 (重庆市地震局 CQ)", rows, source_label)
    dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and USER_LATITUDE else None
    if dist is not None:
        mag_val = safe_get(data, 'Magnitude', 'Magunitude', 'magnitude')
        origin_name = safe_get(data, 'HypoCenter', 'Hypocenter', 'placeName')
        ot = safe_get(data, 'OriginTime', 'origin_time')
        depth_val = safe_get(data, 'Depth', 'depth')
        max_int = safe_get(data, 'MaxIntensity', 'epiIntensity', default='N/A')
        p_sec, s_sec = calc_wave_arrival(dist)
        local_int = estimate_local_intensity(mag_val, dist)
        trigger_alert(source_label, origin_name, mag_val, depth_val, dist,
                      local_int, max_int, ot, p_sec, s_sec, event_id)
        if local_int and local_int > 0:
            start_countdown(f"cq_{event_id}", ot, dist, USER_LOCATION_NAME, mag_val, origin_name)


def process_cenc_eqlist(data, source_key, source_label, send_notification=True, count=3, sound=True, compact=False):
    entries = []
    if any(k.startswith('No') for k in data):
        for key in sorted(data.keys(), key=lambda k: int(k[2:]) if k[2:].isdigit() else 0):
            entry = data[key]
            if isinstance(entry, dict):
                entries.append(entry)
    else:
        entries = [data]
    compact_items = []
    for entry in entries[:count]:
        event_id = safe_get(entry, 'EventID', 'event_id', 'id', default='')
        if not event_id or event_id in processed_events:
            continue
        processed_events.add(event_id)
        lat = safe_get(entry, 'latitude', 'Latitude')
        lon = safe_get(entry, 'longitude', 'Longitude')
        mag_val = safe_get(entry, 'magnitude', 'Magunitude')
        dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and USER_LATITUDE else None
        if compact:
            local_int = estimate_local_intensity(mag_val, dist) if dist is not None else None
            location = safe_get(entry, 'placeName', 'location', 'Hypocenter')
            t = _normalize_ts(safe_get(entry, 'time', 'OriginTime'))
            meta = f"M{mag_val}"
            if dist is not None:
                meta += f" {dist:.0f}km"
            meta += f"  CENC/Wolfx"
            compact_items.append((local_int, [location, f"{t}(+8)", meta]))
        else:
            rows = []
            rows.append(["发震时刻", safe_get(entry, 'time', 'OriginTime')])
            rows.append(["发报时间", safe_get(entry, 'ReportTime', 'report_time')])
            rows.append(["震中位置", safe_get(entry, 'placeName', 'location', 'Hypocenter')])
            rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
            add_location_rows(rows, lat, lon, mag_val)
            rows.append(["震级(M)", mag_val])
            rows.append(["深度(km)", safe_get(entry, 'depth', 'Depth')])
            rows.append(["最大烈度", safe_get(entry, 'intensity', 'MaxIntensity', 'N/A')])
            rows.append(["信息类型", safe_get(entry, 'type', 'N/A')])
            print_earthquake_table("地震信息 (中国地震台网 CENC 目录)", rows, source_label)
        if sound:
            play_sound(SOUND_ALERT)
        if send_notification:
            if dist is not None:
                origin_name = safe_get(entry, 'placeName', 'location', 'Hypocenter')
                ot = safe_get(entry, 'time', 'OriginTime')
                depth_val = safe_get(entry, 'depth', 'Depth')
                max_int = safe_get(entry, 'intensity', 'MaxIntensity', 'N/A')
                p_sec, s_sec = calc_wave_arrival(dist)
                local_int = estimate_local_intensity(mag_val, dist)
                trigger_alert(source_label, origin_name, mag_val, depth_val, dist,
                              local_int, max_int, ot, p_sec, s_sec, event_id)
                if local_int and local_int > 0:
                    start_countdown(f"cenc_eqlist_{event_id}", ot, dist, USER_LOCATION_NAME, mag_val, origin_name)
    if compact and compact_items:
        print_eqlist_compact(compact_items, "地震目录 (中国地震台网 CENC)")


def process_jma_eqlist(data, source_key, source_label, send_notification=True, count=3, sound=True, compact=False):
    entries = []
    if any(k.startswith('No') for k in data):
        for key in sorted(data.keys(), key=lambda k: int(k[2:]) if k[2:].isdigit() else 0):
            entry = data[key]
            if isinstance(entry, dict):
                entries.append(entry)
    else:
        entries = [data]
    compact_items = []
    for entry in entries[:count]:
        event_id = safe_get(entry, 'EventID', 'event_id', 'id', default='')
        if not event_id or event_id in processed_events:
            continue
        processed_events.add(event_id)
        lat = safe_get(entry, 'latitude', 'Latitude')
        lon = safe_get(entry, 'longitude', 'Longitude')
        mag_val = safe_get(entry, 'magnitude', 'Magunitude')
        dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and USER_LATITUDE else None
        if compact:
            local_int = estimate_local_intensity(mag_val, dist) if dist is not None else None
            location = safe_get(entry, 'location', 'placeName', 'Hypocenter')
            t = _normalize_ts(safe_get(entry, 'time_full', 'time', 'OriginTime'))
            meta = f"M{mag_val}"
            if dist is not None:
                meta += f" {dist:.0f}km"
            meta += f"  JMA/Wolfx"
            compact_items.append((local_int, [location, f"{t}(+9)", meta]))
        else:
            depth_raw = safe_get(entry, 'depth', default='')
            depth_val = depth_raw
            if isinstance(depth_raw, str) and depth_raw.endswith('km'):
                depth_val = depth_raw[:-2].strip()
            rows = []
            rows.append(["发震时刻", safe_get(entry, 'time_full', 'time', 'OriginTime')])
            rows.append(["震中位置", safe_get(entry, 'location', 'placeName', 'Hypocenter')])
            rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
            add_location_rows(rows, lat, lon, mag_val)
            rows.append(["震级(M)", mag_val])
            rows.append(["深度(km)", depth_val])
            rows.append(["最大震度(日本)", safe_get(entry, 'shindo', 'MaxIntensity', 'N/A')])
            info = safe_get(entry, 'info', default='')
            if info:
                rows.append(["附注", info])
            print_earthquake_table("地震信息 (日本气象厅 JMA 目录)", rows, source_label)
        if sound:
            play_sound(SOUND_ALERT)
        if send_notification:
            if dist is not None:
                origin_name = safe_get(entry, 'location', 'placeName', 'Hypocenter')
                ot = safe_get(entry, 'time_full', 'time', 'OriginTime')
                depth_raw = safe_get(entry, 'depth', default='')
                depth_val = depth_raw
                if isinstance(depth_raw, str) and depth_raw.endswith('km'):
                    depth_val = depth_raw[:-2].strip()
                max_int = safe_get(entry, 'shindo', 'MaxIntensity', 'N/A')
                p_sec, s_sec = calc_wave_arrival(dist)
                local_int = estimate_local_intensity(mag_val, dist)
                trigger_alert(source_label, origin_name, mag_val, depth_val, dist,
                              local_int, max_int, ot, p_sec, s_sec, event_id)
                if local_int and local_int > 0:
                    start_countdown(f"jma_eqlist_{event_id}", ot, dist, USER_LOCATION_NAME, mag_val, origin_name)
    if compact and compact_items:
        print_eqlist_compact(compact_items, "地震目录 (日本气象厅 JMA)")


def process_cea_eew(data, source_key, source_label):
    event_id = safe_get(data, 'eventId', 'id', default='')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    add_location_rows(rows, lat, lon, safe_get(data, 'magnitude', 'Magunitude'))
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    rows.append(["预估烈度", get_intensity_display(data, 'cenc')])

    print_earthquake_table("地震预警速报 (中国地震预警网 CEA)", rows, source_label)

    dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and USER_LATITUDE else None
    if dist is not None:
        mag_val = safe_get(data, 'magnitude', 'Magunitude')
        origin_name = safe_get(data, 'placeName', 'Hypocenter')
        ot = safe_get(data, 'shockTime', 'OriginTime')
        depth_val = safe_get(data, 'depth', 'Depth')
        p_sec, s_sec = calc_wave_arrival(dist)
        local_int = estimate_local_intensity(mag_val, dist)
        trigger_alert(source_label, origin_name, mag_val, depth_val, dist,
                      local_int, None, ot, p_sec, s_sec, event_id)
        if local_int and local_int > 0:
            start_countdown(f"cea_{event_id}", ot, dist, USER_LOCATION_NAME, mag_val, origin_name)


def process_cwa_eew(data, source_key, source_label):
    event_id = safe_get(data, 'id', default='')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    add_location_rows(rows, lat, lon, safe_get(data, 'magnitude', 'Magunitude'))
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    rows.append(["最大震度", get_intensity_display(data, 'cenc')])
    affected = data.get('locationDesc', [])
    rows.append(["影响区域", ', '.join(affected) if affected else '无'])

    print_earthquake_table("地震预警速报 (台湾气象署 CWA-EEW)", rows, source_label)
    dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and USER_LATITUDE else None
    if dist is not None:
        mag_val = safe_get(data, 'magnitude', 'Magunitude')
        origin_name = safe_get(data, 'placeName', 'Hypocenter')
        ot = safe_get(data, 'shockTime', 'OriginTime')
        depth_val = safe_get(data, 'depth', 'Depth')
        p_sec, s_sec = calc_wave_arrival(dist)
        local_int = estimate_local_intensity(mag_val, dist)
        trigger_alert(source_label, origin_name, mag_val, depth_val, dist,
                      local_int, None, ot, p_sec, s_sec, event_id)
        if local_int and local_int > 0:
            start_countdown(f"cwa_{event_id}", ot, dist, USER_LOCATION_NAME, mag_val, origin_name)


def process_cwa_report(data, source_key, source_label):
    event_id = safe_get(data, 'id', default='')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    add_location_rows(rows, lat, lon, safe_get(data, 'magnitude', 'Magunitude'))
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    rows.append(["最大震度", get_intensity_display(data, 'cenc')])

    print_earthquake_table("地震报告 (台湾气象署 CWA)", rows, source_label)
    dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and USER_LATITUDE else None
    if dist is not None:
        mag_val = safe_get(data, 'magnitude', 'Magunitude')
        origin_name = safe_get(data, 'placeName', 'Hypocenter')
        ot = safe_get(data, 'shockTime', 'OriginTime')
        depth_val = safe_get(data, 'depth', 'Depth')
        p_sec, s_sec = calc_wave_arrival(dist)
        local_int = estimate_local_intensity(mag_val, dist)
        trigger_alert(source_label, origin_name, mag_val, depth_val, dist,
                      local_int, None, ot, p_sec, s_sec, event_id)
        if local_int and local_int > 0:
            start_countdown(f"cwa_rpt_{event_id}", ot, dist, USER_LOCATION_NAME, mag_val, origin_name)


def process_provincial_eew(data, source_key, source_label, province_name):
    event_id = safe_get(data, 'eventId', 'id', default='')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    add_location_rows(rows, lat, lon, safe_get(data, 'magnitude', 'Magunitude'))
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    rows.append(["最大烈度", get_intensity_display(data, 'cenc')])

    print_earthquake_table(f"地震测定报 ({province_name}省地震局)", rows, source_label)
    dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and USER_LATITUDE else None
    if dist is not None:
        mag_val = safe_get(data, 'magnitude', 'Magunitude')
        origin_name = safe_get(data, 'placeName', 'Hypocenter')
        ot = safe_get(data, 'shockTime', 'OriginTime')
        depth_val = safe_get(data, 'depth', 'Depth')
        p_sec, s_sec = calc_wave_arrival(dist)
        local_int = estimate_local_intensity(mag_val, dist)
        trigger_alert(source_label, origin_name, mag_val, depth_val, dist,
                      local_int, None, ot, p_sec, s_sec, event_id)
        if local_int and local_int > 0:
            start_countdown(f"prov_{event_id}", ot, dist, USER_LOCATION_NAME, mag_val, origin_name)


def process_hko_eew(data, source_key, source_label):
    event_id = safe_get(data, 'eventId', 'id', default='')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    add_location_rows(rows, lat, lon, safe_get(data, 'magnitude', 'Magunitude'))
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    rows.append(["最大震度/烈度", get_intensity_display(data, 'cenc')])
    rows.append(["区域", safe_get(data, 'region', 'citystring')])

    print_earthquake_table("地震报告 (香港天文台 HKO)", rows, source_label)
    dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and USER_LATITUDE else None
    if dist is not None:
        mag_val = safe_get(data, 'magnitude', 'Magunitude')
        origin_name = safe_get(data, 'placeName', 'Hypocenter')
        ot = safe_get(data, 'shockTime', 'OriginTime')
        depth_val = safe_get(data, 'depth', 'Depth')
        p_sec, s_sec = calc_wave_arrival(dist)
        local_int = estimate_local_intensity(mag_val, dist)
        trigger_alert(source_label, origin_name, mag_val, depth_val, dist,
                      local_int, None, ot, p_sec, s_sec, event_id)
        if local_int and local_int > 0:
            start_countdown(f"hko_{event_id}", ot, dist, USER_LOCATION_NAME, mag_val, origin_name)


def process_usgs_eew(data, source_key, source_label):
    event_id = safe_get(data, 'id', default='')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    add_location_rows(rows, lat, lon, safe_get(data, 'magnitude', 'Magunitude'))
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    rows.append(["最大震度/烈度", get_intensity_display(data, 'cenc')])
    rows.append(["标题", safe_get(data, 'title')])

    print_earthquake_table("地震测定报 (USGS)", rows, source_label)
    dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and USER_LATITUDE else None
    if dist is not None:
        mag_val = safe_get(data, 'magnitude', 'Magunitude')
        origin_name = safe_get(data, 'placeName', 'Hypocenter')
        ot = safe_get(data, 'shockTime', 'OriginTime')
        depth_val = safe_get(data, 'depth', 'Depth')
        p_sec, s_sec = calc_wave_arrival(dist)
        local_int = estimate_local_intensity(mag_val, dist)
        trigger_alert(source_label, origin_name, mag_val, depth_val, dist,
                      local_int, None, ot, p_sec, s_sec, event_id)
        if local_int and local_int > 0:
            start_countdown(f"usgs_{event_id}", ot, dist, USER_LOCATION_NAME, mag_val, origin_name)


def process_generic_eew(data, source_key, source_label, data_type):
    event_id = safe_get(data, 'eventId', 'id', default='')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime', 'origin_time')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter', 'region_name')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    add_location_rows(rows, lat, lon, safe_get(data, 'magnitude', 'Magunitude'))
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    rows.append(["最大震度/烈度", get_intensity_display(data, 'cenc')])

    print_earthquake_table(f"地震报告 ({data_type})", rows, source_label)
    dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and USER_LATITUDE else None
    if dist is not None:
        mag_val = safe_get(data, 'magnitude', 'Magunitude')
        origin_name = safe_get(data, 'placeName', 'Hypocenter', 'region_name')
        ot = safe_get(data, 'shockTime', 'OriginTime', 'origin_time')
        depth_val = safe_get(data, 'depth', 'Depth')
        p_sec, s_sec = calc_wave_arrival(dist)
        local_int = estimate_local_intensity(mag_val, dist)
        trigger_alert(source_label, origin_name, mag_val, depth_val, dist,
                      local_int, None, ot, p_sec, s_sec, event_id)
        if local_int and local_int > 0:
            start_countdown(f"generic_{event_id}", ot, dist, USER_LOCATION_NAME, mag_val, origin_name)


# ---------- 统一入口 ----------
def process_eew(data, source_key, default_type=None):
    data_type = data.get('type')
    if data_type is None and default_type is not None:
        data_type = default_type
    if not data_type:
        return

    if DEBUG:
        event_id = data.get('EventID') or data.get('eventId') or data.get('id', '?')
        console.print(f"[dim][DEBUG] process_eew: type={data_type}, source={source_key}, id={event_id}[/dim]")

    if source_key in FILTER_DETAIL:
        if data_type in FILTER_DETAIL[source_key]:
            if not FILTER_DETAIL[source_key][data_type]:
                return

    if source_key == 'fan':
        source_label = f"{source_key}.{data_type}"
        process_fan_data(data, data_type, source_label)
        return
    elif source_key == 'p2pjson':
        source_label = f"{source_key}.{data_type}"
        if data_type == 'jma':
            process_jma_eew(data, source_key, source_label)
        else:
            process_generic_eew(data, source_key, source_label, data_type)
        return

    source_label = f"{source_key}.{data_type}"

    if data_type == 'jma':
        process_jma_eew(data, source_key, source_label)
    elif data_type == 'cenc':
        process_cenc_eew(data, source_key, source_label)
    elif data_type == 'sc':
        process_sc_eew(data, source_key, source_label)
    elif data_type == 'fj':
        process_fj_eew(data, source_key, source_label)
    elif data_type == 'cq':
        process_cq_eew(data, source_key, source_label)
    elif data_type == 'cea':
        process_cea_eew(data, source_key, source_label)
    elif data_type == 'cwa-eew':
        process_cwa_eew(data, source_key, source_label)
    elif data_type == 'cwa':
        process_cwa_report(data, source_key, source_label)
    elif data_type == 'yunnan':
        process_provincial_eew(data, source_key, source_label, '云南')
    elif data_type == 'ningxia':
        process_provincial_eew(data, source_key, source_label, '宁夏')
    elif data_type == 'guangxi':
        process_provincial_eew(data, source_key, source_label, '广西')
    elif data_type == 'shanxi':
        process_provincial_eew(data, source_key, source_label, '山西')
    elif data_type == 'beijing':
        process_provincial_eew(data, source_key, source_label, '北京')
    elif data_type == 'cea-pr':
        process_provincial_eew(data, source_key, source_label, '省级')
    elif data_type == 'hko':
        process_hko_eew(data, source_key, source_label)
    elif data_type == 'usgs':
        process_usgs_eew(data, source_key, source_label)
    else:
        if data and isinstance(data, dict):
            process_generic_eew(data, source_key, source_label, data_type)
        elif DEBUG:
            console.print(f"[dim]未处理的类型: {data_type} 来自 {source_key}[/dim]")


# ---------- P2P JSON API 专用处理函数 ----------
def process_p2p_quake(data):
    """
    处理 P2P JSON API 的地震信息 (code=551)
    支持两种数据来源：
    1. WebSocket 推送：顶层包含 id, issue, earthquake, points 等
    2. 历史接口：顶层也是完整的 JMAQuake 对象
    """
    try:
        # 从顶层提取基本字段
        quake_id = data.get('id') or data.get('_id')
        if not quake_id:
            if DEBUG:
                console.print("[dim]P2P 地震信息缺少 id，跳过[/dim]")
            return

        # 去重（基于 id）
        if quake_id in processed_events:
            if DEBUG:
                console.print(f"[dim]P2P 地震信息已处理过 (id={quake_id})，跳过[/dim]")
            return
        processed_events.add(quake_id)

        # 提取 issue 和 earthquake
        issue = data.get('issue', {})
        earthquake = data.get('earthquake', {})
        issue_type = issue.get('type', '')

        # 提取震源信息
        hypocenter = earthquake.get('hypocenter', {})
        max_scale = earthquake.get('maxScale', -1)
        max_intensity = scale_to_jma(max_scale)

        # 发震时刻：优先用 earthquake.time，否则用顶层 time
        origin_time = earthquake.get('time') or data.get('time', '')

        # 构建通用字段
        rows = []
        rows.append(["发震时刻", origin_time])
        rows.append(["震中位置", hypocenter.get('name', '未知')])
        lat = hypocenter.get('latitude')
        lon = hypocenter.get('longitude')
        if lat and lon and lat != -200 and lon != -200:
            rows.append(["坐标", f"{lat}, {lon}"])
            add_location_rows(rows, lat, lon, hypocenter.get('magnitude', -1))
        else:
            rows.append(["坐标", "不明"])
        rows.append(["深度(km)", hypocenter.get('depth', 'N/A')])

        # 处理不同类型的 551 消息
        if issue_type == 'ScalePrompt':
            # 震度速报：无震源详细信息，但有 points 区域列表
            rows.append(["最大震度", max_intensity])
            rows.append(["信息类型", "震度速报 (ScalePrompt)"])
            rows.append(["発表元", issue.get('source', 'N/A')])
            rows.append(["発表時刻", issue.get('time', 'N/A')])

            # 显示受影响区域
            points = data.get('points', [])
            if points:
                area_list = []
                for p in points[:10]:  # 最多显示10条
                    pref = p.get('pref', '')
                    addr = p.get('addr', '')
                    scale = scale_to_jma(p.get('scale', -1))
                    area_list.append(f"{pref} {addr} (震度{scale})")
                if len(points) > 10:
                    area_list.append(f"... 共 {len(points)} 个区域")
                rows.append(["受影响区域", '\n'.join(area_list)])
            else:
                rows.append(["受影响区域", "无"])

            title = "P2P 震度速报 (ScalePrompt)"

        elif issue_type in ('DetailScale', 'ScaleAndDestination', 'Destination'):
            # 详细地震信息
            rows.append(["最大震度", max_intensity])
            rows.append(["信息类型", issue_type])
            rows.append(["発表元", issue.get('source', 'N/A')])
            rows.append(["発表時刻", issue.get('time', 'N/A')])

            # 显示观测点震度列表
            points = data.get('points', [])
            if points:
                area_list = []
                for p in points[:10]:
                    pref = p.get('pref', '')
                    addr = p.get('addr', '')
                    scale = scale_to_jma(p.get('scale', -1))
                    area_list.append(f"{pref} {addr} (震度{scale})")
                if len(points) > 10:
                    area_list.append(f"... 共 {len(points)} 个观测点")
                rows.append(["震度观测点", '\n'.join(area_list)])
            else:
                rows.append(["震度观测点", "无"])

            # 津波信息
            domestic = earthquake.get('domesticTsunami', '')
            foreign = earthquake.get('foreignTsunami', '')
            if domestic:
                rows.append(["国内津波", domestic])
            if foreign:
                rows.append(["海外津波", foreign])

            title = "P2P 地震情報 (JMA)"

        else:
            # 其他类型（如 Foreign 等），通用处理
            rows.append(["最大震度", max_intensity])
            rows.append(["信息类型", issue_type or "不明"])
            rows.append(["発表元", issue.get('source', 'N/A')])
            rows.append(["発表時刻", issue.get('time', 'N/A')])
            title = f"P2P 地震情報 ({issue_type or 'Unknown'})"

        print_earthquake_table(title, rows, "P2P JSON API")
        dist = haversine(lat, lon, USER_LATITUDE, USER_LONGITUDE) if lat and lon and lat != -200 and lon != -200 and USER_LATITUDE else None
        if dist is not None:
            mag_val = hypocenter.get('magnitude', -1)
            origin_name = hypocenter.get('name', '未知')
            depth_val = hypocenter.get('depth')
            p_sec, s_sec = calc_wave_arrival(dist)
            local_int = estimate_local_intensity(mag_val, dist)
            trigger_alert("P2P", origin_name, mag_val, depth_val, dist,
                          local_int, None, origin_time, p_sec, s_sec, quake_id)
            if local_int and local_int > 0:
                start_countdown(f"p2p_{quake_id}", origin_time, dist, USER_LOCATION_NAME, mag_val, origin_name)

    except Exception as e:
        console.print(f"[red]P2P 地震处理异常: {e}[/red]")


def process_p2p_tsunami(data):
    """处理 P2P JSON API 的海啸预报 (code=552)"""
    try:
        if data.get('cancelled', False):
            console.print("[yellow]P2P 海啸预报已取消[/yellow]")
            return
        issue = data.get('issue', {})
        areas = data.get('areas', [])
        rows = []
        rows.append(["発表元", issue.get('source', 'N/A')])
        rows.append(["発表時刻", issue.get('time', 'N/A')])
        if not areas:
            rows.append(["予報区", "なし"])
        else:
            for area in areas:
                grade = area.get('grade', 'Unknown')
                name = area.get('name', '')
                immediate = area.get('immediate', False)
                max_height = area.get('maxHeight', {})
                height_desc = max_height.get('description', 'N/A')
                rows.append(["種別", grade])
                rows.append(["予報区", name])
                rows.append(["直ちに来襲", "はい" if immediate else "いいえ"])
                rows.append(["最大波高", height_desc])
        print_earthquake_table("P2P 津波予報", rows, "P2P JSON API")
        play_sound(SOUND_ALERT)
    except Exception as e:
        console.print(f"[red]P2P 海啸解析错误: {e}[/red]")


def process_p2p_eew(data):
    """处理 P2P JSON API 的紧急地震速报 (code=556)"""
    try:
        if data.get('cancelled', False):
            console.print("[yellow]P2P 紧急地震速报已取消[/yellow]")
            return
        quake = data.get('earthquake', {})
        issue = data.get('issue', {})
        areas = data.get('areas', [])
        rows = []
        rows.append(["発表時刻", issue.get('time', 'N/A')])
        rows.append(["イベントID", issue.get('eventId', 'N/A')])
        rows.append(["連番", issue.get('serial', 'N/A')])
        rows.append(["テスト", "はい" if data.get('test', False) else "いいえ"])

        if quake:
            hypocenter = quake.get('hypocenter', {})
            rows.append(["発震時刻", quake.get('originTime', 'N/A')])
            rows.append(["到達時刻", quake.get('arrivalTime', 'N/A')])
            rows.append(["震央地名", hypocenter.get('name', 'N/A')])
            rows.append(["短縮地名", hypocenter.get('reduceName', 'N/A')])
            rows.append(["緯度", hypocenter.get('latitude', 'N/A')])
            rows.append(["経度", hypocenter.get('longitude', 'N/A')])
            rows.append(["深さ(km)", hypocenter.get('depth', 'N/A')])
            rows.append(["マグニチュード", hypocenter.get('magnitude', 'N/A')])
        else:
            rows.append(["地震情報", "なし"])

        if areas:
            for area in areas:
                pref = area.get('pref', '')
                name = area.get('name', '')
                scale_from = scale_to_jma(area.get('scaleFrom', -1))
                scale_to = scale_to_jma(area.get('scaleTo', -1))
                kind = area.get('kindCode', '')
                rows.append([f"地域: {pref} {name}", f"予測震度: {scale_from}～{scale_to} (種別:{kind})"])
        else:
            rows.append(["予測地域", "なし"])

        print_earthquake_table("P2P 緊急地震速報", rows, "P2P JSON API")
        play_sound(SOUND_ALERT)
    except Exception as e:
        console.print(f"[red]P2P EEW 解析错误: {e}[/red]")


def process_p2p_userquake(data):
    """处理 P2P JSON API 的地震感知情報 (code=561)"""
    try:
        area_code = data.get('area', -1)
        rows = []
        rows.append(["地域コード", str(area_code)])
        rows.append(["受信時刻", data.get('time', 'N/A')])
        print_earthquake_table("P2P 地震感知情報", rows, "P2P JSON API")
        play_sound(SOUND_ALERT)
    except Exception as e:
        console.print(f"[red]P2P 感知情報解析错误: {e}[/red]")


# ---------- 气象预警 ----------
def process_weather_warning(data, source_key):
    try:
        rows = []
        rows.append(["预警标题", safe_get(data, 'title', 'headline')])
        rows.append(["预警类型", data.get('type', 'N/A')])
        rows.append(["生效时间", data.get('effective', 'N/A')])
        desc = data.get('description', '')
        rows.append(["预警内容", desc[:200] + ("..." if len(desc) > 200 else "")])
        lat = data.get('latitude')
        lon = data.get('longitude')
        rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])

        if rows:
            print_weather_table("气象预警 (中国气象局)", rows, SOURCE_DISPLAY.get(source_key, source_key))
            play_sound(SOUND_ALERT)
    except Exception as e:
        console.print(f"[red]气象预警解析错误: {e}[/red]")


def scale_to_jma(scale_code):
    scale_map = {
        -1: "不明",
        10: "1",
        20: "2",
        30: "3",
        40: "4",
        45: "5弱",
        50: "5強",
        55: "6弱",
        60: "6強",
        70: "7"
    }
    return scale_map.get(scale_code, "不明")


# ---------- EPSPClient (已弃用，保留但不启动) ----------
class EPSPClient:
    def __init__(self):
        self.servers = ['www.p2pquake.net', 'p2pquake.info', 'p2pquake.xyz', 'p2pquake.ddo.jp']
        self.port = 6910
        self.running = True
        self.sock = None
        self.peer_id = None
        self.region_code = 901
        self.connected_peers = {}
        self.lock = threading.Lock()
        self.server_index = 0
        self.recv_buffer = ""
        self.listener = None
        self.listener_thread = None
        self.max_connections = 20

    def start(self):
        pass


# ---------- P2P JSON API v2 WebSocket ----------
def on_p2pjson_message(ws, message):
    if not SOURCE_CONFIG.get('p2pjson', {}).get('enabled', True):
        return
    try:
        data = json.loads(message)
        if DEBUG:
            console.print(f"[dim]P2P JSON 原始数据: {data}[/dim]")

        # 标记连接成功（如果尚未标记）
        if ws_status.get('p2pjson') != 'connected':
            msg_type = data.get('type')
            if msg_type not in ('heartbeat', 'error', 'pong'):
                console.print("[green]P2P JSON API 已连接并接收数据[/green]")
                ws_status['p2pjson'] = 'connected'

        # 处理基于 type 的消息
        if 'type' in data:
            msg_type = data['type']
            if msg_type == 'welcome':
                console.print("[green]P2P JSON API 已连接[/green]")
                ws_status['p2pjson'] = 'connected'
            elif msg_type == 'heartbeat':
                if DEBUG:
                    console.print("[dim]P2P JSON 心跳[/dim]")
            elif msg_type == 'error':
                console.print(f"[red]P2P JSON 错误: {data.get('message', '未知错误')}[/red]")
            elif msg_type == 'earthquake':
                quake = data.get('earthquake', {})
                if quake:
                    # 构建完整对象传递给 process_p2p_quake
                    full_quake = {
                        'id': data.get('id'),
                        '_id': data.get('id'),
                        'earthquake': quake,
                        'issue': data.get('issue', {}),
                        'points': data.get('points', []),
                        'time': data.get('time', ''),
                        'comments': data.get('comments', {})
                    }
                    process_p2p_quake(full_quake)
            else:
                if DEBUG:
                    console.print(f"[dim]未知 P2P JSON 消息类型: {msg_type}[/dim]")
        # 处理基于 code 的消息
        elif 'code' in data:
            code = data.get('code')
            if code == 551:
                if DEBUG:
                    console.print("[dim]收到 P2P 地震信息 (code=551)[/dim]")
                # 直接传递整个 data 对象
                process_p2p_quake(data)
            elif code == 552:
                if DEBUG:
                    console.print("[dim]收到 P2P 海啸预报 (code=552)[/dim]")
                process_p2p_tsunami(data)
            elif code == 555:
                if DEBUG:
                    console.print("[dim]收到 P2P 感知信息/节点分布 (code=555)[/dim]")
            elif code == 556:
                if DEBUG:
                    console.print("[dim]收到 P2P 紧急地震速报 (code=556)[/dim]")
                process_p2p_eew(data)
            elif code == 561:
                if DEBUG:
                    console.print("[dim]收到 P2P 地震感知情報 (code=561)[/dim]")
                process_p2p_userquake(data)
            else:
                if DEBUG:
                    console.print(f"[dim]收到 P2P 未处理 code={code}[/dim]")
        else:
            if DEBUG:
                console.print("[dim]P2P JSON 未知格式消息[/dim]")
    except json.JSONDecodeError as e:
        console.print(f"[red]P2P JSON 解析错误: {e}[/red]")
    except Exception as e:
        console.print(f"[red]P2P JSON 处理异常: {e}[/red]")


def on_p2pjson_error(ws, error):
    if "429" in str(error):
        console.print("[red]P2P JSON 请求过于频繁 (429)，已启动退避重连[/red]")
    else:
        console.print(f"[red]P2P JSON WebSocket 错误: {error}[/red]")


def on_p2pjson_close(ws, close_status_code, close_msg):
    global p2pjson_reconnect_delay
    console.print("[yellow]P2P JSON 连接已关闭[/yellow]")
    if ws_running and SOURCE_CONFIG.get('p2pjson', {}).get('enabled', True):
        delay = p2pjson_reconnect_delay
        console.print(f"[dim]将在 {delay} 秒后尝试重连[/dim]")
        threading.Timer(delay, start_p2pjson_websocket).start()
        p2pjson_reconnect_delay = min(p2pjson_reconnect_delay * 2, 300)


def on_p2pjson_open(ws):
    global p2pjson_reconnect_delay
    p2pjson_reconnect_delay = 5
    console.print("[green]P2P JSON WebSocket 已连接，正在订阅...[/green]")
    subscribe_msg = '{"type":"subscribe","topic":"all"}'
    ws.send(subscribe_msg)
    if DEBUG:
        console.print(f"[dim]发送订阅: {subscribe_msg}[/dim]")


def start_p2pjson_websocket():
    if not WS_AVAILABLE:
        console.print("[red]websocket-client 未安装，无法启动 P2P JSON[/red]")
        return
    if not SOURCE_CONFIG.get('p2pjson', {}).get('enabled', True):
        return
    if DEBUG:
        console.print(f"[dim][DEBUG] P2P JSON WebSocket 开始连接...[/dim]")
    url = SOURCE_CONFIG['p2pjson']['url']
    try:
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            url,
            on_open=on_p2pjson_open,
            on_message=on_p2pjson_message,
            on_error=on_p2pjson_error,
            on_close=on_p2pjson_close
        )
        ws_connections['p2pjson'] = ws
        ws.run_forever()
    except Exception as e:
        console.print(f"[red]P2P JSON WebSocket 启动失败: {e}[/red]")
        if ws_running:
            time.sleep(5)
            start_p2pjson_websocket()


# ---------- NIED WebSocket ----------
def on_nied_message(ws, message):
    if not SOURCE_CONFIG.get('nied', {}).get('enabled', True):
        return
    try:
        data = json.loads(message)
        if DEBUG:
            console.print(f"[dim]NIED 原始数据: {data}[/dim]")
        msg_type = data.get('type')
        if msg_type == 'welcome':
            ws_status['nied'] = 'connected'
        elif msg_type == 'heartbeat':
            if DEBUG:
                console.print("[dim]NIED 心跳[/dim]")
        elif msg_type == 'update':
            inner_data = data.get('data')
            if not inner_data or not isinstance(inner_data, dict):
                if DEBUG:
                    console.print("[dim]NIED update 无有效数据，跳过[/dim]")
                return
            magunitude = inner_data.get('magunitude')
            region_name = inner_data.get('region_name')
            if (magunitude is None or magunitude == '' or magunitude == 'N/A') and \
                    (region_name is None or region_name == '' or region_name == '未知'):
                if DEBUG:
                    console.print(f"[dim]NIED 数据缺少震级或区域: mag={magunitude}, region={region_name}[/dim]")
                return
            report_id = inner_data.get('report_id')
            report_num = inner_data.get('report_num', '1')
            if report_id:
                report_key = f"nied_{report_id}_{report_num}"
            else:
                report_key = f"nied_{int(time.time())}"
            if report_key in processed_events:
                if DEBUG:
                    console.print(f"[dim]NIED 重复事件: {report_key}[/dim]")
                return
            processed_events.add(report_key)
            mapped = {
                "type": "jma",
                "EventID": report_id or f"NIED_{int(time.time())}",
                "OriginTime": inner_data.get('origin_time') or inner_data.get('report_time', ''),
                "Hypocenter": region_name or '未知地区',
                "Magunitude": magunitude if magunitude and magunitude != 'N/A' else 'N/A',
                "Depth": inner_data.get('depth', 'N/A'),
                "MaxIntensity": inner_data.get('calcintensity', 'N/A'),
                "isFinal": inner_data.get('is_final', False),
                "Latitude": float(inner_data['latitude']) if inner_data.get('latitude') and inner_data[
                    'latitude'] != 'N/A' else None,
                "Longitude": float(inner_data['longitude']) if inner_data.get('longitude') and inner_data[
                    'longitude'] != 'N/A' else None,
                "Accuracy": {},
                "WarnArea": [],
                "Serial": int(report_num) if report_num.isdigit() else 1
            }
            process_eew(mapped, 'nied')
        elif msg_type == 'pong':
            if DEBUG:
                console.print("[dim]NIED Pong 响应[/dim]")
        else:
            if DEBUG:
                console.print(f"[dim]NIED 未知消息类型: {msg_type}[/dim]")
    except json.JSONDecodeError as e:
        console.print(f"[red]NIED JSON 解析错误: {e}[/red]")
    except Exception as e:
        console.print(f"[red]NIED 处理异常: {e}[/red]")


def on_nied_error(ws, error):
    console.print(f"[red]NIED WebSocket 错误: {error}[/red]")


def on_nied_close(ws, close_status_code, close_msg):
    console.print("[yellow]NIED 连接已关闭，5秒后重连...[/yellow]")
    if ws_running and SOURCE_CONFIG.get('nied', {}).get('enabled', True):
        time.sleep(5)
        start_nied_websocket()


def on_nied_open(ws):
    console.print("[green]NIED WebSocket 已连接[/green]")
    ws_status['nied'] = 'connected'


def start_nied_websocket():
    if not WS_AVAILABLE:
        console.print("[red]websocket-client 未安装，无法启动 NIED[/red]")
        return
    if not SOURCE_CONFIG.get('nied', {}).get('enabled', True):
        return
    if DEBUG:
        console.print(f"[dim][DEBUG] NIED WebSocket 开始连接...[/dim]")
    url = SOURCE_CONFIG['nied']['url']
    try:
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            url,
            on_open=on_nied_open,
            on_message=on_nied_message,
            on_error=on_nied_error,
            on_close=on_nied_close
        )
        ws_connections['nied'] = ws
        ws.run_forever()
    except Exception as e:
        console.print(f"[red]NIED WebSocket 启动失败: {e}[/red]")
        if ws_running:
            time.sleep(5)
            start_nied_websocket()


# ---------- FAN Studio ----------
def on_fan_message(ws, message):
    if not SOURCE_CONFIG.get('fan', {}).get('enabled', True):
        return
    try:
        data = json.loads(message)
        if DEBUG:
            console.print(f"[dim]FAN 原始数据: {data}[/dim]")
        msg_type = data.get('type')
        if msg_type == 'initial_all' or msg_type == 'query_response':
            if DEBUG:
                console.print(f"[dim]FAN 快照消息 {msg_type} 已忽略，仅处理实时更新[/dim]")
        elif msg_type == 'update':
            source = data.get('source')
            if source:
                if source == 'weatheralarm':
                    item_data = data.get('Data')
                    if item_data and isinstance(item_data, dict):
                        process_weather_warning(item_data, 'fan')
                    return
                elif source == 'tsunami':
                    item_data = data.get('Data')
                    if item_data and isinstance(item_data, dict):
                        process_tsunami(item_data, source_label='FAN Studio (tsunami)')
                    return
                if source in FILTER_DETAIL.get('fan', {}):
                    if not FILTER_DETAIL['fan'][source]:
                        if DEBUG:
                            console.print(f"[dim]FAN 子源 {source} 已禁用，跳过更新[/dim]")
                        return
                item_data = data.get('Data')
                if item_data and isinstance(item_data, dict):
                    mapped_data = {
                        "type": source,
                        **item_data
                    }
                    process_eew(mapped_data, 'fan')
        elif msg_type == 'heartbeat':
            if DEBUG:
                console.print("[dim]FAN 心跳[/dim]")
        else:
            if DEBUG:
                console.print(f"[dim]FAN 未知消息类型: {msg_type}[/dim]")
    except json.JSONDecodeError as e:
        console.print(f"[red]FAN JSON 解析错误: {e}[/red]")
    except Exception as e:
        console.print(f"[red]FAN 处理异常: {e}[/red]")


def on_fan_error(ws, error):
    console.print(f"[red]FAN WebSocket 错误: {error}[/red]")


def on_fan_close(ws, close_status_code, close_msg):
    global fan_last_reconnect_time
    console.print("[yellow]FAN 连接已关闭[/yellow]")
    fan_last_reconnect_time = time.time()
    if ws_running and SOURCE_CONFIG.get('fan', {}).get('enabled', True):
        console.print(f"[dim]FAN 将在 {FAN_RECONNECT_DELAY // 60} 分钟后尝试重连[/dim]")
        threading.Timer(FAN_RECONNECT_DELAY, start_fan_websocket).start()


def on_fan_open(ws):
    console.print("[green]FAN Studio (地震) 已连接[/green]")
    ws_status['fan'] = 'connected'


def start_fan_websocket():
    global fan_last_reconnect_time
    if not WS_AVAILABLE:
        console.print("[red]websocket-client 未安装，无法启动 FAN[/red]")
        return
    if not SOURCE_CONFIG.get('fan', {}).get('enabled', True):
        return
    if DEBUG:
        console.print(f"[dim][DEBUG] FAN WebSocket 开始连接...[/dim]")
    elapsed = time.time() - fan_last_reconnect_time
    if elapsed < FAN_RECONNECT_DELAY and fan_last_reconnect_time > 0:
        remaining = int(FAN_RECONNECT_DELAY - elapsed)
        console.print(f"[yellow]FAN 重连冷却中，剩余 {remaining // 60} 分钟[/yellow]")
        return
    url = SOURCE_CONFIG['fan']['url']
    try:
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            url,
            on_open=on_fan_open,
            on_message=on_fan_message,
            on_error=on_fan_error,
            on_close=on_fan_close
        )
        ws_connections['fan'] = ws
        fan_last_reconnect_time = 0
        ws.run_forever()
    except Exception as e:
        console.print(f"[red]FAN WebSocket 启动失败: {e}[/red]")
        if ws_running:
            fan_last_reconnect_time = time.time()
            threading.Timer(FAN_RECONNECT_DELAY, start_fan_websocket).start()


# ---------- Wolfx WebSocket ----------
def on_message_factory(source_key):
    _heartbeat_shown = False
    def on_message(ws, message):
        nonlocal _heartbeat_shown
        if not SOURCE_CONFIG.get(source_key, {}).get('enabled', True):
            return
        try:
            data = json.loads(message)
            if not isinstance(data, dict):
                return
            msg_type = data.get('type', '')
            if msg_type == 'heartbeat':
                if not _heartbeat_shown:
                    _heartbeat_shown = True
                    ts = data.get('timestamp', 0)
                    if ts:
                        delay = abs(int(time.time() * 1000 - int(ts)))
                        console.print(f"\033[1A\033[K[green]{source_key} WebSocket 已连接 ({SOURCE_CONFIG[source_key]['name']}，延迟{delay}ms)[/green]")
                try:
                    ws.send("ping")
                except:
                    pass
                return
            if msg_type.endswith('_eew'):
                data['type'] = msg_type[:-4]
            if data.get('type') == 'cenc_eqlist':
                process_cenc_eqlist(data, source_key, f"{source_key}.{data.get('type')}")
                return
            if data.get('type') == 'jma_eqlist':
                process_jma_eqlist(data, source_key, f"{source_key}.{data.get('type')}")
                return
            if 'EventID' in data or 'event_id' in data:
                process_eew(data, source_key)
        except json.JSONDecodeError:
            pass
    return on_message


def on_error_factory(source_key):
    def on_error(ws, error):
        console.print(f"[red]{source_key} WebSocket 错误: {error}[/red]")
    return on_error


def on_close_factory(source_key):
    def on_close(ws, close_status_code, close_msg):
        console.print(f"[yellow]{source_key} 连接已关闭，5秒后重连...[/yellow]")
        if ws_running and SOURCE_CONFIG.get(source_key, {}).get('enabled', True):
            time.sleep(5)
            start_websocket(source_key)
    return on_close


def on_open_factory(source_key):
    def on_open(ws):
        console.print(f"[green]{source_key} WebSocket 已连接 ({SOURCE_CONFIG[source_key]['name']})[/green]")
        ws_status[source_key] = 'connected'
    return on_open


def start_websocket(source_key):
    if not WS_AVAILABLE:
        console.print(f"[red]websocket-client 未安装，无法启动 {source_key} WebSocket[/red]")
        return
    if not SOURCE_CONFIG.get(source_key, {}).get('enabled', True):
        return
    if DEBUG:
        console.print(f"[dim][DEBUG] {source_key} WebSocket 开始连接...[/dim]")
    url = SOURCE_CONFIG[source_key]['url']
    try:
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            url,
            on_open=on_open_factory(source_key),
            on_message=on_message_factory(source_key),
            on_error=on_error_factory(source_key),
            on_close=on_close_factory(source_key)
        )
        ws_connections[source_key] = ws
        ws.run_forever()
    except Exception as e:
        console.print(f"[red]{source_key} WebSocket 启动失败: {e}[/red]")
        if ws_running:
            time.sleep(5)
            start_websocket(source_key)


# ---------- 命令处理 ----------
def handle_command(cmd):
    global DEBUG, SOURCE_CONFIG, FILTER_DETAIL, EXPORT_ENABLED, EXPORT_FILE, EXPORT_FILE_PATH
    parts = cmd.split()
    if not parts:
        return
    if DEBUG:
        console.print(f"[dim][DEBUG] 收到命令: {cmd}[/dim]")

    def _stop_source(target):
        if target not in SOURCE_CONFIG:
            console.print(f"[yellow]未知数据源: {target}[/yellow]")
            return False
        if not SOURCE_CONFIG[target]['enabled']:
            console.print(f"[yellow]{target} 已经处于停用状态[/yellow]")
            return False
        SOURCE_CONFIG[target]['enabled'] = False
        console.print(f"[yellow]{target} 已停用[/yellow]")
        if target in ws_connections:
            try:
                ws_connections[target].close()
            except:
                pass
        if target == 'p2p' and 'epsp_client' in globals():
            epsp_client.running = False
            if epsp_client.sock:
                try:
                    epsp_client.sock.close()
                except:
                    pass
        return True

    def _enable_source(target):
        if target not in SOURCE_CONFIG:
            console.print(f"[yellow]未知数据源: {target}[/yellow]")
            return False
        if SOURCE_CONFIG[target]['enabled']:
            console.print(f"[yellow]{target} 已经处于启用状态[/yellow]")
            return False
        SOURCE_CONFIG[target]['enabled'] = True
        console.print(f"[green]{target} 已启用，正在连接...[/green]")
        if target == 'p2p':
            epsp_client.start()
        elif target == 'p2pjson':
            threading.Thread(target=start_p2pjson_websocket, daemon=True).start()
        elif target == 'nied':
            threading.Thread(target=start_nied_websocket, daemon=True).start()
        elif target == 'fan':
            threading.Thread(target=start_fan_websocket, daemon=True).start()
        else:
            threading.Thread(target=start_websocket, args=(target,), daemon=True).start()
        return True

    if parts[0] == 'help':
        console.print("[cyan]可用命令:[/cyan]")
        console.print("  test0                         - 模拟M1地震（汶川）")
        console.print("  test1                         - 模拟M3地震（汶川）")
        console.print("  test2                         - 模拟M6地震（汶川）")
        console.print("  test3                         - 模拟M8地震（汶川）")
        console.print("  test5                         - 模拟M5.1地震（印尼巴布亚）")
        console.print("  debug [on|off]                - 开启/关闭调试模式 (无参数则切换)")
        console.print("  export on/off                 - 开启/关闭表格导出到CSV")
        console.print("  export path <文件路径>         - 设置导出文件路径（相对或绝对路径）")
        console.print("  stop <source>                 - 停用数据源 (wolfx/p2p/p2pjson/nied/fan/all)")
        console.print("  stop <source>/<subtype>       - 停用子源 (如 stop fan/cenc)")
        console.print("  stop <source>/all             - 停用该数据源所有子源 (如 stop fan/all)")
        console.print("  enable <source>               - 启用数据源")
        console.print("  enable <source>/<subtype>     - 启用子源")
        console.print("  enable <source>/all           - 启用该数据源所有子源 (如 enable fan/all)")
        console.print("  restart <source>              - 重启数据源 (或 restart all)")
        console.print("  setup                         - 运行交互式配置向导")
        console.print("  status                        - 查看所有数据源状态")
        console.print("  list <n>                      - 获取并显示已启用的地震目录源，n 为条数(默认3)")
        console.print("  help                          - 显示此帮助")

        return

    elif parts[0] == 'test0':
        run_mock_test(1.0, 0)
        return
    elif parts[0] == 'test1':
        run_mock_test(4.0, 1)
        return
    elif parts[0] == 'test2':
        run_mock_test(6.0, 2)
        return
    elif parts[0] == 'test3':
        run_mock_test(8.0, 3)
        return
    elif parts[0] == 'test5':
        run_mock_test5()
        return

    elif parts[0] == 'debug':
        if len(parts) == 1:
            DEBUG = not DEBUG
            console.print(f"[dim]调试模式: {'开启' if DEBUG else '关闭'}[/dim]")
            save_config()
        elif len(parts) == 2:
            if parts[1] == 'on':
                DEBUG = True
                console.print("[dim]调试模式: 开启[/dim]")
                save_config()
            elif parts[1] == 'off':
                DEBUG = False
                console.print("[dim]调试模式: 关闭[/dim]")
                save_config()
            else:
                console.print("[yellow]用法: debug [on|off] 或 debug (切换)[/yellow]")
        return

    elif parts[0] == 'export':
        if len(parts) < 2:
            console.print("[yellow]用法: export on / export off / export path <文件路径>[/yellow]")
            return
        if parts[1] == 'on':
            EXPORT_ENABLED = True
            console.print("[green]表格导出已开启[/green]")
            if EXPORT_FILE_PATH:
                console.print(f"[dim]目标文件: {EXPORT_FILE_PATH}[/dim]")
            else:
                console.print("[dim]未指定路径，将自动生成文件名。使用 'export path <路径>' 设置。[/dim]")
        elif parts[1] == 'off':
            EXPORT_ENABLED = False
            if EXPORT_FILE:
                EXPORT_FILE.close()
                EXPORT_FILE = None
            console.print("[yellow]表格导出已关闭[/yellow]")
        elif parts[1] == 'path':
            if len(parts) < 3:
                console.print("[yellow]用法: export path <文件路径>[/yellow]")
                return
            raw_path = parts[2]
            if not os.path.isabs(raw_path):
                prog_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
                EXPORT_FILE_PATH = os.path.join(prog_dir, raw_path)
            else:
                EXPORT_FILE_PATH = raw_path
            save_config()
            if EXPORT_FILE:
                EXPORT_FILE.close()
                EXPORT_FILE = None
            console.print(f"[green]导出路径已设置为: {EXPORT_FILE_PATH} (已保存配置)[/green]")
        else:
            console.print("[yellow]参数错误，请用 on / off / path[/yellow]")
        return

    elif parts[0] == 'stop':
        if len(parts) < 2:
            console.print("[yellow]用法: stop <source> 或 stop <source>/<subtype>[/yellow]")
            return
        target = parts[1]
        if '/' in target:
            src, sub = target.split('/', 1)
            if src not in FILTER_DETAIL or src not in SOURCE_CONFIG:
                console.print(f"[yellow]未知数据源: {src}[/yellow]")
                return
            if sub == 'all':
                for key in FILTER_DETAIL[src]:
                    FILTER_DETAIL[src][key] = False
                console.print(f"[yellow]{src} 所有子源已停用[/yellow]")
                save_config()
                return
            else:
                if sub not in FILTER_DETAIL[src]:
                    console.print(f"[yellow]未知的子源: {target}[/yellow]")
                    return
                if not FILTER_DETAIL[src][sub]:
                    console.print(f"[yellow]{src}/{sub} 已经处于停用状态[/yellow]")
                    return
                FILTER_DETAIL[src][sub] = False
                console.print(f"[yellow]{src}/{sub} 已停用[/yellow]")
                save_config()
                return
        else:
            if target == 'all':
                for key in SOURCE_CONFIG:
                    _stop_source(key)
                save_config()
                return
            else:
                _stop_source(target)
                save_config()
                return

    elif parts[0] == 'enable':
        if len(parts) < 2:
            console.print("[yellow]用法: enable <source> 或 enable <source>/<subtype>[/yellow]")
            return
        target = parts[1]
        if '/' in target:
            src, sub = target.split('/', 1)
            if src not in FILTER_DETAIL or src not in SOURCE_CONFIG:
                console.print(f"[yellow]未知数据源: {src}[/yellow]")
                return
            if sub == 'all':
                for key in FILTER_DETAIL[src]:
                    FILTER_DETAIL[src][key] = True
                console.print(f"[green]{src} 所有子源已启用[/green]")
                save_config()
                return
            else:
                if sub not in FILTER_DETAIL[src]:
                    console.print(f"[yellow]未知的子源: {target}[/yellow]")
                    return
                if FILTER_DETAIL[src][sub]:
                    console.print(f"[yellow]{src}/{sub} 已经处于启用状态[/yellow]")
                    return
                FILTER_DETAIL[src][sub] = True
                console.print(f"[green]{src}/{sub} 已启用[/green]")
                save_config()
                return
        else:
            if target == 'all':
                for key in SOURCE_CONFIG:
                    _enable_source(key)
                save_config()
                return
            else:
                _enable_source(target)
                save_config()
                return

    elif parts[0] == 'restart':
        if len(parts) < 2:
            console.print("[yellow]用法: restart <source> 或 restart all[/yellow]")
            return
        target = parts[1]
        sources = list(SOURCE_CONFIG.keys()) if target == 'all' else [target]
        for src in sources:
            if src not in SOURCE_CONFIG:
                console.print(f"[yellow]未知数据源: {src}，跳过[/yellow]")
                continue
            if SOURCE_CONFIG[src]['enabled']:
                _stop_source(src)
            _enable_source(src)
        return

    elif parts[0] == 'map':
        if len(parts) > 1 and parts[1] == 'world':
            console.print(geo_ascii.WORLD_MAP)
        else:
            console.print(geo_ascii.CHINA_MAP)
        return

    elif parts[0] == 'list':
        count = 3
        if len(parts) > 1:
            try:
                count = max(1, int(parts[1]))
            except ValueError:
                console.print(f"[yellow]无效条数: {parts[1]}，使用默认 3 条[/yellow]")
        list_sources = ('cenc_eqlist', 'jma_eqlist')
        enabled_sources = [k for k, en in FILTER_DETAIL.get('wolfx', {}).items()
                           if en and k in list_sources and HTTP_URLS.get(k)]
        if not enabled_sources:
            console.print("[yellow]没有已启用的目录源 (cenc_eqlist/jma_eqlist)，请用 setup 或 enable wolfx/cenc_eqlist 开启[/yellow]")
            return
        for source_key in enabled_sources:
            url = HTTP_URLS.get(source_key)
            if not url:
                continue
            console.print(f"[cyan]正在获取 {SOURCE_DISPLAY.get(source_key, source_key)} 地震目录 (最近 {count} 条)...[/cyan]")
            try:
                response = requests.get(url, timeout=5)
            except Exception as e:
                console.print(f"[red]请求失败 ({source_key}): {e}[/red]")
                continue
            if response.status_code != 200:
                console.print(f"[red]请求失败 ({source_key}): HTTP {response.status_code}[/red]")
                continue
            try:
                data = response.json()
                if data and isinstance(data, dict):
                        if source_key == 'cenc_eqlist':
                            process_cenc_eqlist(data, 'wolfx', f"wolfx.{source_key}",
                                                send_notification=False, count=count, sound=False, compact=True)
                        elif source_key == 'jma_eqlist':
                            process_jma_eqlist(data, 'wolfx', f"wolfx.{source_key}",
                                               send_notification=False, count=count, sound=False, compact=True)
                else:
                    console.print(f"[red]处理失败 ({source_key}): 返回数据格式异常[/red]")
            except Exception as e:
                console.print(f"[red]处理失败 ({source_key}): {e}[/red]")
        return

    elif parts[0] == 'setup':
        setup_wizard()
        return

    elif parts[0] == 'status':
        console.print("[cyan]当前数据源状态:[/cyan]")
        for key, config in SOURCE_CONFIG.items():
            status = "[green]启用[/green]" if config['enabled'] else "[red]停用[/red]"
            conn_status = "[green]已连接[/green]" if ws_status.get(key) == 'connected' else "[yellow]未连接[/yellow]"
            remark = SOURCE_REMARKS.get(key)
            remark_str = f" ({remark})" if remark else ""
            console.print(f"  {config['name']} ({key}){remark_str}: {status} | {conn_status}")
            if key in FILTER_DETAIL and FILTER_DETAIL[key]:
                for sub, enabled in FILTER_DETAIL[key].items():
                    sub_status = "[green]启用[/green]" if enabled else "[red]停用[/red]"
                    sub_remark = SOURCE_REMARKS.get(sub)
                    sub_str = f" ({sub_remark})" if sub_remark else ""
                    console.print(f"    └─ {sub}{sub_str}: {sub_status}")
        return

    else:
        console.print(f"[yellow]未知命令: {cmd}[/yellow]")


# ---------- 模拟测试 ----------
def run_mock_test(magnitude, report_num):
    event_id = f"DEMO_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    data = {
        "type": "cenc",
        "EventID": event_id,
        "ReportNum": report_num,
        "OriginTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "HypoCenter": "汶川",
        "Latitude": 31.0,
        "Longitude": 103.4,
        "Magnitude": magnitude,
        "Depth": 10,
        "MaxIntensity": str(min(int(magnitude * 1.5), 12)),
        "isFinal": True,
    }
    process_eew(data, 'test')


def run_mock_test5():
    data = {
        "type": "cenc",
        "EventID": f"DEMO5_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "ReportNum": 1,
        "ReportTime": "2026-07-30 13:08:23",
        "OriginTime": "2026-07-30 12:42:12",
        "HypoCenter": "印尼巴布亚省",
        "Latitude": -2.95,
        "Longitude": 138.65,
        "Magnitude": 5.1,
        "Depth": 20,
        "MaxIntensity": "7",
        "isFinal": True,
    }
    process_eew(data, 'wolfx')


def check_user_command():
    if not WINDOWS:
        return None
    if msvcrt.kbhit():
        line = []
        while True:
            ch = msvcrt.getch()
            if ch == b'\x03':
                raise KeyboardInterrupt
            if ch == b'\r':
                msvcrt.putch(b'\r')
                msvcrt.putch(b'\n')
                break
            elif ch == b'\x08':
                if line:
                    line.pop()
                    msvcrt.putch(b'\x08')
                    msvcrt.putch(b' ')
                    msvcrt.putch(b'\x08')
            else:
                if 32 <= ch[0] <= 126:
                    line.append(ch.decode('ascii'))
                    msvcrt.putch(ch)
        raw = ''.join(line).strip()
        if not raw:
            return None
        return raw.lower()
    return None


# ================== 主程序 ==================
def main():
    global ws_running, epsp_client, EXPORT_FILE, EXPORT_FILE_PATH

    if not WS_AVAILABLE:
        console.print("[red]错误: websocket-client 未安装，WebSocket 数据源将不可用[/red]")

    console.print("\n[bold yellow]========== EEW-CLI-Monitor ==========[/bold yellow]")
    console.print(Panel(
        "本工具是一个非官方项目，与任何国家或地区的政府机构、气象机构或地震相关机构均无隶属或合作关系。本服务提供的信息仅供参考，不能替代官方地震预警、灾害信息、疏散信息或其他官方警报渠道。灾害发生时，请务必以相关官方机构发布的最新信息为准。",
        title="声明",
        border_style="yellow",
        box=box.ROUNDED,
        expand=False
    ))
    if not os.path.exists(SOUND_ALERT):
        console.print("[yellow]提示: 普通提示音文件未找到，将无法播放。[/yellow]")
    config, config_found = load_config()
    if not config_found:
        console.print("\n[bold red]未找到 config.json 配置文件[/bold red]")
        console.print("[yellow]请输入 [bold]setup[/bold] 启动交互式配置向导[/yellow]")
        apply_config(config)
        while True:
            if WINDOWS:
                cmd = check_user_command()
                if cmd:
                    if cmd == 'setup':
                        setup_wizard()
                        break
                    else:
                        console.print("[yellow]请先输入 setup 完成配置[/yellow]")
            time.sleep(0.1)
        config, config_found = load_config()
    apply_config(config)

    # ---------- 配置通报 ----------
    loc_name = USER_LOCATION_NAME or "未设置"
    loc_str = f"({USER_LATITUDE:.4f}, {USER_LONGITUDE:.4f})" if USER_LATITUDE and USER_LONGITUDE else ""
    console.print(f"\n[bold]========== 配置通报 ==========[/bold]")
    console.print(f"位置:      {loc_name} {loc_str}")
    console.print(f"调试模式:  {'开启' if DEBUG else '关闭'}")
    console.print(f"导出路径:  {EXPORT_FILE_PATH if EXPORT_FILE_PATH else '未设置'}")

    bark_txt = ALERT_BARK_URL if ALERT_BARK_URL else "未设置"
    console.print(f"Bark地址:  {bark_txt}")

    ns_txt = f"开启 (≥M{NO_SENSATION_MAG_THRESHOLD})" if NO_SENSATION_REPORT else '关闭'
    console.print(f"无震感地震通报:  {ns_txt}")

    if ALERT_TIERS:
        console.print(f"\n预警分级:")
        for key in sorted(ALERT_TIERS.keys()):
            tc = ALERT_TIERS[key]
            lo = tc.get('min', '?')
            hi = tc.get('max', '∞')
            win = '开' if tc.get('windows', True) else '关'
            bark = '开' if tc.get('bark', True) else '关'
            console.print(f"  {key}    {lo}≤烈度<{hi}  Windows:{win}  Bark:{bark}")
    else:
        console.print(f"\n预警分级:  未配置")

    console.print(f"\n数据源:")
    for key, src_cfg in SOURCE_CONFIG.items():
        status = "[green]启用[/green]" if src_cfg['enabled'] else "[red]停用[/red]"
        conn_status = "[green]已连接[/green]" if ws_status.get(key) == 'connected' else "[yellow]未连接[/yellow]"
        remark = SOURCE_REMARKS.get(key)
        remark_str = f" ({remark})" if remark else ""
        console.print(f"  {src_cfg['name']} ({key}){remark_str}: {status} | {conn_status}")
        if key in FILTER_DETAIL and FILTER_DETAIL[key]:
            for sub, enabled in FILTER_DETAIL[key].items():
                sub_status = "[green]启用[/green]" if enabled else "[red]停用[/red]"
                sub_remark = SOURCE_REMARKS.get(sub)
                sub_str = f" ({sub_remark})" if sub_remark else ""
                console.print(f"    └─ {sub}{sub_str}: {sub_status}")
    console.print(f"[bold]==============================[/bold]\n")

    if SOURCE_CONFIG.get('wolfx', {}).get('enabled', False):
        ws_status['wolfx'] = 'connecting'
        threading.Thread(target=start_websocket, args=('wolfx',), daemon=True).start()
        time.sleep(1)

    if SOURCE_CONFIG.get('p2pjson', {}).get('enabled', False):
        ws_status['p2pjson'] = 'connecting'
        threading.Thread(target=start_p2pjson_websocket, daemon=True).start()
        time.sleep(1)

    if SOURCE_CONFIG.get('fan', {}).get('enabled', False):
        ws_status['fan'] = 'connecting'
        threading.Thread(target=start_fan_websocket, daemon=True).start()
        time.sleep(1)

    if SOURCE_CONFIG.get('nied', {}).get('enabled', False):
        ws_status['nied'] = 'connecting'
        threading.Thread(target=start_nied_websocket, daemon=True).start()
        time.sleep(1)

    epsp_client = EPSPClient()
    if SOURCE_CONFIG['p2p']['enabled']:
        ws_status['p2p'] = 'connecting'
        epsp_client.start()

    try:
        while True:
            if WINDOWS:
                cmd = check_user_command()
                if cmd:
                    handle_command(cmd)
            time.sleep(0.1)
    except KeyboardInterrupt:
        ws_running = False
        if 'epsp_client' in globals():
            epsp_client.running = False
        if EXPORT_FILE:
            EXPORT_FILE.close()
        console.print("\n[bold red]程序已退出，感谢使用！[/bold red]")
        sys.exit(0)


if __name__ == "__main__":
    main()
