from urllib.request import Request, urlopen
from pathlib import Path
import re
import json
import time


# ============================================================
# 配置
# ============================================================

SOURCE_URL = (
    "https://iptv-org.github.io/iptv/index.m3u"
)

OUTPUT_DIR = Path("output")
RAW_FILE = OUTPUT_DIR / "discovered.json"

TIMEOUT = 20


# ============================================================
# 精确频道 ID
#
# 铁规则：
# 只按照 tvg-id 判断。
# 不根据频道名称猜测。
# 不使用 Phoenix / Guangdong / Sports 等关键词。
# ============================================================

EXACT_CHANNELS = {

    # --------------------------------------------------------
    # CCTV
    # --------------------------------------------------------

    "CCTV1.cn",
    "CCTV2.cn",
    "CCTV3.cn",
    "CCTV4.cn",
    "CCTV5.cn",
    "CCTV5Plus.cn",
    "CCTV6.cn",
    "CCTV7.cn",
    "CCTV8.cn",
    "CCTV9.cn",
    "CCTV10.cn",
    "CCTV11.cn",
    "CCTV12.cn",
    "CCTV13.cn",
    "CCTV14.cn",
    "CCTV15.cn",
    "CCTV16.cn",
    "CCTV17.cn",

    # CCTV 4K
    "CCTV4K.cn",

    # --------------------------------------------------------
    # 凤凰卫视
    # --------------------------------------------------------

    "PhoenixChineseChannel.hk",
    "PhoenixInfoNewsChannel.hk",

    # --------------------------------------------------------
    # 广东
    # --------------------------------------------------------

    "GuangdongTV.cn",
    "GuangdongNews.cn",
    "GuangdongZhujiang.cn",
    "GuangdongPearlRiver.cn",
    "GuangdongFilm.cn",
    "GuangdongPublic.cn",
    "GuangdongChildren.cn",
    "GuangdongSports.cn",
}


# ============================================================
# 下载 M3U
# ============================================================

def download(url):

    print(
        f"[下载] {url}"
    )

    request = Request(
        url,
        headers={
            "User-Agent":
                "Mozilla/5.0 "
                "(compatible; IPTV-Auto/3.0)"
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
# 判断目标频道
# ============================================================

def is_target_channel(tvg_id):

    if not tvg_id:
        return False

    return (
        tvg_id.strip()
        in EXACT_CHANNELS
    )


# ============================================================
# 分类
# ============================================================

def classify_channel(tvg_id):

    tvg_id_lower = (
        tvg_id.lower()
    )

    # CCTV 4K
    if tvg_id_lower == "cctv4k.cn":

        return "央视4K"

    # CCTV
    if tvg_id_lower.startswith(
        "cctv"
    ):

        return "央视"

    # 凤凰
    if tvg_id in {
        "PhoenixChineseChannel.hk",
        "PhoenixInfoNewsChannel.hk",
    }:

        return "凤凰卫视"

    # 广东体育
    if tvg_id == "GuangdongSports.cn":

        return "广东体育"

    # 广东
    if tvg_id.startswith(
        "Guangdong"
    ):

        return "广东"

    return "其他"


# ============================================================
# 解析 EXTINF
# ============================================================

def parse_extinf(line):

    tvg_id_match = re.search(
        r'tvg-id="([^"]*)"',
        line,
        re.IGNORECASE
    )

    if not tvg_id_match:

        return None

    tvg_id = (
        tvg_id_match
        .group(1)
        .strip()
    )

    group_match = re.search(
        r'group-title="([^"]*)"',
        line,
        re.IGNORECASE
    )

    logo_match = re.search(
        r'tvg-logo="([^"]*)"',
        line,
        re.IGNORECASE
    )

    if "," in line:

        name = (
            line
            .split(",", 1)[1]
            .strip()
        )

    else:

        name = tvg_id

    return {

        "tvg_id":
            tvg_id,

        "name":
            name,

        "group":
            (
                group_match.group(1)
                if group_match
                else ""
            ),

        "logo":
            (
                logo_match.group(1)
                if logo_match
                else ""
            ),
    }


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

        # ----------------------------------------------------
        # EXTINF
        # ----------------------------------------------------

        if line.startswith(
            "#EXTINF"
        ):

            current_info = line

            continue

        # ----------------------------------------------------
        # URL
        # ----------------------------------------------------

        if (
            current_info
            and not line.startswith("#")
            and (
                line.startswith(
                    "http://"
                )
                or
                line.startswith(
                    "https://"
                )
            )
        ):

            info = parse_extinf(
                current_info
            )

            if not info:

                current_info = None

                continue

            tvg_id = info[
                "tvg_id"
            ]

            # ------------------------------------------------
            # 精确过滤
            # ------------------------------------------------

            if not is_target_channel(
                tvg_id
            ):

                current_info = None

                continue

            category = classify_channel(
                tvg_id
            )

            channels.append({

                "name":
                    info["name"],

                "tvg_id":
                    tvg_id,

                "logo":
                    info["logo"],

                "group":
                    info["group"],

                "category":
                    category,

                "url":
                    line,
            })

            current_info = None

    return channels


# ============================================================
# 去重
#
# 同一个 tvg-id + URL 才算重复。
#
# 同一频道不同 URL 必须保留，
# 因为后面的 check.py 要从多个源里选择最佳源。
# ============================================================

def clean_channels(channels):

    result = []

    seen = set()

    for channel in channels:

        key = (
            channel["tvg_id"],
            channel["url"],
        )

        if key in seen:

            continue

        seen.add(
            key
        )

        result.append(
            channel
        )

    return result


# ============================================================
# 统计
# ============================================================

def make_statistics(channels):

    statistics = {}

    for channel in channels:

        category = channel[
            "category"
        ]

        statistics[
            category
        ] = (
            statistics.get(
                category,
                0
            ) + 1
        )

    return statistics


# ============================================================
# 目标频道命中统计
# ============================================================

def make_channel_statistics(channels):

    result = {}

    for channel in channels:

        tvg_id = channel[
            "tvg_id"
        ]

        result[tvg_id] = (
            result.get(
                tvg_id,
                0
            ) + 1
        )

    return result


# ============================================================
# 主程序
# ============================================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print(
        "========================================"
    )

    print(
        " IPTV 精确频道发现系统 v3"
    )

    print(
        "========================================"
    )

    # --------------------------------------------------------
    # 下载
    # --------------------------------------------------------

    text = download(
        SOURCE_URL
    )

    print(
        f"[下载完成] "
        f"{len(text):,} 字符"
    )

    # --------------------------------------------------------
    # 解析
    # --------------------------------------------------------

    print(
        "[解析] 开始解析 M3U"
    )

    channels = parse_m3u(
        text
    )

    print(
        f"[精确筛选] "
        f"{len(channels)}"
    )

    # --------------------------------------------------------
    # 去重
    # --------------------------------------------------------

    channels = clean_channels(
        channels
    )

    print(
        f"[去重后] "
        f"{len(channels)}"
    )

    # --------------------------------------------------------
    # 分类统计
    # --------------------------------------------------------

    statistics = make_statistics(
        channels
    )

    print(
        "----------------------------------------"
    )

    print(
        "[分类统计]"
    )

    if statistics:

        for category, count in sorted(
            statistics.items()
        ):

            print(
                f"  {category}: {count}"
            )

    else:

        print(
            "  没有匹配频道"
        )

    print(
        "----------------------------------------"
    )

    # --------------------------------------------------------
    # 频道 ID 统计
    # --------------------------------------------------------

    channel_statistics = (
        make_channel_statistics(
            channels
        )
    )

    print(
        "[频道 ID]"
    )

    if channel_statistics:

        for tvg_id, count in sorted(
            channel_statistics.items()
        ):

            print(
                f"  {tvg_id}: {count}"
            )

    else:

        print(
            "  没有匹配 ID"
        )

    print(
        "----------------------------------------"
    )

    # --------------------------------------------------------
    # 输出
    # --------------------------------------------------------

    data = {

        "generated_at":
            int(time.time()),

        "source":
            SOURCE_URL,

        "channel_count":
            len(channels),

        "statistics":
            statistics,

        "channel_statistics":
            channel_statistics,

        "channels":
            channels,
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
        f"[完成] {RAW_FILE}"
    )

    print(
        "========================================"
    )


if __name__ == "__main__":

    main()
