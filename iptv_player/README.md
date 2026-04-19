# IPTV Player

A PyQt6-based IPTV player application that loads M3U/M3U8 playlist files and allows you to browse channels grouped by TV group, view channel logos, switch between multiple sources for each channel, display EPG (Electronic Program Guide) data, and handle EXTVLCOPT tags for special playback requirements. Video playback is handled by mpv media player with automatic conversion of VLC options to mpv equivalents.

## Features

- Load M3U/M3U8 playlist files using the m3u8 library with custom_tags_parser
- Parse EXTINF tags for tvg-id, tvg-logo, group-title, and other attributes
- Extract x-tvg-url from M3U header for EPG data
- Display channels grouped by tv-group in a tree view
- Show channel logos from tvg-logo attribute
- Support for multiple sources per channel
- Switch between different sources for the same channel
- Display EPG program guide when a channel is selected
- **Support for EXTVLCOPT tags** (http-user-agent, http-referrer, network-caching, program, etc.)
- **Support for HLS encryption keys** (#EXT-X-KEY with METHOD, URI, IV)
- Automatic conversion of VLC options to mpv equivalent options
- Automatic handling of AES-128 encrypted streams via mpv
- Video playback using mpv (via subprocess)
- Play/Stop controls
- Status bar with playback information

## Requirements

- Python 3.10+
- PyQt6
- m3u8
- mpv media player (must be installed separately)

## Installation

### Install Python dependencies

```bash
pip install -r requirements.txt
```

Or install PyQt6 directly:

```bash
pip install "PyQt6>=6.7.0"
```

### Install mpv

**Linux (Ubuntu/Debian):**
```bash
sudo apt install mpv
```

**macOS:**
```bash
brew install mpv
```

**Windows:**
Download from https://mpv.io/installation/ and add mpv to your PATH

## Usage

Run the application:

```bash
python iptv_player.py
```

Then:
1. Click "Load M3U File" to load your playlist
2. Select a channel from the list on the right
3. Choose a source from the dropdown below the video area
4. Click "Play" to start streaming (video will appear in a separate mpv window)

## Project Structure

```
iptv_player/
├── iptv_player.py    # Main application code
├── m3u_parser.py     # Custom M3U/M3U8 parser using m3u8 library
├── requirements.txt   # Python dependencies
├── README.md         # This file
└── sample_playlist.m3u8  # Sample playlist for testing
```

## M3U Format

The parser supports standard M3U format with EXTINF tags including tvg-id, tvg-logo, group-title attributes, x-tvg-url in the header, EXTVLCOPT tags for special playback requirements, and #EXT-X-KEY tags for HLS encryption:

```
#EXTM3U x-tvg-url="https://example.com/epg.xml"
#EXTINF:-1 tvg-id="ChannelID" tvg-logo="https://example.com/logo.png" group-title="Movies",Channel Name
#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)
#EXTVLCOPT:http-referrer=https://example.com
http://example.com/stream1.m3u8
http://example.com/stream2.m3u8
#EXTINF:-1 tvg-id="NewsID" tvg-logo="https://example.com/logo2.png" group-title="News",Another Channel
#EXTVLCOPT:network-caching=3000
http://example.com/another-stream.m3u8
#EXTINF:-1 tvg-id="EncryptedID" group-title="Premium",Encrypted Channel
#EXT-X-KEY:METHOD=AES-128,URI="http://example.com/key.key",IV=0x1234567890abcdef1234567890abcdef
http://example.com/encrypted-stream.m3u8
```

Multiple URLs under the same EXTINF tag are treated as alternative sources for that channel. Channels are automatically grouped by their `group-title` attribute, logos from `tvg-logo` are displayed in the channel list, and EPG data is loaded from the `x-tvg-url` specified in the header. The `tvg-id` attribute is used to match channels with their EPG programs.

### Supported EXTVLCOPT Options

The following VLC options are automatically converted to mpv equivalents:

- `http-user-agent` → `--user-agent` (Set custom User-Agent header)
- `http-referrer` → `--referrer` (Set HTTP referrer header)
- `program` → `--program` (Select specific program in MPEG-TS)
- `network-caching` → `--cache-secs` (Network caching in milliseconds, converted to seconds)
- `live-caching` → `--cache-secs` (Live stream caching in milliseconds, converted to seconds)

Unknown options are passed as `--{option}={value}` when possible. Boolean options (with value "true") are ignored.

### HLS Encryption Support

The player supports HLS encrypted streams using the #EXT-X-KEY tag:

```
#EXT-X-KEY:METHOD=AES-128,URI="http://example.com/key.key",IV=0x1234567890abcdef1234567890abcdef
```

Supported attributes:
- `METHOD` - Encryption method (currently supports AES-128)
- `URI` - URL to fetch the decryption key
- `IV` - Initialization Vector (optional, passed to mpv via --hls-aes-iv)

When an encrypted channel is played, mpv automatically handles the key fetching from the URI and decryption. If an IV is specified in the playlist, it is explicitly passed to mpv.

## How It Works

- The application uses mpv media player as a subprocess for video playback
- mpv is called with `--no-terminal` and `--force-window` flags
- When you select a channel and click Play, a new mpv window opens with the stream
- You can switch between sources for the same channel using the dropdown selector
- The Stop button terminates the mpv process

## License

MIT License
