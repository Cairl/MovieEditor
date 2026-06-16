import ui.live as live
from ui.app import process_files

if __name__ == '__main__':
    try:
        process_files()
    except KeyboardInterrupt:
        pass
    finally:
        live.stop_screen()
