# -*- coding: utf-8 -*-
"""直接调用 Windows WASAPI 探测麦克风能否打开（绕过 PortAudio）。"""
import ctypes
from ctypes import wintypes, POINTER, byref, c_void_p, cast


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class WAVEFORMATEXTENSIBLE(ctypes.Structure):
    _fields_ = [
        ("Format", WAVEFORMATEX),
        ("Samples", wintypes.WORD),
        ("dwChannelMask", wintypes.DWORD),
        ("SubFormat", GUID),
    ]


ole32 = ctypes.windll.ole32
ole32.CoInitialize.argtypes = [c_void_p]
ole32.CoInitialize(None)
ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, POINTER(GUID)]
ole32.CoCreateInstance.argtypes = [
    POINTER(GUID), c_void_p, wintypes.DWORD, POINTER(GUID), POINTER(c_void_p)
]

CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
IID_IAudioClient = "{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}"


def clsid(s):
    b = ctypes.create_unicode_buffer(s)
    guid = GUID()
    if ole32.CLSIDFromString(b, byref(guid)) != 0:
        raise RuntimeError("CLSIDFromString failed")
    return guid


def hrcheck(hr, what):
    if hr < 0:
        raise ctypes.WinError(hr & 0xFFFFFFFF)


class IMMDeviceEnumerator(ctypes.Structure):
    pass


class IMMDevice(ctypes.Structure):
    pass


class IAudioClient(ctypes.Structure):
    pass


class EnumVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(GUID), POINTER(c_void_p))),
        ("AddRef", ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)),
        ("Release", ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)),
        ("EnumAudioEndpoints", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, wintypes.DWORD, wintypes.DWORD, POINTER(POINTER(IMMDevice)))),
        ("GetDefaultAudioEndpoint", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, wintypes.DWORD, wintypes.DWORD, POINTER(POINTER(IMMDevice)))),
        ("GetDevice", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, c_void_p, POINTER(POINTER(IMMDevice)))),
        ("RegisterEndpointNotificationCallback", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, c_void_p)),
        ("UnregisterEndpointNotificationCallback", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, c_void_p)),
    ]


class DevVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(GUID), POINTER(c_void_p))),
        ("AddRef", ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)),
        ("Release", ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)),
        ("Activate", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p))),
        ("OpenPropertyStore", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, wintypes.DWORD, POINTER(c_void_p))),
        ("GetId", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(POINTER(wintypes.WCHAR)))),
        ("GetState", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(wintypes.DWORD))),
    ]


class ClientVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(GUID), POINTER(c_void_p))),
        ("AddRef", ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)),
        ("Release", ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)),
        ("Initialize", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_longlong, ctypes.c_longlong, POINTER(WAVEFORMATEX), POINTER(GUID))),
        ("GetBufferSize", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(wintypes.UINT))),
        ("GetStreamLatency", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(ctypes.c_longlong))),
        ("GetCurrentPadding", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(wintypes.UINT))),
        ("IsFormatSupported", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, wintypes.DWORD, POINTER(WAVEFORMATEX), POINTER(POINTER(WAVEFORMATEX)))),
        ("GetMixFormat", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(POINTER(WAVEFORMATEX)))),
        ("GetDevicePeriod", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(ctypes.c_longlong), POINTER(ctypes.c_longlong))),
        ("Start", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p)),
        ("Stop", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p)),
        ("Reset", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p)),
        ("SetEventHandle", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, c_void_p)),
        ("GetService", ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(GUID), POINTER(c_void_p))),
    ]


IMMDeviceEnumerator._fields_ = [("lpVtbl", POINTER(EnumVtbl))]
IMMDevice._fields_ = [("lpVtbl", POINTER(DevVtbl))]
IAudioClient._fields_ = [("lpVtbl", POINTER(ClientVtbl))]


def make_fmt(rate, channels, bits):
    wfe = WAVEFORMATEXTENSIBLE()
    wfe.Format.wFormatTag = 0xFFFE  # WAVE_FORMAT_EXTENSIBLE
    wfe.Format.nChannels = channels
    wfe.Format.nSamplesPerSec = rate
    wfe.Format.nAvgBytesPerSec = rate * channels * bits // 8
    wfe.Format.nBlockAlign = channels * bits // 8
    wfe.Format.wBitsPerSample = bits
    wfe.Format.cbSize = 22
    wfe.Samples = bits
    wfe.dwChannelMask = 0x3  # FL | FR
    wfe.SubFormat = clsid("{00000003-0000-0010-8000-00AA00389B71}")  # IEEE_FLOAT
    return wfe


ppv = c_void_p()
hr = ole32.CoCreateInstance(byref(clsid(CLSID_MMDeviceEnumerator)), None, 1, byref(clsid(IID_IMMDeviceEnumerator)), byref(ppv))
hrcheck(hr, "CoCreateInstance")
enum = cast(ppv, POINTER(IMMDeviceEnumerator))

dev = POINTER(IMMDevice)()
hr = enum.contents.lpVtbl.contents.GetDefaultAudioEndpoint(enum, 1, 0, byref(dev))
hrcheck(hr, "GetDefaultAudioEndpoint")

state = wintypes.DWORD()
dev.contents.lpVtbl.contents.GetState(dev, byref(state))
print("device state:", state.value, "(1=active, 2=disabled, 3=notpresent, 4=unplugged)")

ac = c_void_p()
hr = dev.contents.lpVtbl.contents.Activate(dev, byref(clsid(IID_IAudioClient)), 0, None, byref(ac))
hrcheck(hr, "Activate IAudioClient")
audio_client = cast(ac, POINTER(IAudioClient))

fmt = POINTER(WAVEFORMATEX)()
hr = audio_client.contents.lpVtbl.contents.GetMixFormat(audio_client, byref(fmt))
hrcheck(hr, "GetMixFormat")
print("mix format:", fmt.contents.nSamplesPerSec, "Hz,", fmt.contents.nChannels, "ch,", fmt.contents.wBitsPerSample, "bit")


def try_init(label, share_mode, hns, pfmt):
    global audio_client
    hr = audio_client.contents.lpVtbl.contents.Initialize(
        audio_client, share_mode, 0, hns, 0, pfmt, None
    )
    if hr == 0:
        print("WASAPI Initialize OK:", label)
        audio_client.contents.lpVtbl.contents.Release(audio_client)
        ac2 = c_void_p()
        hr = dev.contents.lpVtbl.contents.Activate(dev, byref(clsid(IID_IAudioClient)), 0, None, byref(ac2))
        hrcheck(hr, "Activate again")
        audio_client = cast(ac2, POINTER(IAudioClient))
    else:
        print("WASAPI Initialize failed:", label, "hr=0x%08X" % (hr & 0xFFFFFFFF))


wfe = make_fmt(48000, 2, 32)
fmt_ptr = cast(byref(wfe), POINTER(WAVEFORMATEX))
try_init("shared 0.1s manual", 0, 1_000_000, fmt_ptr)
try_init("exclusive 0.1s manual", 1, 1_000_000, fmt_ptr)
try_init("shared default manual", 0, 0, fmt_ptr)

audio_client.contents.lpVtbl.contents.Release(audio_client)
dev.contents.lpVtbl.contents.Release(dev)
enum.contents.lpVtbl.contents.Release(enum)
