if __name__ == '__main__':
    try:
        import multiprocessing
        multiprocessing.freeze_support()
        from murmur.app import main
        main()
    except Exception:
        import sys,traceback
        from murmur.paths import startup_error_log
        log=startup_error_log()
        log.parent.mkdir(parents=True,exist_ok=True);log.write_text(traceback.format_exc(),encoding='utf-8')
        if sys.stderr:traceback.print_exc()
        elif getattr(sys,'frozen',False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,'MurMur could not start.\n\nDetails have been saved to:\n'+str(log),'MurMur startup error',0x10)
        sys.exit(1)
