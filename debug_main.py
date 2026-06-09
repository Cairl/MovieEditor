import sys

sys.argv = [sys.argv[0], r"U:\【高清剧集网 www.BTHDTV.com】绝命毒师 第一季[全7集][简繁英字幕].Breaking.Bad.S01.2160p.NF.WEB-DL.DDP.5.1.H.265-BlackTV"]

from ui.app import process_files

if __name__ == '__main__':
    try:
        from ui.console import hide_cursor, show_cursor
        hide_cursor()
        process_files()
    except KeyboardInterrupt:
        show_cursor()
