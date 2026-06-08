from ui.app import process_files

if __name__ == '__main__':
    try:
        from ui.console import hide_cursor, show_cursor
        hide_cursor()
        process_files()
    except KeyboardInterrupt:
        show_cursor()
