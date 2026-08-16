from urllib.request import Request, urlopen
from pathlib import Path
import re
import json
import time


# ============================================================
# 自动 IPTV 频道发现器
#
# 目标：
# CCTV / CCTV-4K / 港澳台 / 凤凰 / 广东 / 卫视 / 体育
#
# 注意：
# 这里只处理公开、无需登录、无需绕过访问控制的播放列表。
# ============================================================

SOURCE_URLS = [
    "https://iptv-org.github.io/iptv/index.m3u",
    "https://iptv-org.github.io/iptv/countries/cn.m3u",
    "https://iptv-org.github.io/iptv/countries/hk.m3u",
    "https://iptv-org.github.io/iptv/countries/mo.m3u",
    "https://iptv-org.github.io/iptv/countries/tw.m3u",
]

OUTPUT_DIR = Path("output")

RAW_FILE = OUTPUT_DIR / "discovered.json"

TIMEOUT = 20


# ============================================================
# 频道分类关键词
# ============================================================

CCTV_KEYWORDS = [
    "CCTV",
    "央视",
    "中央电视台",
]

CCTV_4K_KEYWORDS = [
    "CCTV-4K",
    "CCTV4K",
    "CCTV 4K",
    "CCTV UHD",
    "CCTV-UHD",
]

PHOENIX_KEYWORDS = [
    "凤凰卫视",
    "凤凰资讯",
    "凤凰中文",
    "Phoenix",
    "PHOENIX",
]

HONG_KONG_KEYWORDS = [
    "香港",
    "HK",
    "TVB",
    "ViuTV",
]

MACAU_KEYWORDS = [
    "澳门",
    "Macau",
    "Macao",
]

TAIWAN_KEYWORDS = [
    "台湾",
    "台灣",
    "Taiwan",
]

GUANGDONG_KEYWORDS = [
    "广东体育",
    "廣東體育",
    "广东卫视",
    "廣東衛視",
    "广东新闻",
    "廣東新聞",
    "广东公共",
    "廣東公共",
]

SPORTS_KEYWORDS = [
    "体育",
    "體育",
    "Sports",
    "SPORT",
    "CCTV-5",
    "CCTV5",
]


# ============================================================
# 下载 M3U
# ============================================================

def download(url):

    print(f"[下载] {url}")

    request = Request(
        url,
        headers={
            "User-Agent": "iptv-auto/1.0"
        }
    )

    with urlopen(
        request,
        timeout=TIMEOUT
    ) as response:

        data = response.read()

    return data.decode(
        "utf-8",
        errors="ignore"
    )


# ============================================================
# 解析 M3U
# ============================================================

def parse_m3u(text):

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    channels = []

    current_info = None

    for line in lines:

        if line.startswith("#EXTINF"):

            current_info = line

            continue

        if (
            current_info
            and not line.startswith("#")
            and (
                line.startswith("http://")
                or line.startswith("https://")
            )
        ):

            name = current_info.split(
                ",",
                1
            )[-1].strip()

            tvg_id = extract_attribute(
                current_info,
                "tvg-id"
            )

            group = extract_attribute(
                current_info,
                "group-title"
            )

            logo = extract_attribute(
                current_info,
                "tvg-logo"
            )

            channels.append({
                "name": name,
                "tvg_id": tvg_id,
                "group": group,
                "logo": logo,
                "url": line,
            })

            current_info = None

    return channels


# ============================================================
# 提取 EXTINF 属性
# ============================================================

def extract_attribute(
    text,
    attribute
):

    pattern = (
        rf'{re.escape(attribute)}="([^"]*)"'
    )

    match = re.search(
        pattern,
        text,
        re.IGNORECASE
    )

    if match:

        return match.group(1).strip()

    return ""


# ============================================================
# 判断关键词
# ============================================================

def contains_keyword(
    text,
    keywords
):

    text = text.lower()

    for keyword in keywords:

        if keyword.lower() in text:

            return True

    return False


# ============================================================
# 频道分类
# ============================================================

def classify_channel(channel):

    text = " ".join([
        channel.get("name", ""),
        channel.get("tvg_id", ""),
        channel.get("group", ""),
    ])

    # 4K 必须优先判断
    if contains_keyword(
        text,
        CCTV_4K_KEYWORDS
    ):

        return "CCTV-4K"

    if contains_keyword(
        text,
        PHOENIX_KEYWORDS
    ):

        return "凤凰卫视"

    if contains_keyword(
        text,
        GUANGDONG_KEYWORDS
    ):

        return "广东"

    if contains_keyword(
        text,
        SPORTS_KEYWORDS
    ):

        return "体育"

    if contains_keyword(
        text,
        CCTV_KEYWORDS
    ):

        return "央视"

    if contains_keyword(
        text,
        HONG_KONG_KEYWORDS
    ):

        return "香港"

    if contains_keyword(
        text,
        MACAU_KEYWORDS
    ):

        return "澳门"

    if contains_keyword(
        text,
        TAIWAN_KEYWORDS
    ):

        return "台湾"

    return "其他"


# ============================================================
# URL 基础检查
# ============================================================

def valid_url(url):

    return (
        url.startswith("http://")
        or url.startswith("https://")
    )


# ============================================================
# 基础清洗
# ============================================================

def clean_channels(channels):

    result = []

    seen_urls = set()

    for channel in channels:

        url = channel["url"].strip()

        name = channel["name"].strip()

        if not url:
            continue

        if not name:
            continue

        if not valid_url(url):
            continue

        if url in seen_urls:
            continue

        seen_urls.add(url)

        channel["category"] = classify_channel(
            channel
        )

        result.append(channel)

    return result


# ============================================================
# M3U 安全写入
# ============================================================

def write_m3u(
    filename,
    channels
):

    lines = [
        "#EXTM3U"
    ]

    for channel in channels:

        name = channel["name"]

        tvg_id = channel["tvg_id"]

        group = channel["category"]

        logo = channel["logo"]

        url = channel["url"]

        lines.append(
            f'#EXTINF:-1 '
            f'tvg-id="{tvg_id}" '
            f'tvg-logo="{logo}" '
            f'group-title="{group}",'
            f'{name}'
        )

        lines.append(url)

    filename.write_text(
        "\n".join(lines),
        encoding="utf-8"
    )

    print(
        f"[生成] {filename} "
        f"({len(channels)} 个)"
    )


# ============================================================
# 主程序
# ============================================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    all_channels = []

    # --------------------------------------------------------
    # 抓取多个公开来源
    # --------------------------------------------------------

    for source in SOURCE_URLS:

        try:

            text = download(source)

            channels = parse_m3u(text)

            print(
                f"[解析] {len(channels)} 个"
            )

            all_channels.extend(
                channels
            )

            time.sleep(1)

        except Exception as error:

            print(
                f"[失败] {source}"
            )

            print(error)

    print(
        f"[原始总数] "
        f"{len(all_channels)}"
    )

    # --------------------------------------------------------
    # 清洗
    # --------------------------------------------------------

    channels = clean_channels(
        all_channels
    )

    print(
        f"[清洗后] "
        f"{len(channels)}"
    )

    # --------------------------------------------------------
    # 分类
    # --------------------------------------------------------

    categories = {}

    for channel in channels:

        category = channel[
            "category"
        ]

        categories.setdefault(
            category,
            []
        ).append(channel)

    # --------------------------------------------------------
    # 输出各分类 M3U
    # --------------------------------------------------------

    file_map = {

        "央视":
            "cctv.m3u",

        "CCTV-4K":
            "cctv_4k.m3u",

        "凤凰卫视":
            "phoenix.m3u",

        "香港":
            "hongkong.m3u",

        "澳门":
            "macau.m3u",

        "台湾":
            "taiwan.m3u",

        "广东":
            "guangdong.m3u",

        "体育":
            "sports.m3u",

        "其他":
            "other.m3u",
    }

    for category, filename in file_map.items():

        category_channels = categories.get(
            category,
            []
        )

        write_m3u(
            OUTPUT_DIR / filename,
            category_channels
        )

    # --------------------------------------------------------
    # 全部频道
    # --------------------------------------------------------

    write_m3u(
        OUTPUT_DIR / "all.m3u",
        channels
    )

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    summary = {

        "generated_at":
            int(time.time()),

        "total":
            len(channels),

        "categories": {
            category: len(items)
            for category, items
            in categories.items()
        },

        "channels":
            channels,
    }

    RAW_FILE.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("")
    print("==============================")
    print(" IPTV 自动发现完成")
    print("==============================")

    for category in sorted(
        categories
    ):

        print(
            f"{category}: "
            f"{len(categories[category])}"
        )


if __name__ == "__main__":

    main()
