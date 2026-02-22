import random
from typing import List, Set, Dict, Optional, Tuple
from dataclasses import dataclass
import spotipy
import math

@dataclass(frozen=True)
class Track:
    id: str
    name: str
    artist: str
    spotify_url: str


def get_artist_albums(sp: spotipy.Spotify, artist_id: str, limit: int = 10) -> List[str]:
    """
    Returns a list of album IDs for an artist (albums + singles).
    Uses pagination up to `limit`.
    """
    album_ids: List[str] = []
    seen: Set[str] = set()

    results = sp.artist_albums(
        artist_id,
        album_type="album,single",
        country="US",
        limit=min(10, limit),   # Spotify search limit changed; keep small and paginate if needed
        offset=0
    )

    while results and len(album_ids) < limit:
        for item in results.get("items", []):
            album_artists = [a.get("id") for a in item.get("artists", [])]
            if artist_id not in album_artists:
                continue
            aid = item.get("id")
            if aid and aid not in seen:
                seen.add(aid)
                album_ids.append(aid)
                if len(album_ids) >= limit:
                    break

        results = sp.next(results) if results.get("next") and len(album_ids) < limit else None

    return album_ids


def get_album_tracks(
    sp: spotipy.Spotify,
    album_id: str,
    allowed_artist_ids: Optional[Set[str]] = None,
    solo_only=False,
    limit: int = 50
) -> List[Track]:
    """
    Returns tracks from an album ID.
    If allowed_artist_ids is provided, only keep tracks that include one of those artists.
    """
    out: List[Track] = []
    results = sp.album_tracks(album_id, limit=min(50, limit), offset=0)

    while results:
        for t in results.get("items", []):
            track_id = t.get("id")
            if not track_id:
                continue

            track_artist_ids = {a.get("id") for a in t.get("artists", []) if a.get("id")}
            if allowed_artist_ids is not None and track_artist_ids.isdisjoint(allowed_artist_ids):
                continue
            if solo_only and allowed_artist_ids is not None:
                if track_artist_ids != allowed_artist_ids:
                    continue

            track_name = t.get("name", "Unknown Track")
            artist_name = ", ".join(a.get("name", "") for a in t.get("artists", [])) or "Unknown Artist"
            url = t.get("external_urls", {}).get("spotify", "")
            out.append(Track(id=track_id, name=track_name, artist=artist_name, spotify_url=url))

        results = sp.next(results) if results.get("next") else None

    return out

def build_playlist(
    sp: spotipy.Spotify,
    seed_artist_ids: List[str],
    target_size: int = 40,
    albums_per_artist: int = 10,
    tracks_per_album: int = 2,
    shuffle: bool = True,
    solo_only: bool = False,
) -> List[Track]:
    if not seed_artist_ids:
        return []

    # Build a candidate pool per artist
    def artist_pool(aid: str, solo_only: bool) -> List[Track]:
        pool: List[Track] = []
        album_ids = get_artist_albums(sp, aid, limit=albums_per_artist)
        for album_id in album_ids:
            tracks = get_album_tracks(sp, album_id, allowed_artist_ids={aid}, solo_only=solo_only)
            if shuffle:
                random.shuffle(tracks)
            # cap per album so one album doesn't dominate
            pool.extend(tracks[:tracks_per_album])
        if shuffle:
            random.shuffle(pool)
        return pool

    pools: Dict[str, List[Track]] = {aid: artist_pool(aid, solo_only) for aid in seed_artist_ids}
    seen: Set[str] = set()
    playlist: List[Track] = []
    seen_names: Set[tuple[str, str]] = set()

    # If only 1 artist: just fill from that pool up to target_size
    if len(seed_artist_ids) == 1:
        aid = seed_artist_ids[0]
        for tr in pools[aid]:
            if len(playlist) >= target_size:
                break
            if not tr.id:
                continue
            name_key = (tr.name.lower().strip(), tr.artist.lower().strip())

            if tr.id in seen or name_key in seen_names:
                continue

            seen.add(tr.id)
            seen_names.add(name_key)
            playlist.append(tr)
        return playlist[:target_size]

    # Multiple artists: round-robin fill with a per-artist cap
    per_artist_cap = max(1, math.ceil(target_size / len(seed_artist_ids)))
    contributed = {aid: 0 for aid in seed_artist_ids}

    made_progress = True
    while len(playlist) < target_size and made_progress:
        made_progress = False
        for aid in seed_artist_ids:
            if len(playlist) >= target_size:
                break
            if contributed[aid] >= per_artist_cap:
                continue

            while pools[aid]:
                tr = pools[aid].pop(0)
                if not tr.id:
                    continue

                name_key = (tr.name.lower().strip(), tr.artist.lower().strip())
                if tr.id in seen or name_key in seen_names:
                    continue

                seen.add(tr.id)
                seen_names.add(name_key)
                playlist.append(tr)
                contributed[aid] += 1
                made_progress = True
                break

    if shuffle:
        random.shuffle(playlist)
    return playlist[:target_size]
if __name__ == "__main__":
    print("Running playlist generator...")

    # 1) put the artist NAMES here
    seed_names = input("Enter artists (comma-separated): ").split(",")
    seed_names = [s.strip() for s in seed_names if s.strip()]
    target_size = int(input("How many songs do you want? (e.g., 40): ") or "40")

    # 2) create Spotify client
    import os
    from spotipy.oauth2 import SpotifyClientCredentials

    def get_spotify_client() -> spotipy.Spotify:
        client_id = os.getenv("SPOTIPY_CLIENT_ID")
        client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise RuntimeError("Missing SPOTIPY_CLIENT_ID or SPOTIPY_CLIENT_SECRET.")
        return spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=client_id,
                client_secret=client_secret
            )
        )

    def search_artist_id(sp: spotipy.Spotify, artist_name: str) -> Optional[Tuple[str, str]]:
        results = sp.search(q=artist_name, type="artist", limit=10)
        items = results.get("artists", {}).get("items", [])
        if not items:
            return None

    # 1) Prefer exact name match
        for a in items:
            if a.get("name", "").lower() == artist_name.lower():
                return a["id"], a["name"]

    # 2) Otherwise, choose the most popular result
        best = max(items, key=lambda x: x.get("popularity", 0))
        return best["id"], best["name"]

    sp = get_spotify_client()

    # 3) resolve names -> IDs
    seed_ids = []
    not_found = []

    for name in seed_names:
        result = search_artist_id(sp, name)
        if not result:
            not_found.append(name)
            continue
        artist_id, _canonical = result
        seed_ids.append(artist_id)
    MAX_ARTISTS = 5
    if len(seed_names) > MAX_ARTISTS:
        print(f"\nNote: You entered {len(seed_names)} artists. Using the first {MAX_ARTISTS}:")
        print(", ".join(seed_names[:MAX_ARTISTS]))
        seed_names = seed_names[:MAX_ARTISTS]
    if not seed_ids:
        raise RuntimeError(f"No artists found. Not found: {not_found}")

    # 4) build playlist from discography sampling
    playlist = build_playlist(
        sp,
        seed_ids,
        target_size=target_size,
        albums_per_artist=20,
        tracks_per_album=5,
        shuffle=True,
        solo_only=True
    )
    import csv

    with open("playlist.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["track", "artist", "spotify_url"])
        for t in playlist:
            w.writerow([t.name, t.artist, t.spotify_url])
    print("\nSaved to playlist.csv")
    
    print("\nGenerated playlist:\n")
    for i, t in enumerate(playlist[:target_size], start=1):
        print(f"{i:02d}. {t.name} — {t.artist}")
        print(f"    {t.spotify_url}")

    if not_found:
        print("\nArtists not found:", ", ".join(not_found))