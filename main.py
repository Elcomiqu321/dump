"""
Audio Transcription Correction Tool
Main entry point
"""
import tkinter as tk
from gui import TranscriptionToolGUI


def main():
    root = tk.Tk()
    app = TranscriptionToolGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
