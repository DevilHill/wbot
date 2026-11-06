"""供本地执行宿主共用的 Windows 任务进程树管理。"""


def windows_job(proc):
    """只管理调用方创建的进程及其后代。"""
    import ctypes as C
    from ctypes import wintypes as W
    class Basic(C.Structure):
        _fields_ = [('time1', C.c_longlong), ('time2', C.c_longlong), ('flags', W.DWORD),
                    ('min', C.c_size_t), ('max', C.c_size_t), ('active', W.DWORD),
                    ('affinity', C.c_size_t), ('priority', W.DWORD), ('scheduling', W.DWORD)]
    class Limits(C.Structure):
        _fields_ = [('basic', Basic), ('io', C.c_ulonglong * 6), ('memory', C.c_size_t * 4)]
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [C.c_void_p, W.LPCWSTR]
    kernel.CreateJobObjectW.restype = W.HANDLE
    kernel.SetInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    limits = Limits(); limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE：关闭句柄时结束进程树
    if not handle or not kernel.SetInformationJobObject(handle, 9, C.byref(limits), C.sizeof(limits)):
        if handle: kernel.CloseHandle(handle)
        raise OSError(C.get_last_error(), '无法创建脚本进程组')
    if not kernel.AssignProcessToJobObject(handle, W.HANDLE(int(proc._handle))):
        kernel.CloseHandle(handle)
        raise OSError(C.get_last_error(), '无法管理脚本进程组')
    return lambda: kernel.CloseHandle(handle)
