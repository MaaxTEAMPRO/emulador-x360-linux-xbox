#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════╗
║           VOLANTE VIRTUAL - Windows 10               ║
║   Giroscópio do celular -> Xbox 360 virtual          ║
╠══════════════════════════════════════════════════════╣
║  pip install vgamepad websockets cryptography        ║
║  pip install pywinusb                                ║
║  Driver ViGEmBus: github.com/ViGEm/ViGEmBus/releases ║
╚══════════════════════════════════════════════════════╝
"""

import tkinter as tk
from tkinter import ttk
import asyncio, json, ssl, socket, os, sys, threading, time, ctypes
from ctypes import wintypes as W
from http.server import HTTPServer, SimpleHTTPRequestHandler
from datetime import datetime, timezone, timedelta

# ════════════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════════════
WSS_PORT   = 8765
HTTPS_PORT = 8443
CERT_FILE  = "cert.pem"
KEY_FILE   = "key.pem"
MAX_ANGLE  = 60
ANTI_DZ    = 0 # usar escala com zero ponto na frente, tipo: 0.10 ou 0.18 pro ACE
SMOOTHING  = 0.55
UPDATE_HZ  = 50
ACCEL_TIME = 1.1
BRAKE_TIME = 1.6
LEARN_SEC  = 3.0

# ════════════════════════════════════════════════════════════════════
#  OPTIONAL DEPS
# ════════════════════════════════════════════════════════════════════
VGAMEPAD_OK = False
_vg_err = ""
try:
    import vgamepad as vg
    VGAMEPAD_OK = True
except Exception as ex:
    _vg_err = str(ex)

CRYPTO_OK = False
try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    CRYPTO_OK = True
except Exception:
    pass

WS_OK = False
try:
    import websockets
    WS_OK = True
except Exception:
    pass

RAW_OK = False
try:
    import pywinusb.hid as pyhid
    RAW_OK = True
except Exception:
    pass

# ════════════════════════════════════════════════════════════════════
#  RAW INPUT — abre TODOS os HID não-Xbox/teclado, como teste_rawinput.py
# ════════════════════════════════════════════════════════════════════

# VIDs cujo driver (XInput/etc) intercepta HID antes de chegar ao pywinusb
_XINPUT_VIDS  = {0x045E, 0x0738, 0x0E6F, 0x0F0D, 0x1532, 0x24C6}
_IGNORE_NAMES = ("keyboard", "teclado", "mouse", "consumer control",
                 "audio", "headset", "headphone", "microphone")

raw_devs          = []      # todos os devices HID abertos
raw_dev           = None    # alias → o último device aberto (compat)
raw_axes          = [0.5] * 8
raw_buttons       = 0
raw_buttons_state = 0       # alias de raw_buttons
raw_last_raw      = []      # último array cru (para debug no monitor)
raw_lock          = threading.Lock()


def raw_handler(data):
    """
    Layout real do ShanWan / HID-compliant game controller observado:
      idx  0    1    2    3    4    5    6    7    8    9   10
           ID   LX   LY   RX   RY  HAT1  ?  BTN1 HAT2 BTN2  ?

      arr[1..4] = eixos analógicos (0-255, centro=128)
      arr[5]    = HAT/POV (255=neutro, 0-7=direção) — NÃO é botão
      arr[7]    = botões byte 1 (bitmask)
      arr[8]    = HAT2 / valor extra (255=neutro) — NÃO é botão
      arr[9]    = botões byte 2 (bitmask); se == 255 é HAT, ignorar
      arr[10]   = botões byte 3 (bitmask)
    """
    global raw_axes, raw_buttons, raw_buttons_state, raw_last_raw
    try:
        arr = list(data)
        if len(arr) < 8:
            return
        with raw_lock:
            raw_last_raw = arr[:]

            # Eixos analógicos 0..1
            raw_axes[0] = arr[1] / 255.0   # LX
            raw_axes[1] = arr[2] / 255.0   # LY
            raw_axes[2] = arr[3] / 255.0   # RX
            raw_axes[3] = arr[4] / 255.0   # RY

            # Botões
            b1 = int(arr[7])
            # arr[9]=255 é HAT/POV neutro, não botão
            b2 = int(arr[9])  if len(arr) > 9  and arr[9] != 255 else 0
            b3 = int(arr[10]) if len(arr) > 10 else 0

            raw_buttons       = b1 | (b2 << 8) | (b3 << 16)
            raw_buttons_state = raw_buttons
    except Exception:
        pass


def start_rawinput():
    """
    Estratégia idêntica ao teste_rawinput.py:
    abrir TODOS os dispositivos HID que não são Xbox/teclado/mouse/consumer.
    O handler é o mesmo para todos — o controle que enviar dados preencherá os globals.
    """
    global raw_devs, raw_dev
    if not RAW_OK:
        return False

    stop_rawinput()

    try:
        all_devs = pyhid.HidDeviceFilter().get_devices()
    except Exception as e:
        _log_cb(f"Erro ao listar HID: {e}")
        return False

    _log_cb(f"HID: {len(all_devs)} dispositivos encontrados")
    opened = []

    for d in all_devs:
        name = (getattr(d, "product_name", "") or "").lower()
        vid  = getattr(d, "vendor_id", 0)
        pid  = getattr(d, "product_id", 0)
        disp = getattr(d, "product_name", "?") or "?"
        _log_cb(f"  VID:{vid:04X} PID:{pid:04X}  {disp!r}")

        # Pular Xbox (usa XInput, HID cru não funciona)
        if vid in _XINPUT_VIDS:
            _log_cb(f"    -> ignorado (VID Xbox/XInput)")
            continue
        # Pular teclados, mouses, consumer control
        if any(k in name for k in _IGNORE_NAMES):
            _log_cb(f"    -> ignorado (teclado/mouse/consumer)")
            continue

        try:
            d.open()
            d.set_raw_data_handler(raw_handler)
            opened.append(d)
            _log_cb(f"    -> ABERTO")
        except Exception as e:
            _log_cb(f"    -> falhou: {e}")

    if not opened:
        _log_cb("Nenhum dispositivo HID de controle pôde ser aberto.")
        return False

    raw_devs = opened
    raw_dev  = opened[-1]
    _log_cb(f"RAW: {len(opened)} dispositivo(s) monitorado(s)")
    return True


def stop_rawinput():
    global raw_devs, raw_dev
    for d in raw_devs:
        try:
            d.close()
        except Exception:
            pass
    raw_devs = []
    raw_dev  = None

# ════════════════════════════════════════════════════════════════════
#  JOYSTICK LAYER (XInput + WinMM — fallbacks)
# ════════════════════════════════════════════════════════════════════
_xi = None
for _dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
    try:
        _xi = ctypes.WinDLL(_dll)
        break
    except Exception:
        pass

class _XGP(ctypes.Structure):
    _fields_ = [("wButtons", W.WORD), ("bLT", ctypes.c_ubyte), ("bRT", ctypes.c_ubyte),
                ("sLX", ctypes.c_short), ("sLY", ctypes.c_short),
                ("sRX", ctypes.c_short), ("sRY", ctypes.c_short)]

class _XSTATE(ctypes.Structure):
    _fields_ = [("pkt", W.DWORD), ("gp", _XGP)]

def _xi_scan():
    if not _xi:
        return []
    out = []
    st  = _XSTATE()
    for i in range(4):
        if _xi.XInputGetState(i, ctypes.byref(st)) == 0:
            out.append({"api": "xinput", "id": i,
                        "label": f"[XInput] Controle #{i+1}"})
    return out

def _xi_read(dev):
    if not _xi:
        return None
    st = _XSTATE()
    if _xi.XInputGetState(dev["id"], ctypes.byref(st)) != 0:
        return None
    g = st.gp
    return {"axes": {"LT": g.bLT / 255.0, "RT": g.bRT / 255.0,
                     "LX": max(-1.0, g.sLX / 32767.0), "LY": max(-1.0, g.sLY / 32767.0),
                     "RX": max(-1.0, g.sRX / 32767.0), "RY": max(-1.0, g.sRY / 32767.0)},
            "buttons": g.wButtons}

_winmm   = ctypes.WinDLL("winmm")
_MM_AXES = ["X", "Y", "Z", "R", "U", "V"]

class _JOYCAPS(ctypes.Structure):
    _fields_ = [
        ("wMid", W.WORD), ("wPid", W.WORD), ("szPname", ctypes.c_char * 32),
        ("wXmin", W.UINT), ("wXmax", W.UINT), ("wYmin", W.UINT), ("wYmax", W.UINT),
        ("wZmin", W.UINT), ("wZmax", W.UINT), ("wNumButtons", W.UINT),
        ("wPeriodMin", W.UINT), ("wPeriodMax", W.UINT),
        ("wRmin", W.UINT), ("wRmax", W.UINT), ("wUmin", W.UINT), ("wUmax", W.UINT),
        ("wVmin", W.UINT), ("wVmax", W.UINT), ("wCaps", W.UINT),
        ("wMaxAxes", W.UINT), ("wNumAxes", W.UINT), ("wMaxButtons", W.UINT),
        ("szRegKey", ctypes.c_char * 32), ("szOEMVxD", ctypes.c_char * 260),
    ]

class _JOYINFOEX(ctypes.Structure):
    _fields_ = [
        ("dwSize", W.DWORD), ("dwFlags", W.DWORD),
        ("dwXpos", W.DWORD), ("dwYpos", W.DWORD), ("dwZpos", W.DWORD),
        ("dwRpos", W.DWORD), ("dwUpos", W.DWORD), ("dwVpos", W.DWORD),
        ("dwButtons", W.DWORD), ("dwButtonNumber", W.DWORD), ("dwPOV", W.DWORD),
        ("dwR1", W.DWORD), ("dwR2", W.DWORD),
    ]

def _mm_scan():
    out = []
    caps = _JOYCAPS()
    for i in range(16):
        if _winmm.joyGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            nm = caps.szPname.decode("utf-8", "replace").rstrip("\x00")
            out.append({"api": "winmm", "id": i, "label": f"[Legacy] {nm}"})
    return out

def _mm_read(dev):
    info = _JOYINFOEX()
    info.dwSize  = ctypes.sizeof(info)
    info.dwFlags = 0xFF
    if _winmm.joyGetPosEx(dev["id"], ctypes.byref(info)) != 0:
        return None
    caps = _JOYCAPS()
    _winmm.joyGetDevCapsW(dev["id"], ctypes.byref(caps), ctypes.sizeof(caps))
    lo = [caps.wXmin, caps.wYmin, caps.wZmin, caps.wRmin, caps.wUmin, caps.wVmin]
    hi = [caps.wXmax, caps.wYmax, caps.wZmax, caps.wRmax, caps.wUmax, caps.wVmax]
    rv = [info.dwXpos, info.dwYpos, info.dwZpos,
          info.dwRpos, info.dwUpos, info.dwVpos]
    axes = {n: (r - l) / max(h - l, 1)
            for n, l, h, r in zip(_MM_AXES, lo, hi, rv)}
    return {"axes": axes, "buttons": info.dwButtons}

def joy_scan():
    out = []
    if RAW_OK and raw_devs:
        # Mostra um único item "RAW" agregado
        names = ", ".join(
            getattr(d, "product_name", "?") or "?" for d in raw_devs
        )
        out.append({"api": "raw", "id": "raw0",
                    "label": f"[RAW] {names}"})
    out += _xi_scan() + _mm_scan()
    return out

def joy_read(dev):
    if not dev:
        return None
    api = dev.get("api")
    if api == "raw":
        with raw_lock:
            return {"axes": {f"A{i}": raw_axes[i] for i in range(6)},
                    "buttons": raw_buttons_state}
    if api == "xinput":
        return _xi_read(dev)
    if api == "winmm":
        return _mm_read(dev)
    return None

# ════════════════════════════════════════════════════════════════════
#  GLOBAL STATE
# ════════════════════════════════════════════════════════════════════
gamepad           = None
steer_float       = 0.0
target_gas        = 0.0
target_brake      = 0.0
throttle_lim      = 1.0
brake_lim         = 1.0
accel_ramp        = ACCEL_TIME
brake_ramp        = BRAKE_TIME
phys_dev          = None

# Mapeamento de gas/freio: pode ser eixo (string) ou botão (int bitmask)
gas_axis_idx      = -1    # índice em raw_axes, ou -1 se não mapeado
brake_axis_idx    = -1
gas_button_mask   = 0     # bitmask se mapeado a botão
brake_button_mask = 0
gas_label         = "--"
brake_label       = "--"

_log_cb = print
BTN_MAP = {}

def _init_btn_map():
    global BTN_MAP
    if not VGAMEPAD_OK:
        return
    BTN_MAP = {
        "A":      vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
        "B":      vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
        "X":      vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
        "Y":      vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
        "LB":     vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
        "RB":     vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
        "start":  vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
        "select": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
        "up":     vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
        "down":   vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
        "left":   vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
        "right":  vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
        "L3":     vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
        "R3":     vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
    }

# ════════════════════════════════════════════════════════════════════
#  SSL
# ════════════════════════════════════════════════════════════════════
def ensure_cert():
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return True
    if not CRYPTO_OK:
        return False
    key  = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "volante")])
    now  = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + timedelta(days=730))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    with open(KEY_FILE, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption()))
    with open(CERT_FILE, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    return True

# ════════════════════════════════════════════════════════════════════
#  HTTP
# ════════════════════════════════════════════════════════════════════
class _QH(SimpleHTTPRequestHandler):
    def log_message(self, *_): pass
    def log_error(self, *_):   pass

def _run_https(ssl_ctx):
    srv = HTTPServer(("0.0.0.0", HTTPS_PORT), _QH)
    srv.socket = ssl_ctx.wrap_socket(srv.socket, server_side=True)
    srv.serve_forever()

# ════════════════════════════════════════════════════════════════════
#  PHYSICAL CONTROLLER THREAD
# ════════════════════════════════════════════════════════════════════
def _phys_thread():
    global target_gas, target_brake
    while True:
        time.sleep(1.0 / UPDATE_HZ)
        try:
            # Botões têm prioridade; fallback para eixos
            if gas_button_mask or brake_button_mask:
                with raw_lock:
                    btns = raw_buttons_state
                if gas_button_mask:
                    target_gas   = 255.0 if (btns & gas_button_mask) else 0.0
                if brake_button_mask:
                    target_brake = 255.0 if (btns & brake_button_mask) else 0.0

            if gas_axis_idx >= 0 or brake_axis_idx >= 0:
                with raw_lock:
                    axes = list(raw_axes)
                if gas_axis_idx >= 0:
                    g = abs(axes[gas_axis_idx] - 0.5) * 2.0  # centro=0, borda=1
                    # tenta eixo unipolar também (0..1)
                    g = max(g, axes[gas_axis_idx]) if axes[gas_axis_idx] > 0.55 else g
                    target_gas   = g * 255.0 if g > 0.03 else 0.0
                if brake_axis_idx >= 0:
                    b = abs(axes[brake_axis_idx] - 0.5) * 2.0
                    b = max(b, axes[brake_axis_idx]) if axes[brake_axis_idx] > 0.55 else b
                    target_brake = b * 255.0 if b > 0.03 else 0.0
        except Exception:
            pass

# ════════════════════════════════════════════════════════════════════
#  GAMEPAD OUTPUT
# ════════════════════════════════════════════════════════════════════
async def _gamepad_loop():
    cg = cb = 0.0
    dt = 1.0 / UPDATE_HZ
    def _ramp(cur, tgt, r):
        if r <= 0: return tgt
        step = 255.0 / (r / dt)
        return min(tgt, cur + step) if tgt > cur else max(tgt, cur - step * 3)
    while True:
        cg = _ramp(cg, target_gas   * throttle_lim, accel_ramp)
        cb = _ramp(cb, target_brake * brake_lim,    brake_ramp)
        if gamepad:
            try:
                gamepad.left_joystick_float(x_value_float=steer_float, y_value_float=0.0)
                gamepad.right_trigger(value=int(cg))
                gamepad.left_trigger(value=int(cb))
                gamepad.update()
            except Exception:
                pass
        await asyncio.sleep(dt)

# ════════════════════════════════════════════════════════════════════
#  WEBSOCKET
# ════════════════════════════════════════════════════════════════════
def _parse_beta(v):
    try: return max(-180.0, min(180.0, float(v) if v is not None else 0.0))
    except: return None

async def _ws_handler(ws, path=None):
    global steer_float, target_gas, target_brake
    global throttle_lim, brake_lim, accel_ramp, brake_ramp
    peer = getattr(ws, "remote_address", ("?",))[0]

    # Estado por conexão
    zero = 0.0; calibrated = False; smooth = 0.0; inv = False
    max_angle = MAX_ANGLE   # pode ser sobrescrito por msg max_angle

    # Estado do right stick (rs_up/down/left/right)
    rs_x = 0.0; rs_y = 0.0

    _log_cb(f"Conectado: {peer}")
    try:
        async for raw in ws:
            try: data = json.loads(raw)
            except: continue
            t = data.get("type")

            if t == "calibrate":
                zero = _parse_beta(data.get("beta")) or 0.0
                calibrated = True; inv = zero < 0; smooth = steer_float = 0.0
                _log_cb(f"Zero={zero:.1f} deg{' (inv)' if inv else ''}")

            elif t == "wheel" and calibrated:
                beta = _parse_beta(data.get("beta"))
                if beta is None: continue
                angle = (beta - zero + 180) % 360 - 180
                if inv: angle = -angle
                smooth = SMOOTHING * smooth + (1 - SMOOTHING) * angle
                c = max(-max_angle, min(max_angle, smooth))
                n = abs(c) / max_angle
                if n > 0: n = ANTI_DZ + n * (1 - ANTI_DZ)
                steer_float = n * (-1 if c < 0 else 1)

            elif t == "button":
                btn = data.get("btn"); pressed = data.get("pressed")
                value = data.get("value", 0)

                if btn == "gas":
                    target_gas   = 255.0 if value else 0.0
                elif btn == "brake":
                    target_brake = 255.0 if value else 0.0

                # Right-stick directions (rs_up/down/left/right)
                elif btn in ("rs_up", "rs_down", "rs_left", "rs_right") and gamepad:
                    p = bool(pressed)
                    if btn == "rs_up":    rs_y = -1.0 if p else 0.0
                    elif btn == "rs_down":  rs_y =  1.0 if p else 0.0
                    elif btn == "rs_left":  rs_x = -1.0 if p else 0.0
                    elif btn == "rs_right": rs_x =  1.0 if p else 0.0
                    try:
                        gamepad.right_joystick_float(x_value_float=rs_x,
                                                     y_value_float=rs_y)
                        gamepad.update()
                    except Exception:
                        pass

                elif gamepad and btn in BTN_MAP and pressed is not None:
                    if pressed: gamepad.press_button(button=BTN_MAP[btn])
                    else:       gamepad.release_button(button=BTN_MAP[btn])

            elif t == "max_angle":
                try:
                    max_angle = max(10, int(data.get("value", MAX_ANGLE)))
                except Exception:
                    pass

            elif t == "throttle_limit":
                throttle_lim = max(0.0, min(1.0, float(data.get("value", 1.0))))
            elif t == "brake_limit":
                brake_lim    = max(0.0, min(1.0, float(data.get("value", 1.0))))

            # Nomes vindos do controller.html (antigo e atual)
            elif t in ("accel_time", "tcs_mode"):
                v = float(data.get("value", ACCEL_TIME))
                accel_ramp = max(0.0, v)
            elif t in ("brake_time", "brake_mode"):
                v = float(data.get("value", BRAKE_TIME))
                brake_ramp = max(0.0, v)

    except Exception:
        pass
    finally:
        steer_float = 0.0
        _log_cb(f"Desconectado: {peer}")

_aloop = None
def _run_async(ssl_ctx):
    global _aloop
    _aloop = asyncio.new_event_loop()
    asyncio.set_event_loop(_aloop)
    _aloop.run_until_complete(_async_main(ssl_ctx))

async def _async_main(ssl_ctx):
    asyncio.create_task(_gamepad_loop())
    async with websockets.serve(_ws_handler, "0.0.0.0", WSS_PORT, ssl=ssl_ctx,
                                ping_interval=20, ping_timeout=20, close_timeout=5):
        _log_cb(f"WebSocket wss://:{WSS_PORT}")
        await asyncio.Future()

def _get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# ════════════════════════════════════════════════════════════════════
#  GUI
# ════════════════════════════════════════════════════════════════════
class App(tk.Tk):
    BG   = "#0a0a0a"; CARD = "#111111"; ACC = "#ff3c5f"
    GRN  = "#00e5a0"; YEL  = "#f1c40f"; DIM = "#555555"
    FG   = "#e8e8e8"; RED  = "#e74c3c"

    def __init__(self):
        super().__init__()
        self.title("Volante Virtual")
        self.geometry("590x700")
        self.resizable(False, False)
        self.configure(bg=self.BG)
        self._joy_list   = []
        self._learn_mode = None
        self._build_ui()

        global _log_cb, gamepad
        _log_cb = self._log
        _init_btn_map()

        if VGAMEPAD_OK:
            try:
                gamepad = vg.VX360Gamepad()
                self._log("OK Xbox 360 virtual criado")
            except Exception as ex:
                self._log(f"ERRO ViGEmBus: {ex}")
                self._log("   -> github.com/ViGEm/ViGEmBus/releases")
        else:
            self._log(f"AVISO vgamepad nao instalado: {_vg_err}")

        if not WS_OK:     self._log("AVISO pip install websockets")
        if not CRYPTO_OK: self._log("AVISO pip install cryptography")
        if not RAW_OK:    self._log("AVISO pip install pywinusb")

        os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))
        self._start_servers()

        if RAW_OK:
            if start_rawinput():
                self._log("RAWInput iniciado com sucesso")
            else:
                self._log("RAWInput: conecte o controle e clique Buscar")

        self._scan_joysticks()
        threading.Thread(target=_phys_thread, daemon=True).start()
        self._axis_monitor()

    def _build_ui(self):
        BG = self.BG; CARD = self.CARD; ACC = self.ACC
        GRN = self.GRN; DIM = self.DIM; FG = self.FG; YEL = self.YEL

        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text="VOLANTE VIRTUAL", font=("Courier New", 15, "bold"),
                 bg=BG, fg=ACC).pack(side="left")
        self._dot = tk.Label(hdr, text="●", font=("Courier New", 14), bg=BG, fg="#333")
        self._dot.pack(side="right")

        uc = tk.Frame(self, bg=CARD, pady=10, padx=14)
        uc.pack(fill="x", padx=16, pady=4)
        tk.Label(uc, text="ABRA NO CELULAR  (paisagem - tela para cima)",
                 font=("Courier New", 8), bg=CARD, fg=DIM).pack(anchor="w")
        self._url = tk.StringVar(value="aguardando...")
        tk.Entry(uc, textvariable=self._url, font=("Courier New", 11, "bold"),
                 bg="#1a1a1a", fg=YEL, relief="flat",
                 readonlybackground="#1a1a1a", state="readonly").pack(fill="x", pady=(3, 0))
        tk.Button(uc, text="Copiar", command=self._copy_url,
                  bg=CARD, fg=DIM, relief="flat", font=("Courier New", 8),
                  activebackground=CARD, cursor="hand2").pack(anchor="e")

        cf = tk.LabelFrame(self, text="  CONTROLE FISICO  ",
                           font=("Courier New", 9, "bold"), bg=BG, fg=FG,
                           bd=1, relief="solid", pady=10, padx=14)
        cf.pack(fill="x", padx=16, pady=6)

        r0 = tk.Frame(cf, bg=BG)
        r0.pack(fill="x", pady=(0, 2))
        tk.Label(r0, text="Dispositivo:", font=("Courier New", 9),
                 bg=BG, fg=FG, width=13, anchor="e").pack(side="left")
        self._joy_var = tk.StringVar()
        self._joy_combo = ttk.Combobox(r0, textvariable=self._joy_var,
                                       state="readonly", width=29)
        self._joy_combo.pack(side="left", padx=(4, 2))
        self._joy_combo.bind("<<ComboboxSelected>>", lambda _: self._on_dev_select())
        tk.Button(r0, text="Buscar", command=self._scan_joysticks,
                  bg=CARD, fg=FG, relief="flat", font=("Courier New", 9),
                  cursor="hand2").pack(side="left", padx=4)

        self._api_lbl = tk.Label(cf, text="", font=("Courier New", 7), bg=BG, fg=DIM)
        self._api_lbl.pack(anchor="w")
        self._mon_lbl = tk.Label(cf, text="", font=("Courier New", 7),
                                  bg=BG, fg=DIM, anchor="w")
        self._mon_lbl.pack(fill="x", pady=(0, 8))

        # Gas row
        rg = tk.Frame(cf, bg=BG)
        rg.pack(fill="x", pady=3)
        tk.Label(rg, text="Gas :", font=("Courier New", 9, "bold"),
                 bg=BG, fg=GRN, width=7, anchor="e").pack(side="left")
        self._gas_lbl = tk.Label(rg, text="--", font=("Courier New", 10, "bold"),
                                  bg=BG, fg=GRN, width=10, anchor="w")
        self._gas_lbl.pack(side="left", padx=(6, 4))
        self._val_gas = tk.Label(rg, text="0%", font=("Courier New", 9),
                                  bg=BG, fg=DIM, width=5)
        self._val_gas.pack(side="left")
        self._btn_lg = tk.Button(rg, text="APRENDER GAS",
                                  command=lambda: self._start_learn("gas"),
                                  bg="#0a2a15", fg=GRN,
                                  font=("Courier New", 9, "bold"),
                                  relief="flat", padx=10, pady=5,
                                  cursor="hand2", activebackground="#0d3a1e")
        self._btn_lg.pack(side="left", padx=(4, 0))

        # Brake row
        rb = tk.Frame(cf, bg=BG)
        rb.pack(fill="x", pady=3)
        tk.Label(rb, text="Freio:", font=("Courier New", 9, "bold"),
                 bg=BG, fg=self.RED, width=7, anchor="e").pack(side="left")
        self._brk_lbl = tk.Label(rb, text="--", font=("Courier New", 10, "bold"),
                                  bg=BG, fg=self.RED, width=10, anchor="w")
        self._brk_lbl.pack(side="left", padx=(6, 4))
        self._val_brk = tk.Label(rb, text="0%", font=("Courier New", 9),
                                  bg=BG, fg=DIM, width=5)
        self._val_brk.pack(side="left")
        self._btn_lb = tk.Button(rb, text="APRENDER FREIO",
                                  command=lambda: self._start_learn("brake"),
                                  bg="#2a0a10", fg=self.RED,
                                  font=("Courier New", 9, "bold"),
                                  relief="flat", padx=10, pady=5,
                                  cursor="hand2", activebackground="#3a0d18")
        self._btn_lb.pack(side="left", padx=(4, 0))

        self._learn_lbl = tk.Label(cf,
            text="<- Selecione o dispositivo e clique em APRENDER",
            font=("Courier New", 8), bg=BG, fg=DIM)
        self._learn_lbl.pack(pady=(6, 0))

        lf = tk.LabelFrame(self, text="  LOG  ",
                           font=("Courier New", 9, "bold"),
                           bg=BG, fg=FG, bd=1, relief="solid", pady=6, padx=8)
        lf.pack(fill="both", expand=True, padx=16, pady=(4, 12))
        self._log_txt = tk.Text(lf, font=("Courier New", 8),
                                 bg="#050505", fg="#00e5cc",
                                 relief="flat", state="disabled", height=12)
        sb = tk.Scrollbar(lf, command=self._log_txt.yview,
                          bg=CARD, troughcolor=BG, relief="flat")
        self._log_txt.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log_txt.pack(fill="both", expand=True)

    def _log(self, msg):
        def _do():
            self._log_txt.config(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_txt.insert("end", f"[{ts}] {msg}\n")
            self._log_txt.see("end")
            self._log_txt.config(state="disabled")
        self.after(0, _do)

    def _copy_url(self):
        self.clipboard_clear()
        self.clipboard_append(self._url.get())

    def _scan_joysticks(self):
        def _bg():
            if RAW_OK and not raw_devs:
                start_rawinput()
            devs = joy_scan()
            def _upd():
                self._joy_list = devs
                labels = [d["label"] for d in devs]
                self._joy_combo["values"] = labels or ["-- nenhum encontrado --"]
                if labels:
                    self._joy_combo.current(0)
                    self._on_dev_select()
                self._log(f"Total: {len(devs)} dispositivos encontrados")
                for d in devs:
                    self._log(f"  * {d['label']}")
            self.after(0, _upd)
        threading.Thread(target=_bg, daemon=True).start()

    def _on_dev_select(self):
        sel = self._joy_combo.current()
        if 0 <= sel < len(self._joy_list):
            d = self._joy_list[sel]
            colors = {"raw": self.ACC, "xinput": self.YEL, "winmm": self.DIM}
            self._api_lbl.config(text=f"  API: {d['api'].upper()}",
                                  fg=colors.get(d["api"], self.DIM))

    def _start_learn(self, which):
        try:
            self._btn_lg.config(state="disabled")
            self._btn_lb.config(state="disabled")
        except Exception:
            pass

        def worker():
            try:
                self._learn_mode = which
                self.after(0, lambda: self._learn_lbl.config(
                    text=f"Pressione o botão/eixo de {'GAS' if which=='gas' else 'FREIO'} ({LEARN_SEC:.0f}s)...",
                    fg=self.YEL))

                btn_mask = None
                axis_idx = None

                if RAW_OK and raw_devs:
                    with raw_lock:
                        init_btns = raw_buttons
                        init_axes = list(raw_axes)
                        init_raw  = list(raw_last_raw)

                    self._log(f"Baseline RAW: {init_raw}")
                    self._log(f"Baseline botões: {init_btns:#010b}  Mova ou aperte agora...")

                    t_end = time.time() + LEARN_SEC
                    while time.time() < t_end:
                        with raw_lock:
                            cur_btns = raw_buttons
                            cur_axes = list(raw_axes)

                        # Checar botão
                        diff = cur_btns ^ init_btns
                        if diff:
                            btn_mask = diff
                            self._log(f"Botão detectado! mask={diff:#010b}  raw_btns={cur_btns:#010b}")
                            break

                        # Checar eixo analógico
                        best_i, best_d = -1, 0.0
                        for i, (b, c) in enumerate(zip(init_axes, cur_axes)):
                            delta = abs(c - b)
                            if delta > best_d:
                                best_d, best_i = delta, i
                        if best_d > 0.10:
                            axis_idx = best_i
                            self._log(f"Eixo detectado! A{best_i}  delta={best_d:.3f}")
                            break

                        remaining = t_end - time.time()
                        self.after(0, lambda r=remaining: self._learn_lbl.config(
                            text=f"Aguardando entrada... {r:.1f}s"))
                        time.sleep(0.02)

                self.after(0, lambda: self._finish_learn(which, btn_mask, axis_idx))

            except Exception as e:
                self._log(f"ERRO no learn: {e}")
                self.after(0, lambda: self._learn_lbl.config(text="Erro durante mapeamento", fg=self.ACC))
            finally:
                self._learn_mode = None
                try:
                    self._btn_lg.config(state="normal")
                    self._btn_lb.config(state="normal")
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _finish_learn(self, which, btn_mask, axis_idx):
        global gas_axis_idx, brake_axis_idx, gas_button_mask, brake_button_mask
        global gas_label, brake_label

        if btn_mask:
            if which == "gas":
                gas_button_mask = btn_mask
                gas_axis_idx    = -1
                gas_label       = f"BTN:{btn_mask:#010b}"
                self._gas_lbl.config(text=gas_label)
            else:
                brake_button_mask = btn_mask
                brake_axis_idx    = -1
                brake_label       = f"BTN:{btn_mask:#010b}"
                self._brk_lbl.config(text=brake_label)
            tag = "Gas" if which == "gas" else "Freio"
            self._log(f"OK {tag} -> botão mask={btn_mask:#010b}")

        elif axis_idx is not None:
            if which == "gas":
                gas_axis_idx    = axis_idx
                gas_button_mask = 0
                gas_label       = f"EIXO A{axis_idx}"
                self._gas_lbl.config(text=gas_label)
            else:
                brake_axis_idx    = axis_idx
                brake_button_mask = 0
                brake_label       = f"EIXO A{axis_idx}"
                self._brk_lbl.config(text=brake_label)
            tag = "Gas" if which == "gas" else "Freio"
            self._log(f"OK {tag} -> eixo A{axis_idx}")

        else:
            self._log("AVISO Nada detectado -- tente novamente e mantenha pressionado")
            self._learn_lbl.config(text="AVISO Nada detectado. Tente novamente.", fg=self.ACC)
            return

        gl = gas_label if gas_label != "--" else "?"
        bl = brake_label if brake_label != "--" else "?"
        self._learn_lbl.config(text=f"Gas=[{gl}]  Freio=[{bl}]", fg=self.GRN)

    def _axis_monitor(self):
        def _tick():
            sel = self._joy_combo.current()
            if 0 <= sel < len(self._joy_list) and not self._learn_mode:
                try:
                    dev = self._joy_list[sel]
                    state = joy_read(dev)
                    if state:
                        axes = state.get("axes", {})
                        btns = state.get("buttons", 0)

                        # Para RAW: mostrar bytes crus + resumo
                        if dev.get("api") == "raw":
                            with raw_lock:
                                arr = list(raw_last_raw)
                            raw_str = " ".join(str(b) for b in arr) if arr else "aguardando..."
                            self._mon_lbl.config(text=f"RAW: [{raw_str}]  BTN:{btns:#010b}")
                        else:
                            parts = [f"{n}:{v:.2f}" for n, v in list(axes.items())[:6]]
                            if btns:
                                parts.append(f"BTN:{btns:#010b}")
                            self._mon_lbl.config(text="  ".join(parts))

                        # Percentuais Gas/Freio
                        g_pct = b_pct = 0.0
                        if gas_button_mask:
                            g_pct = 1.0 if (btns & gas_button_mask) else 0.0
                        elif gas_axis_idx >= 0:
                            v = list(axes.values())[gas_axis_idx] if gas_axis_idx < len(axes) else 0.5
                            g_pct = abs(v - 0.5) * 2.0
                        if brake_button_mask:
                            b_pct = 1.0 if (btns & brake_button_mask) else 0.0
                        elif brake_axis_idx >= 0:
                            v = list(axes.values())[brake_axis_idx] if brake_axis_idx < len(axes) else 0.5
                            b_pct = abs(v - 0.5) * 2.0

                        self._val_gas.config(text=f"{int(g_pct*100)}%",
                                              fg=self.GRN if g_pct > 0.05 else self.DIM)
                        self._val_brk.config(text=f"{int(b_pct*100)}%",
                                              fg=self.RED if b_pct > 0.05 else self.DIM)
                except Exception:
                    pass
            self.after(100, _tick)
        self.after(300, _tick)

    def _start_servers(self):
        if not WS_OK or not CRYPTO_OK:
            self._log("ERRO pip install websockets cryptography")
            return
        if not ensure_cert():
            self._log("ERRO falha ao gerar certificado SSL")
            return
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(CERT_FILE, KEY_FILE)
        threading.Thread(target=_run_https, args=(ssl_ctx,), daemon=True).start()
        threading.Thread(target=_run_async, args=(ssl_ctx,), daemon=True).start()
        ip  = _get_ip()
        url = f"https://{ip}:{HTTPS_PORT}/controller.html"
        self.after(800, lambda: self._url.set(url))
        self.after(800, lambda: self._dot.config(fg=self.GRN))
        self._log(f"HTTPS:{HTTPS_PORT}  WSS:{WSS_PORT}")
        self._log(f"URL: {url}")

# ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = App()
    app.mainloop()