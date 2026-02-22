import random
from typing import List, Set, Optional, Tuple
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


def get_album_tracks(sp: spotipy.Spotify, album_id: str, limit: int = 50) -> List[Track]:
    """
    Returns tracks from an album ID.
    """
    out: List[Track] = []
    results = sp.album_tracks(album_id, limit=min(50, limit), offset=0)

    while results:
        for t in results.get("items", []):
            track_id = t.get("id")
            track_name = t.get("name", "Unknown Track")
            artist_name = ", ".join(a.get("name", "") for a in t.get("artists", [])) or "Unknown Artist"
            url = t.get("external_urls", {}).get("spotify", "")
            if track_id:
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
) -> List[Track]:
    """
    Creates a playlist by sampling tracks from each artist's albums/singles,
    ensuring each artist contributes (roughly) evenly.
    """
    if not seed_artist_ids:
        return []

    per_artist_cap = math.ceil(target_size / len(seed_artist_ids))

    playlist: List[Track] = []
    seen_tracks: Set[str] = set()

    for artist_id in seed_artist_ids:
        added_for_artist = 0

        album_ids = get_artist_albums(sp, artist_id, limit=albums_per_artist)
        for album_id in album_ids:
            tracks = get_album_tracks(sp, album_id)

            if shuffle:
                random.shuffle(tracks)

            for tr in tracks:
                if tr.id in seen_tracks:
                    continue
                seen_tracks.add(tr.id)
                playlist.append(tr)
                added_for_artist += 1

                # stop this artist once they hit their quota
                if added_for_artist >= per_artist_cap:
                    break

                # stop entirely once we hit target size
                if len(playlist) >= target_size:
                    break

            if added_for_artist >= per_artist_cap or len(playlist) >= target_size:
                break

        if len(playlist) >= target_size:
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

    def search_artist_id(sp: spotipy.Spotify, artist_name: str) -> Optional[str]:
        results = sp.search(q=f"artist:{artist_name}", type="artist", limit=1)
        items = results.get("artists", {}).get("items", [])
        if not items:
            return None
        return items[0]["id"]

    sp = get_spotify_client()

    # 3) resolve names -> IDs
    seed_ids = []
    not_found = []
    for name in seed_names:
        aid = search_artist_id(sp, name)
        if aid is None:
            not_found.append(name)
        else:
            seed_ids.append(aid)

    if not seed_ids:
        raise RuntimeError(f"No artists found. Not found: {not_found}")

    # 4) build playlist from discography sampling
    playlist = build_playlist(
        sp,
        seed_ids,
        target_size=50,
        albums_per_artist=10,
        tracks_per_album=2,
        shuffle=True,
    )
    import csv

    with open("playlist.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["track", "artist", "spotify_url"])
        for t in playlist:
            w.writerow([t.name, t.artist, t.spotify_url])
    print("\nSaved to playlist.csv")
    
    print("\nGenerated playlist:\n")
    for i, t in enumerate(playlist, start=1):
        print(f"{i:02d}. {t.name} — {t.artist}")
        print(f"    {t.spotify_url}")

    if not_found:
        print("\nArtists not found:", ", ".join(not_found))