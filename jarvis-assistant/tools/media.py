import os
import urllib.parse
import webbrowser

_LAST_SONG = ""


def search_google(query: str) -> str:
    """Open Google search in default browser."""
    clean = urllib.parse.quote_plus(query.strip())
    webbrowser.open(f"https://www.google.com/search?q={clean}")
    return f"Searching Google for {query}."


def open_browser(url: str = "") -> str:
    """Open default browser to a specific URL or homepage."""
    target = url.strip() or "https://www.google.com"
    if not target.startswith("http://") and not target.startswith("https://"):
        target = f"https://{target}"
    webbrowser.open(target)
    return f"Opened browser."


def play_youtube(query: str) -> str:
    """Open YouTube search/video directly in browser (0MB RAM footprint)."""
    clean_q = urllib.parse.quote_plus(query.strip())
    webbrowser.open(f"https://www.youtube.com/results?search_query={clean_q}")
    return f"Playing {query} on YouTube."


def play_spotify(query: str) -> str:
    """Trigger Spotify focus media via URI protocol or fallback search."""
    clean_q = urllib.parse.quote(query.strip())
    try:
        os.startfile(f"spotify:search:{clean_q}")
    except Exception:
        webbrowser.open(f"https://open.spotify.com/search/{clean_q}")
    return f"Playing {query} on Spotify."


def play_music(song: str = "", platform: str = "") -> str:
    """Play a song on Spotify or YouTube. If platform is unspecified, asks Fas to choose."""
    global _LAST_SONG
    target_song = song.strip() or _LAST_SONG or "music"
    p = platform.lower().strip()
    if "spotify" in p:
        _LAST_SONG = ""
        return play_spotify(target_song)
    if "youtube" in p:
        _LAST_SONG = ""
        return play_youtube(target_song)
    _LAST_SONG = target_song
    return f"Would you like to play {target_song} on Spotify or YouTube, Fas?"
