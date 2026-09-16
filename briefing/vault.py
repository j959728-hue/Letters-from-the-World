"""Windows-only local UI credential storage. Cloud runs use environment variables."""
import ctypes
from ctypes import wintypes

class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]

def _crypt(value,decrypt=False):
    buf=(ctypes.c_ubyte*len(value)).from_buffer_copy(value)
    incoming=Blob(len(value),buf); outgoing=Blob()
    fn=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    fn.restype=wintypes.BOOL
    ok=fn(ctypes.byref(incoming),None,None,None,None,1,ctypes.byref(outgoing))
    if not ok: raise OSError('Windows 凭据加密操作失败')
    try: return ctypes.string_at(outgoing.data,outgoing.size)
    finally:
        free=ctypes.windll.kernel32.LocalFree
        free.argtypes=[ctypes.c_void_p]; free.restype=ctypes.c_void_p
        free(outgoing.data)

def encode(value): return _crypt(value)
def decode(value): return _crypt(value,True).decode('utf-8')
