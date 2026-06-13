# 文件选择对话框
import os
import re
import tkinter as tk
from tkinter import filedialog


def _tk_dialog(dialog_fn, *args, **kwargs):
    root = tk.Tk()
    root.withdraw()
    try:
        return dialog_fn(*args, **kwargs)
    finally:
        root.destroy()


def choose_files(title: str, filetypes: list) -> list:
    return list(_tk_dialog(filedialog.askopenfilenames, title=title, filetypes=filetypes))


def choose_file(title: str, filetypes: list) -> str:
    return _tk_dialog(filedialog.askopenfilename, title=title, filetypes=filetypes)


def choose_directory(title: str) -> str:
    return _tk_dialog(filedialog.askdirectory, title=title)


def get_video_files_in_dir(dir_path: str) -> list:
    exts = ('.mp4', '.mkv', '.mov', '.avi', '.flv', '.wmv')
    files = [os.path.join(dir_path, f) for f in os.listdir(dir_path) if f.lower().endswith(exts)]
    files.sort(key=lambda x: [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', x)])
    return files
