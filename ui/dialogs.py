# 文件选择对话框
import os
import tkinter as tk
from tkinter import filedialog


def choose_files(title: str, filetypes: list) -> list:
    root = tk.Tk()
    root.withdraw()
    files = filedialog.askopenfilenames(title=title, filetypes=filetypes)
    root.destroy()
    return list(files)


def choose_file(title: str, filetypes: list) -> str:
    root = tk.Tk()
    root.withdraw()
    file = filedialog.askopenfilename(title=title, filetypes=filetypes)
    root.destroy()
    return file


def choose_directory(title: str) -> str:
    root = tk.Tk()
    root.withdraw()
    directory = filedialog.askdirectory(title=title)
    root.destroy()
    return directory


def get_video_files_in_dir(dir_path: str) -> list:
    import re
    exts = ('.mp4', '.mkv', '.mov', '.avi', '.flv', '.wmv')
    files = [os.path.join(dir_path, f) for f in os.listdir(dir_path) if f.lower().endswith(exts)]
    files.sort(key=lambda x: [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', x)])
    return files
