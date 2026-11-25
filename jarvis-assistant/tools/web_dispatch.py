import urllib.parse
import webbrowser

_ENGINES = {
    "google": "https://www.google.com/search?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
    "spotify": "https://open.spotify.com/search/{}",
    "github": "https://github.com/search?q={}",
    "reddit": "https://www.reddit.com/search/?q={}",
}

def web_dispatch(query: str = "", engine: str = "google", url: str = None) -> str:
    if url and url.strip():
        target = url.strip()
        if not target.startswith("http://") and not target.startswith("https://"):
            target = f"https://{target}"
        webbrowser.open(target)
        return f"Opening {target}"
    q = query.strip()
    if not q:
        webbrowser.open("https://www.google.com")
        return "Opened browser home"
    eng = engine.lower().strip() if engine else "google"
    template = _ENGINES.get(eng, _ENGINES["google"])
    encoded = urllib.parse.quote_plus(q)
    target_url = template.format(encoded)
    webbrowser.open(target_url)
    return f"Searching {eng.capitalize()} for '{q}'"
