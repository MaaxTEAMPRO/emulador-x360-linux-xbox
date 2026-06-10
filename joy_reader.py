import ctypes
from ctypes import wintypes as W

_winmm   = ctypes.WinDLL("winmm")

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

def read_joystick(dev_id):
    """Reads a joystick using WinMM joyGetPosEx."""
    info = _JOYINFOEX()
    info.dwSize  = ctypes.sizeof(info)
    info.dwFlags = 0x80 | 0x01 | 0x02 | 0x04 | 0x08 # JOY_RETURNBUTTONS | JOY_RETURNX | JOY_RETURNY | JOY_RETURNZ | JOY_RETURNR
    
    if _winmm.joyGetPosEx(dev_id, ctypes.byref(info)) != 0:
        return None
    
    caps = _JOYCAPS()
    if _winmm.joyGetDevCapsW(dev_id, ctypes.byref(caps), ctypes.sizeof(caps)) != 0:
        return None

    _MM_AXES = ["X", "Y", "Z", "R", "U", "V"]
    lo = [caps.wXmin, caps.wYmin, caps.wZmin, caps.wRmin, caps.wUmin, caps.wVmin]
    hi = [caps.wXmax, caps.wYmax, caps.wZmax, caps.wRmax, caps.wUmax, caps.wVmax]
    rv = [info.dwXpos, info.dwYpos, info.dwZpos,
          info.dwRpos, info.dwUpos, info.dwVpos]
    
    axes = {n: (r - l) / max(h - l, 1) for n, l, h, r in zip(_MM_AXES, lo, hi, rv)}
    
    result = {
        "axes": axes,
        "buttons": info.dwButtons,
        "pov": info.dwPOV
    }
    return result

if __name__ == '__main__':
    import time
    print("Testing joystick reader. Press buttons on joystick 0...")
    while True:
        state = read_joystick(0)
        if state:
            print(f"Buttons: {state['buttons']:016b}  Axes: {state['axes']['X']:.2f}, {state['axes']['Y']:.2f}    ", end='')
        else:
            print("Joystick 0 not detected.", end='')
        time.sleep(0.05)
