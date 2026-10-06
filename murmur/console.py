"""Small, thread-safe console logger without optional terminal dependencies."""
import ctypes
import logging
import os
import re
import sys

_COLORS={'DEBUG':'90','INFO':'36','WARNING':'33','ERROR':'31','CRITICAL':'1;31'}
_CONTROL=re.compile(r'[\x00-\x1f\x7f-\x9f]')
LOGO=r'''     ___           ___           ___           ___           ___           ___
    /__/\         /__/\         /  /\         /__/\         /__/\         /  /\
    |  |::\        \  \:\       /  /::\       |  |::\        \  \:\       /  /::\
    |  |:|:\        \  \:\     /  /:/\:\      |  |:|:\        \  \:\     /  /:/\:\
  __|__|:|\:\   ___  \  \:\   /  /:/~/:/    __|__|:|\:\   ___  \  \:\   /  /:/~/:/
 /__/::::| \:\ /__/\  \__\:\ /__/:/ /:/___ /__/::::| \:\ /__/\  \__\:\ /__/:/ /:/___
 \  \:\~~\__\/ \  \:\ /  /:/ \  \:\/:::::/ \  \:\~~\__\/ \  \:\ /  /:/ \  \:\/:::::/
  \  \:\        \  \:\  /:/   \  \::/~~~~   \  \:\        \  \:\  /:/   \  \::/~~~~
   \  \:\        \  \:\/:/     \  \:\        \  \:\        \  \:\/:/     \  \:\
    \  \:\        \  \::/       \  \:\        \  \:\        \  \::/       \  \:\
     \__\/         \__\/         \__\/         \__\/         \__\/         \__\/'''


def _terminal_color(stream):
    if not stream or not getattr(stream,'isatty',lambda:False)():return False
    if os.name!='nt':return True
    try:
        import msvcrt
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetConsoleMode.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        kernel.SetConsoleMode.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        handle=msvcrt.get_osfhandle(stream.fileno());mode=ctypes.c_ulong()
        return bool(kernel.GetConsoleMode(handle,ctypes.byref(mode)) and kernel.SetConsoleMode(handle,mode.value|4))
    except (OSError,ValueError,AttributeError):return False


class ConsoleHandler(logging.Handler):
    def __init__(self,color='auto',stream=None):
        super().__init__();self.color=color;self.stream=stream
        self._color_stream=None;self._color_enabled=False

    def colored(self,stream):
        if stream is not self._color_stream:
            self._color_stream=stream;self._color_enabled=_terminal_color(stream)
        return self.color=='always' or (self.color=='auto' and 'NO_COLOR' not in os.environ and self._color_enabled)

    def emit(self,record):
        stream=self.stream if self.stream is not None else sys.stdout
        if stream is None:return
        try:
            colored=self.colored(stream)
            # One physical line per event; provider/model labels cannot inject ANSI.
            message=_CONTROL.sub(' ',record.getMessage())
            category=_CONTROL.sub(' ',str(getattr(record,'category','app')))
            stamp=logging.Formatter().formatTime(record,'%H:%M:%S')
            level=record.levelname
            tag=f'[{level.lower()}]'
            if colored:
                line=f'\033[90m{stamp}\033[0m \033[{_COLORS.get(level,"36")}m{tag:<9}\033[0m \033[35m{category:<9}\033[0m {message}'
            else:line=f'{stamp} {tag:<9} {category:<9} {message}'
            stream.write(line+'\n');stream.flush()
        except (OSError,ValueError,UnicodeError):pass


def configure(level='INFO',color='auto',stream=None):
    logger=logging.getLogger('murmur.console');logger.propagate=False
    for handler in logger.handlers[:]:logger.removeHandler(handler);handler.close()
    logger.setLevel(level);logger.addHandler(ConsoleHandler(color,stream))
    return logger


def event(category,message,*args,level='INFO'):
    logger=logging.getLogger('murmur.console')
    if not logger.handlers:configure()
    logger.log(getattr(logging,level),message,*args,extra={'category':category})


def banner():
    logger=logging.getLogger('murmur.console')
    if not logger.handlers:configure()
    for handler in logger.handlers:
        if not isinstance(handler,ConsoleHandler):continue
        stream=handler.stream if handler.stream is not None else sys.stdout
        if stream is None:continue
        with handler.lock:
            try:
                logo='\033[95m'+LOGO+'\033[0m' if handler.colored(stream) else LOGO
                stream.write(logo+'\n\n');stream.flush()
            except (OSError,ValueError,UnicodeError):pass
