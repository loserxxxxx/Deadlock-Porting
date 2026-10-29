"""Read Blender window/process metadata; never inject code into running sessions."""
import os
from pathlib import Path
import re


def project_from_title(title):
    match = re.search(r'\[((?:[A-Za-z]:[\\/]|\\\\).+\.blend)\]', title, re.I)
    if not match:
        match = re.search(r'((?:[A-Za-z]:[\\/]|\\\\)[^\r\n]+?\.blend)(?=\s+-\s+Blender|\s*$)', title, re.I)
    return match[1] if match else None


def describe_session(pid, title, executable):
    project = project_from_title(title)
    saved = bool(project and Path(project).is_file())
    return dict(pid=pid, title=title, executable=executable, project_path=project,
                name=Path(project).name if project else 'Untitled project',
                saved=saved, modified='*' in title,
                note=None if saved else 'Save this project in Blender first' if not project else 'The saved file could not be found')


def opened_projects():
    if os.name != 'nt':
        return []
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    executables = {}
    sessions = {}

    @callback_type
    def visit(window, _):
        if not user32.IsWindowVisible(window):
            return True
        length = user32.GetWindowTextLengthW(window)
        if not length:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value not in executables:
            handle = kernel32.OpenProcess(0x1000, False, pid.value)
            executable = ''
            if handle:
                try:
                    size = wintypes.DWORD(32768)
                    buffer = ctypes.create_unicode_buffer(size.value)
                    if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                        executable = buffer.value
                finally:
                    kernel32.CloseHandle(handle)
            executables[pid.value] = executable
        executable = executables[pid.value]
        if Path(executable).name.lower() != 'blender.exe':
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(window, buffer, length + 1)
        session = describe_session(pid.value, buffer.value, executable)
        previous = sessions.get(pid.value)
        
        if previous is None or (session['project_path'] and not previous['project_path']):
            sessions[pid.value] = session
        return True

    if not user32.EnumWindows(visit, 0):
        raise OSError(ctypes.get_last_error(), 'Could not enumerate Blender windows')
    return sorted(sessions.values(), key=lambda s: (s['name'].lower(), s['pid']))


def sessions_for_project(project):
    target = os.path.normcase(str(Path(project).resolve()))
    return [s for s in opened_projects() if s['project_path']
            and os.path.normcase(str(Path(s['project_path']).resolve())) == target]
