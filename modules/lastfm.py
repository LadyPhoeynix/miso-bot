import asyncio
import math
import urllib.parse
from enum import Enum

import aiohttp
import arrow
import orjson
from bs4 import BeautifulSoup
from loguru import logger

from modules import exceptions
from modules.misobot import MisoBot


def int_bool(value: bool | None) -> int | None:
    """Turn optional bool into 1 or 0."""
    return int(value) if value is not None else None


def non_empty(data: dict):
    if data:
        return data
    else:
        raise exceptions.LastFMError(error_code=0, message="Last.fm returned no data")


class LastFmImage:
    MISSING_IMAGE_HASH = "2a96cbd8b46e442fc41c2b86b821562f"
    CDN_BASE_URL = "https://lastfm.freetls.fastly.net/i/u/"

    def __init__(self, hash: str):
        self.hash = hash

    @classmethod
    def from_url(cls, url: str):
        return cls(url.split("/")[-1].split(".")[0])

    def _get_res(self, res: str):
        return self.CDN_BASE_URL + res + self.hash

    def is_missing(self):
        return self.hash == self.MISSING_IMAGE_HASH

    def as_34s(self):
        return self._get_res("34s/")

    def as_64s(self):
        return self._get_res("64s/")

    def as_174s(self):
        return self._get_res("174s/")

    def as_300(self):
        return self._get_res("300x300/")

    def as_full(self):
        return self._get_res("")


class Period(Enum):
    """Time period used by the Api."""

    OVERALL = "overall"
    WEEK = "7day"
    MONTH = "1month"
    QUARTER = "3month"
    HALFYEAR = "6month"
    YEAR = "12month"

    def web_format(self):
        """Time period as formatted in the web queries."""
        match self:
            case Period.OVERALL:
                return "ALL"
            case Period.WEEK:
                return "LAST_7_DAYS"
            case Period.MONTH:
                return "LAST_30_DAYS"
            case Period.QUARTER:
                return "LAST_90_DAYS"
            case Period.HALFYEAR:
                return "LAST_180_DAYS"
            case Period.YEAR:
                return "LAST_365_DAYS"

    def display(self):
        match self:
            case Period.OVERALL:
                return "Alltime"
            case Period.WEEK:
                return "Weekly"
            case Period.MONTH:
                return "Monthly"
            case Period.QUARTER:
                return "Quarterly"
            case Period.HALFYEAR:
                return "6 month"
            case Period.YEAR:
                return "Yearly"

    def __str__(self):
        match self:
            case Period.OVERALL:
                return "Alltime"
            case Period.WEEK:
                return "Week"
            case Period.MONTH:
                return "Month"
            case Period.QUARTER:
                return "Quarter"
            case Period.HALFYEAR:
                return "Half a year"
            case Period.YEAR:
                return "Year"


class LastFmApi:
    LASTFM_RED = "b90000"
    API_BASE_URL = "http://ws.audioscrobbler.com/2.0/"

    def __init__(self, bot: MisoBot):
        self.bot = bot

    async def api_request(self, method: str, params: dict) -> dict:
        """Make a request to the lastfm api, returns json."""
        # add auth params, remove null values and combine to single dict
        request_params = {
            "method": method,
            "api_key": self.bot.keychain.LASTFM_API_KEY,
            "format": "json",
        } | {k: v for k, v in params.items() if v is not None}

        print(request_params)

        async with self.bot.session.get(self.API_BASE_URL, params=request_params) as response:
            try:
                content = await response.json(loads=orjson.loads)
            except aiohttp.ContentTypeError:
                text = await response.text()
                raise exceptions.LastFMError(error_code=response.status, message=text)

            error_code = content.get("error")
            if error_code:
                raise exceptions.LastFMError(
                    error_code=error_code,
                    message=content.get("message"),
                )

            logger.info(content)
            return content

    ###############
    # API METHODS #
    ###############

    async def user_get_info(self, username: str) -> dict:
        """Get information about a user profile."""
        data = await self.api_request(
            "user.getinfo",
            {
                "user": username,
            },
        )
        return data["user"]

    async def user_get_recent_tracks(
        self,
        username: str,
        limit: int | None = None,
        page: int | None = None,
        from_ts: int | None = None,
        to_ts: int | None = None,
        extended: bool | None = None,
    ) -> dict:
        """Returns a list of the tracks recently scrobbled by this user.
        Adds a nowplaying flag with a boolean value if the user is currently scrobbling."""
        data = await self.api_request(
            "user.getrecenttracks",
            {
                "user": username,
                "limit": limit,
                "page": page,
                "from": from_ts,
                "to": to_ts,
                "extended": int_bool(extended),
            },
        )
        data = data["recenttracks"]

        if (
            (
                (to_ts is not None and to_ts < int(data["track"][0]["date"]["uts"]))
                or (page is not None)
            )
            and data["track"][0].get("@attr")
            and data["track"][0]["@attr"].get("nowplaying") == "true"
        ):
            # get rid of nowplaying track if user is currently scrobbling.
            # for some reason it appears even if it's not in the requested timeframe.
            data["track"] = data["track"][1:]

        return non_empty(data)

    async def user_get_top_albums(
        self,
        username: str,
        period: Period | None = None,
        limit: int | None = None,
        page: int | None = None,
    ) -> dict:
        """Get the top albums listened to by a user. You can stipulate a time period.
        Sends the overall chart by default."""
        data = await self.api_request(
            "user.gettopalbums",
            {
                "user": username,
                "period": period.value if period else None,
                "limit": limit,
                "page": page,
            },
        )
        return non_empty(data["topalbums"])

    async def user_get_top_artists(
        self,
        username: str,
        period: Period | None = None,
        limit: int | None = None,
        page: int | None = None,
    ) -> dict:
        """Get the top artists listened to by a user. You can stipulate a time period.
        Sends the overall chart by default."""
        data = await self.api_request(
            "user.gettopartists",
            {
                "user": username,
                "period": period.value if period else None,
                "limit": limit,
                "page": page,
            },
        )
        return non_empty(data["topartists"])

    async def user_get_top_tracks(
        self,
        username: str,
        period: Period | None = None,
        limit: int | None = None,
        page: int | None = None,
    ) -> dict:
        """Get the top tracks listened to by a user. You can stipulate a time period.
        Sends the overall chart by default."""
        data = await self.api_request(
            "user.gettoptracks",
            {
                "user": username,
                "period": period.value if period else None,
                "limit": limit,
                "page": page,
            },
        )
        return non_empty(data["toptracks"])

    async def artist_get_info(
        self,
        artist: str,
        username: str | None = None,
        autocorrect: bool | None = None,
    ) -> dict:
        """Get the metadata for an artist. Includes biography, truncated at 300 characters."""
        data = await self.api_request(
            "artist.getinfo",
            {
                "artist": artist,
                "username": username,
                "autocorrect": int_bool(autocorrect),
            },
        )
        return data["artist"]

    async def album_get_info(
        self,
        artist: str,
        album: str,
        username: str | None = None,
        autocorrect: bool | None = None,
    ) -> dict:
        """Get the metadata and tracklist for an album."""
        data = await self.api_request(
            "album.getinfo",
            {
                "artist": artist,
                "album": album,
                "username": username,
                "autocorrect": int_bool(autocorrect),
            },
        )
        return data["album"]

    async def track_get_info(
        self,
        artist: str,
        track: str,
        username: str | None = None,
        autocorrect: bool | None = None,
    ) -> dict:
        """Get the metadata for a track."""
        data = await self.api_request(
            "track.getinfo",
            {
                "artist": artist,
                "track": track,
                "username": username,
                "autocorrect": int_bool(autocorrect),
            },
        )
        return data["track"]

    ###########
    # HELPERS #
    ###########

    async def user_get_now_playing(self, username: str) -> dict:
        """Get the user's currently playing or most recent track with added nowplaying key."""
        data = await self.user_get_recent_tracks(username, limit=1)
        try:
            track: dict = data["track"][0]
        except KeyError:
            raise exceptions.LastFMError(error_code=0, message="Last.fm returned no data")

        now_playing = bool(track.get("@attr") and track["@attr"].get("nowplaying") == "true")
        track.pop("@attr", None)
        track["nowplaying"] = now_playing
        return track

    ################
    # WEB SCRAPING #
    ################

    async def scrape_page(self, page_url: str, params: dict | None = None, authenticated=False):
        """Scrapes the given url returning a Soup."""
        headers = {
            "Host": "www.last.fm",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:106.0) Gecko/20100101 Firefox/106.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "fi,en;q=0.7,en-US;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Cookie": self.bot.keychain.LASTFM_LOGIN_COOKIE,
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
        }
        async with self.bot.session.get(
            page_url, headers=headers if authenticated else None, params=params
        ) as response:
            response.raise_for_status()
            content = await response.text()
            soup = BeautifulSoup(content, "lxml")
            return soup

    @staticmethod
    def get_library_playcounts(soup: BeautifulSoup) -> list[tuple[str, int]]:
        """Scrape a listing page for playcounts."""
        results = []
        for row in soup.select(".chartlist-row"):
            name = row.select_one(".chartlist-name a")
            playcount = row.select_one("chartlist-count-bar-value")
            if name and playcount:
                results.append(
                    (
                        name.attrs["title"],
                        int(playcount.get_text().split()[0].replace(",", "")),
                    )
                )

        return results

    async def get_additional_library_pages(self, soup: BeautifulSoup, url: str):
        """Check for pagination on listing page and fetch all the remaining pages."""
        pages = soup.select(".pagination-page")
        if not pages:
            return []

        page_count = int(pages[-1].get_text())

        async def get_additional_page(n):
            new_url = url + f"&page={n}"
            soup = await self.scrape_page(new_url, authenticated=True)
            return self.get_library_playcounts(soup)

        tasks = []
        if page_count > 1:
            for i in range(2, page_count + 1):
                tasks.append(get_additional_page(i))

        results = []
        for result in await asyncio.gather(*tasks):
            results += result

        return results

    async def get_artist_image(self, artist_name: str):
        IMAGE_LIFETIME = 604800  # 1 week
        cached = await self.bot.db.fetch_row(
            "SELECT image_hash, scrape_date FROM artist_image_cache WHERE artist_name = %s",
            artist_name,
        )

        if cached:
            image_hash, scrape_date = cached
            lifetime = arrow.now().timestamp() - scrape_date.timestamp()
            if lifetime < IMAGE_LIFETIME:
                return LastFmImage(image_hash)

        image = await self.scrape_artist_image(artist_name)
        if image is None or image.is_missing():
            return None

        await self.bot.db.execute(
            """
            INSERT INTO artist_image_cache (artist_name, image_hash, scrape_date)
                VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                image_hash = VALUES(image_hash),
                scrape_date = VALUES(scrape_date)
            """,
            artist_name,
            image.hash,
            arrow.now().datetime,
        )
        return image

    async def scrape_artist_image(self, artist: str) -> LastFmImage | None:
        """Get artist's top image."""
        url = f"https://www.last.fm/music/{urllib.parse.quote_plus(artist)}/+images"
        soup = await self.scrape_page(url)
        image = soup.select_one(".image-list-item-wrapper a img")
        return LastFmImage.from_url(image.attrs["src"]) if image else None

    async def scrape_track_image(self, url: str) -> LastFmImage | None:
        """Get track's top album image."""
        soup = await self.scrape_page(f"{url}/+albums")
        image = soup.select_one(".cover-art img")
        return LastFmImage.from_url(image.attrs["src"]) if image else None

    async def library_artist_images(
        self,
        username: str,
        amount,
        period: Period | None = None,
    ) -> list[LastFmImage]:
        """Get image hashes for user's top n artists"""
        url: str = f"https://www.last.fm/user/{username}/library/artists"
        params = {"date_preset": period.web_format()} if period else {}

        tasks = []
        for i in range(1, math.ceil(amount / 50) + 1):
            if i > 1:
                params["page"] = str(i)
            tasks.append(asyncio.ensure_future(self.scrape_page(url, params, authenticated=i > 1)))

        images = []
        soup: BeautifulSoup
        for soup in await asyncio.gather(*tasks):
            if len(images) >= amount:
                break

            imagedivs = soup.select(".chartlist-image img")
            images += [LastFmImage.from_url(div.attrs["src"]) for div in imagedivs]

        return images
