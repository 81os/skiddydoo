from io import BytesIO
from typing import Any, Dict, List, Optional

from anyio import Path as AsyncPath
from pydantic import BaseModel, Field


class LiveChat(BaseModel):
    url: Optional[str] = Field(None, title="Url")
    video_id: Optional[str] = Field(None, title="Video Id")
    ext: Optional[str] = Field(None, title="Ext")
    protocol: Optional[str] = Field(None, title="Protocol")


class Subtitles(BaseModel):
    live_chat: Optional[List[LiveChat]] = Field(None, title="Live Chat")


class Fragment(BaseModel):
    url: Optional[str] = Field(None, title="Url")
    duration: Optional[float] = Field(None, title="Duration")


class Thumbnail(BaseModel):
    url: Optional[str] = Field(None, title="Url")
    preference: Optional[int] = Field(None, title="Preference")
    id: Optional[str] = Field(None, title="Id")
    height: Optional[int] = Field(None, title="Height")
    width: Optional[int] = Field(None, title="Width")
    resolution: Optional[str] = Field(None, title="Resolution")


class HttpHeaders(BaseModel):
    User_Agent: Optional[str] = Field(None, alias="User-Agent", title="User-Agent")
    Accept: Optional[str] = Field(None, title="Accept")
    Accept_Language: Optional[str] = Field(
        None, alias="Accept-Language", title="Accept-Language"
    )
    Sec_Fetch_Mode: Optional[str] = Field(
        None, alias="Sec-Fetch-Mode", title="Sec-Fetch-Mode"
    )


class DownloaderOptions(BaseModel):
    http_chunk_size: Optional[int] = Field(None, title="Http Chunk Size")


class Format(BaseModel):
    format_id: Optional[str] = Field(None, title="Format Id")
    format_note: Optional[str] = Field(None, title="Format Note")
    ext: Optional[str] = Field(None, title="Ext")
    protocol: Optional[str] = Field(None, title="Protocol")
    acodec: Optional[str] = Field(None, title="Acodec")
    vcodec: Optional[str] = Field(None, title="Vcodec")
    url: Optional[str] = Field(None, title="Url")
    width: Optional[int] = Field(None, title="Width")
    height: Optional[int] = Field(None, title="Height")
    fps: Optional[float] = Field(None, title="Fps")
    rows: Optional[int] = Field(None, title="Rows")
    columns: Optional[int] = Field(None, title="Columns")
    fragments: Optional[List[Fragment]] = Field(None, title="Fragments")
    audio_ext: Optional[str] = Field(None, title="Audio Ext")
    video_ext: Optional[str] = Field(None, title="Video Ext")
    format: Optional[str] = Field(None, title="Format")
    resolution: Optional[str] = Field(None, title="Resolution")
    http_headers: Optional[HttpHeaders] = None
    asr: Optional[int] = Field(None, title="Asr")
    filesize: Optional[int] = Field(None, title="Filesize")
    source_preference: Optional[int] = Field(None, title="Source Preference")
    audio_channels: Optional[int] = Field(None, title="Audio Channels")
    quality: Optional[int] = Field(None, title="Quality")
    has_drm: Optional[Any] = Field(None, title="Has Drm")
    tbr: Optional[float] = Field(None, title="Tbr")
    language: Optional[str] = Field(None, title="Language")
    language_preference: Optional[int] = Field(None, title="Language Preference")
    preference: Optional[int] = Field(None, title="Preference")
    dynamic_range: Optional[str] = Field(None, title="Dynamic Range")
    abr: Optional[float] = Field(None, title="Abr")
    downloader_options: Optional[DownloaderOptions] = None
    container: Optional[str] = Field(None, title="Container")
    vbr: Optional[float] = Field(None, title="Vbr")
    filesize_approx: Optional[int] = Field(None, title="Filesize Approx")


class RequestedDownload(BaseModel):
    epoch: Optional[int]
    filepath: str
    file_size: Optional[int] = 0

    async def read(self) -> BytesIO:
        target = AsyncPath(self.filepath)
        buffer = await target.read_bytes()
        return BytesIO(buffer)


class Information(BaseModel):
    id: Optional[str] = Field(None, title="Id")
    title: str = Field(None, title="Title")
    formats: Optional[List[Format]] = Field(None, title="Formats")
    thumbnails: Optional[List[Thumbnail]] = Field(None, title="Thumbnails")
    thumbnail: Optional[str] = Field(None, title="Thumbnail")
    description: Optional[str] = Field(None, title="Description")
    uploader: Optional[str] = Field(None, title="Uploader")
    uploader_id: Optional[str] = Field(None, title="Uploader Id")
    uploader_url: Optional[str] = Field(None, title="Uploader Url")
    channel_id: Optional[str] = Field(None, title="Channel Id")
    channel_url: Optional[str] = Field(None, title="Channel Url")
    duration: Optional[int] = Field(None, title="Duration")
    view_count: Optional[int] = Field(0, title="View Count")
    average_rating: Optional[Any] = Field(None, title="Average Rating")
    age_limit: Optional[int] = Field(None, title="Age Limit")
    webpage_url: Optional[str] = Field(None, title="Webpage Url")
    categories: Optional[List[str]] = Field(None, title="Categories")
    tags: Optional[List[str]] = Field(None, title="Tags")
    playable_in_embed: Optional[bool] = Field(None, title="Playable In Embed")
    is_live: Optional[bool] = Field(None, title="Is Live")
    was_live: Optional[bool] = Field(None, title="Was Live")
    live_status: Optional[str] = Field(None, title="Live Status")
    release_timestamp: Optional[int] = Field(None, title="Release Timestamp")
    automatic_captions: Optional[Dict[str, Any]] = Field(
        None, title="Automatic Captions"
    )
    subtitles: Optional[Subtitles] = None
    comment_count: Optional[Any] = Field(0, title="Comment Count")
    chapters: Optional[Any] = Field(None, title="Chapters")
    like_count: Optional[int] = Field(0, title="Like Count")
    channel: Optional[str] = Field(None, title="Channel")
    channel_follower_count: Optional[int] = Field(None, title="Channel Follower Count")
    upload_date: Optional[str] = Field(None, title="Upload Date")
    availability: Optional[str] = Field(None, title="Availability")
    original_url: Optional[str] = Field(None, title="Original Url")
    webpage_url_basename: Optional[str] = Field(None, title="Webpage Url Basename")
    webpage_url_domain: Optional[str] = Field(None, title="Webpage Url Domain")
    extractor: Optional[str] = Field(None, title="Extractor")
    extractor_key: Optional[str] = Field(None, title="Extractor Key")
    playlist_count: Optional[int] = Field(None, title="Playlist Count")
    playlist: Optional[str] = Field(None, title="Playlist")
    playlist_id: Optional[str] = Field(None, title="Playlist Id")
    playlist_title: Optional[str] = Field(None, title="Playlist Title")
    playlist_uploader: Optional[Any] = Field(None, title="Playlist Uploader")
    playlist_uploader_id: Optional[Any] = Field(None, title="Playlist Uploader Id")
    n_entries: Optional[int] = Field(None, title="N Entries")
    playlist_index: Optional[int] = Field(None, title="Playlist Index")
    playlist_autonumber: Optional[int] = Field(None, title="Playlist Autonumber")
    display_id: Optional[str] = Field(None, title="Display Id")
    fulltitle: Optional[str] = Field(None, title="Fulltitle")
    duration_string: Optional[str] = Field(None, title="Duration String")
    release_date: Optional[str] = Field(None, title="Release Date")
    requested_subtitles: Optional[Any] = Field(None, title="Requested Subtitles")
    asr: Optional[int] = Field(None, title="Asr")
    filesize: Optional[int] = Field(None, title="Filesize")
    format_id: Optional[str] = Field(None, title="Format Id")
    format_note: Optional[str] = Field(None, title="Format Note")
    source_preference: Optional[int] = Field(None, title="Source Preference")
    fps: Optional[Any] = Field(None, title="Fps")
    audio_channels: Optional[int] = Field(None, title="Audio Channels")
    height: Optional[Any] = Field(None, title="Height")
    quality: Optional[int] = Field(None, title="Quality")
    has_drm: Optional[bool] = Field(None, title="Has Drm")
    tbr: Optional[float] = Field(None, title="Tbr")
    url: Optional[str] = Field(None, title="Url")
    width: Optional[Any] = Field(None, title="Width")
    language: Optional[str] = Field(None, title="Language")
    language_preference: Optional[int] = Field(None, title="Language Preference")
    preference: Optional[Any] = Field(None, title="Preference")
    ext: Optional[str] = Field(None, title="Ext")
    vcodec: Optional[str] = Field(None, title="Vcodec")
    acodec: Optional[str] = Field(None, title="Acodec")
    dynamic_range: Optional[Any] = Field(None, title="Dynamic Range")
    abr: Optional[float] = Field(None, title="Abr")
    downloader_options: Optional[DownloaderOptions] = None
    container: Optional[str] = Field(None, title="Container")
    protocol: Optional[str] = Field(None, title="Protocol")
    audio_ext: Optional[str] = Field(None, title="Audio Ext")
    video_ext: Optional[str] = Field(None, title="Video Ext")
    format: Optional[str] = Field(None, title="Format")
    resolution: Optional[str] = Field(None, title="Resolution")
    http_headers: Optional[HttpHeaders] = None
    requested_downloads: Optional[list[RequestedDownload]]
