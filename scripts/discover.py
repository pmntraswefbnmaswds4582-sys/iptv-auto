from urllib.request import Request, urlopen
from urllib.parse import urlparse
from pathlib import Path
import re
import json
import time

# 公开、可访问的 M3U 播放列表来源
SOURCE_URLS = [
    "https://iptv-org.github.io/iptv/index.m3u",
    "https://iptv-org.github.io/iptv/index.category.m3u",
    "https://iptv-org.github.io/iptv/index.country.m3u",
]

OUTPUT_DIR = Path("output")
RAW_FILE = OUTPUT_DIR / "discovered.json"

TIMEOUT = 20
MAX_CHANNELS = 20000


def download(url):
    """下载公开 M3U 文件"""
    print(f"[下载] {url}")

    request = Request(
        url,
        headers={
            "User-Agent": "iptv-auto/1.0"
        }
    )

    with urlopen(request, timeout=TIMEOUT) as response:
        data = response.read()

    return data.decode("utf-8", errors="ignore")


def parse_m3u(text):
    """解析 M3U"""
    lines = [x.strip() for x in text.splitlines() if x.strip()]

    channels = []
    current_info = None

    for line in lines:

        if line.startswith("#EXTINF"):
            current_info = line

        elif (
            current_info
            and not line.startswith("#")
            and (
                line.startswith("http://")
                or line.startswith("https://")
            )
        ):

            name = current_info.split(",")[-1].strip()

            group_match = re.search(
                r'group-title="([^"]*)"',
                current_info,
                re.IGNORECASE
            )

            tvg_id_match = re.search(
                r'tvg-id="([^"]*)"',
                current_info,
                re.IGNORECASE
            )

            group = (
                group_match.group(1)
                if group_match
                else "未分类"
            )

            tvg_id = (
                tvg_id_match.group(1)
                if tvg_id_match
                else ""
            )

            channels.append({
                "name": name,
                "group": group,
                "tvg_id": tvg_id,
                "url": line
            })

            current_info = None

            if len(channels) >= MAX_CHANNELS:
                break

    return channels


def is_valid_url(url):
    """过滤明显异常地址"""

    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False

        if not parsed.netloc:
            return False

        return True

    except Exception:
        return False


def clean_channels(channels):
    """去重和基础清洗"""

    result = []
    seen_urls = set()
    seen_pairs = set()

    for channel in channels:

        url = channel["url"].strip()
        name = channel["name"].strip()

        if not name:
            continue

        if not is_valid_url(url):
            continue

        # URL 完全重复
        if url in seen_urls:
            continue

        # 同频道 + 同地址重复
        pair = (name.lower(), url)

        if pair in seen_pairs:
            continue

        seen_urls.add(url)
        seen_pairs.add(pair)

        result.append(channel)

    return result


def main():

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_channels = []

    for source in SOURCE_URLS:

        try:

            text = download(source)

            channels = parse_m3u(text)

            print(
                f"[解析] {len(channels)} 个频道"
            )

            all_channels.extend(channels)

            time.sleep(1)

        except Exception as e:

            print(
                f"[失败] {source}"
            )

            print(
                f"       {e}"
            )

    print(
        f"[总计] 原始频道：{len(all_channels)}"
    )

    channels = clean_channels(all_channels)

    print(
        f"[清洗] 有效频道：{len(channels)}"
    )

    data = {
        "generated_at": int(time.time()),
        "source_count": len(SOURCE_URLS),
        "channel_count": len(channels),
        "channels": channels
    }

    RAW_FILE.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        f"[完成] 已保存：{RAW_FILE}"
    )


if __name__ == "__main__":
    main()
