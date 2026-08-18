"""Compatibility wrapper that swaps only Meemaw's transport implementation."""
from app.core._player_original import *
from app.core._player_original import PlayerManager as _OriginalPlayerManager
from app.core.browser_audio_backend import BrowserAudioAdapter, patch_player_manager

PlayerManager = patch_player_manager(_OriginalPlayerManager)
