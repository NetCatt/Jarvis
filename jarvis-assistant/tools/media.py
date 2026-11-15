import urllib.parse
import webbrowser


def play_youtube(query: str) -> str:
    """Open YouTube search/video directly in browser (0MB RAM footprint)."""
    clean_q = urllib.parse.quote_plus(query.strip())
    url = f"https://www.youtube.com/results?search_query={clean_q}"
    webbrowser.open(url)
    return f"Playing {query} on YouTube."


def play_spotify(query: str) -> str:
    """Trigger Spotify focus media via URI protocol or fallback search."""
    clean_q = urllib.parse.quote(query.strip())
    webbrowser.open(f"spotify:search:{clean_q}")
    return f"Searching {query} on Spotify."
