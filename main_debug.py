import sys
sys.argv = [sys.argv[0], r"U:\绝命毒师 第一季[全7集][简繁英字幕].Breaking.Bad.S01.2160p.NF.WEB-DL.DDP.5.1.H.265-BlackTV"]
import ui.live as live
from ui.app import process_files

if __name__ == '__main__':
    try:
        process_files()
    except KeyboardInterrupt:
        pass
    finally:
        live.stop_screen()
