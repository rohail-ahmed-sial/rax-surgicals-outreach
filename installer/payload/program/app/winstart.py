"""Start with Windows: a value in the user's Run key starts RAX Surgicals Outreach (without a window) when Windows
starts. Only for the installed app, whose launcher sets RAX_LAUNCHER to its own path."""
import os

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
NAME = 'RAX Surgicals Outreach'
OLD_NAME = 'RAX Outreach'          # the value's name up to version 2.1


def supported():
    return os.name == 'nt' and bool(os.environ.get('RAX_LAUNCHER'))


def is_on():
    if not supported():
        return False
    import winreg
    for name in (NAME, OLD_NAME):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, name)
                return True
        except OSError:
            continue
    return False


def set_on(on):
    if not supported():
        raise OSError('Starting with Windows is only available in the installed app.')
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if on:
            winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, f'"{os.environ["RAX_LAUNCHER"]}" --background')
        for name in ((OLD_NAME,) if on else (NAME, OLD_NAME)):
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
    return is_on()
