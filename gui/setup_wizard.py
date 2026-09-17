"""
gui/setup_wizard.py — First-run setup wizard.

Standalone CTk window shown on first launch when no valid token is found.
Collects credentials, writes .env, then destroys itself so the main
AgyBotApp can start normally.
"""

from pathlib import Path

import customtkinter as ctk

from gui.constants import (
    COLOR_ACCENT,
    COLOR_ACCENT_HVR,
    COLOR_BG_DARK,
    COLOR_BORDER,
    COLOR_RED,
    COLOR_SURFACE,
    COLOR_TEXT,
    COLOR_TEXT_DIM,
)
from gui.env_store import write_env_all
from gui.paths import ENV_FILE


class SetupWizard:
    def __init__(self) -> None:
        ctk.set_appearance_mode('dark')
        ctk.set_default_color_theme('blue')

        self._root = ctk.CTk()
        self._root.title('Antigravity Bot — First Run Setup')
        self._root.geometry('460x520')
        self._root.resizable(False, False)
        self._root.configure(fg_color=COLOR_BG_DARK)
        self._root.protocol('WM_DELETE_WINDOW', self._cancel)
        self._completed = False
        self._build()

    def _build(self) -> None:
        r = self._root

        # Branding
        ctk.CTkLabel(
            r, text='✦',
            font=ctk.CTkFont(size=48),
            text_color=COLOR_ACCENT,
        ).pack(pady=(36, 0))

        ctk.CTkLabel(
            r, text='Antigravity Bot',
            font=ctk.CTkFont(family='Roboto', size=22, weight='bold'),
            text_color=COLOR_TEXT,
        ).pack(pady=(4, 2))

        ctk.CTkLabel(
            r, text='Quick setup — takes 30 seconds',
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_DIM,
        ).pack(pady=(0, 24))

        card = ctk.CTkFrame(r, fg_color=COLOR_SURFACE, corner_radius=14)
        card.pack(fill='x', padx=28)

        # Bot Token
        ctk.CTkLabel(
            card, text='Telegram Bot Token',
            font=ctk.CTkFont(size=13, weight='bold'),
            text_color=COLOR_TEXT, anchor='w',
        ).pack(fill='x', padx=16, pady=(16, 4))
        ctk.CTkLabel(
            card,
            text='Get yours from @BotFather on Telegram',
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_DIM, anchor='w',
        ).pack(fill='x', padx=16, pady=(0, 4))
        self._e_token = ctk.CTkEntry(
            card, show='●',
            placeholder_text='123456789:ABCdef...',
            fg_color=COLOR_BG_DARK, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, corner_radius=8, height=36,
        )
        self._e_token.pack(fill='x', padx=16, pady=(0, 14))

        # Chat IDs
        ctk.CTkLabel(
            card, text='Allowed Chat IDs  (optional)',
            font=ctk.CTkFont(size=13, weight='bold'),
            text_color=COLOR_TEXT, anchor='w',
        ).pack(fill='x', padx=16, pady=(0, 4))
        ctk.CTkLabel(
            card,
            text='Comma-separated. Get yours from @userinfobot',
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_DIM, anchor='w',
        ).pack(fill='x', padx=16, pady=(0, 4))
        self._e_ids = ctk.CTkEntry(
            card,
            placeholder_text='123456789, 987654321',
            fg_color=COLOR_BG_DARK, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, corner_radius=8, height=36,
        )
        self._e_ids.pack(fill='x', padx=16, pady=(0, 16))

        # Error label
        self._err_lbl = ctk.CTkLabel(
            r, text='', font=ctk.CTkFont(size=12),
            text_color=COLOR_RED,
        )
        self._err_lbl.pack(pady=(10, 0))

        # Launch button
        ctk.CTkButton(
            r,
            text='Get Started  →',
            command=self._submit,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HVR,
            text_color='#FFFFFF', corner_radius=10, height=42,
            font=ctk.CTkFont(size=15, weight='bold'),
        ).pack(fill='x', padx=28, pady=(16, 8))

        ctk.CTkLabel(
            r,
            text='You can change these later in Settings',
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_DIM,
        ).pack()

    def _submit(self) -> None:
        token = self._e_token.get().strip()
        if not token or ':' not in token:
            self._err_lbl.configure(text='⚠  Please enter a valid Bot Token')
            return
        chat_ids = self._e_ids.get().strip()
        write_env_all({
            'TELEGRAM_BOT_TOKEN': token,
            'TELEGRAM_ALLOWED_CHAT_IDS': chat_ids,
            'AGY_BIN': 'agy',
            'AGY_DEFAULT_WORKSPACE': str(Path.home() / 'agy-server-workspace'),
            'AGY_PRINT_TIMEOUT': '300',
        })
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=str(ENV_FILE), override=True)
        self._completed = True
        self._root.destroy()

    def _cancel(self) -> None:
        self._root.destroy()

    def run(self) -> bool:
        """Show the wizard; return True if user completed setup."""
        self._root.mainloop()
        return self._completed
