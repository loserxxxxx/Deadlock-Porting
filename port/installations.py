"""Find Steam libraries and installed Deadlock/Blender without a full-disk crawl."""
import os
from pathlib import Path
import re

APP_ID = '1422450'
VPK_SUFFIX = Path('game/citadel/pak01_dir.vpk')


def quoted_values(text, key):
    pattern = r'"' + re.escape(key) + r'"\s*"((?:\\.|[^"\\])*)"'
    return [value.replace('\\\\', '\\').replace('\\"', '"') for value in re.findall(pattern, text, re.I)]


def registry_steam_paths():
    paths = []
    try:
        import winreg
        for hive, key, value in [(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                                  (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
                                  (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath')]:
            try:
                with winreg.OpenKey(hive, key) as handle:
                    paths.append(Path(winreg.QueryValueEx(handle, value)[0]))
            except OSError:
                pass
    except ImportError:
        pass
    return paths


def steam_roots():
    candidates = registry_steam_paths()
    for env in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
        if os.environ.get(env):
            candidates.append(Path(os.environ[env]) / 'Steam')
    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        drive = Path(letter + ':/')
        if drive.exists():
            candidates.extend(drive / folder for folder in ('Steam', 'SteamLibrary', 'Games/Steam', 'Program Files (x86)/Steam'))
    return candidates


def steam_libraries(roots):
    libraries = set()
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        libraries.add(root)
        for manifest in (root / 'steamapps/libraryfolders.vdf', root / 'config/libraryfolders.vdf'):
            try:
                text = manifest.read_text(encoding='utf-8', errors='replace')
                paths = quoted_values(text, 'path')
                
                paths += [value.replace('\\\\', '\\') for value in re.findall(r'"\d+"\s*"([^"\n]+)"', text) if ':' in value or value.startswith('/')]
                libraries.update(Path(path) for path in paths)
            except OSError:
                pass
    return sorted(libraries, key=lambda p: str(p).lower())


def find_deadlock(roots=None):
    results = []
    seen = set()
    for library in steam_libraries(steam_roots() if roots is None else roots):
        folders = [library / 'steamapps/common/Deadlock', library / 'steamapps/common/Project8']
        try:
            text = (library / f'steamapps/appmanifest_{APP_ID}.acf').read_text(encoding='utf-8', errors='replace')
            for name in quoted_values(text, 'installdir'):
                
                candidate = library / 'steamapps/common' / name
                if candidate.resolve().is_relative_to((library / 'steamapps/common').resolve()):
                    folders.insert(0, candidate)
        except OSError:
            pass
        for folder in folders:
            vpk = folder / VPK_SUFFIX
            if vpk.is_file() and str(vpk.resolve()).lower() not in seen:
                seen.add(str(vpk.resolve()).lower())
                results.append(dict(path=str(vpk.resolve()), directory=str(folder.resolve()), library=str(library)))
    return results


def find_blender():
    candidates = []
    for env in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        if not os.environ.get(env):
            continue
        root = Path(os.environ[env])
        for pattern in ('Blender Foundation/Blender */blender.exe', 'Programs/Blender Foundation/Blender */blender.exe', 'Blender*/blender.exe'):
            candidates.extend(root.glob(pattern))
    for library in steam_libraries(steam_roots()):
        candidates.append(library / 'steamapps/common/Blender/blender.exe')
    return [str(p) for p in sorted(set(candidates), reverse=True) if p.is_file()]
