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

RAW_FILE = (
    OUTPUT_DIR / "discovered.json"
)

TIMEOUT = 20


# ============================================================
# 精确频道 ID
#
# 注意：
#
# iptv-org 的实际 Stream ID 可能是：
#
# CCTV1.cn
# CCTV1.cn@HD
# CCTV1.cn@SD
#
# 因此我们只对 @ 前面的「基础 Channel ID」
# 进行精确匹配。
#
# 绝不使用频道名称关键词匹配。
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
# 下载
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
                "(compatible; IPTV-Auto/4.0)"
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
# 解析 Stream ID
#
# 例如：
#
# CCTV1.cn
# CCTV1.cn@HD
# CCTV1.cn@SD
#
# 返回：
#
# channel_id = CCTV1.cn
# feed       = HD / SD / None
# ============================================================

def parse_stream_id(tvg_id):

    tvg_id = (
        tvg_id or ""
    ).strip()

    if not tvg_id:

        return "", ""

    if "@" in tvg_id:

        channel_id, feed = (
            tvg_id.split(
                "@",
                1
            )
        )

        return (
            channel_id.strip(),
            feed.strip()
        )

    return (
        tvg_id,
        ""
    )


# ============================================================
# 精确频道判断
# ============================================================

def is_target_channel(tvg_id):

    channel_id, feed = (
        parse_stream_id(
            tvg_id
        )
    )

    if not channel_id:

        return False

    return (
        channel_id
        in EXACT_CHANNELS
    )


# ============================================================
# 分类
# ============================================================

def classify_channel(
    channel_id
):

    channel_id_lower = (
        channel_id.lower()
    )


    # --------------------------------------------------------
    # CCTV 4K
    # --------------------------------------------------------

    if (
        channel_id_lower
        == "cctv4k.cn"
    ):

        return "央视4K"


    # --------------------------------------------------------
    # CCTV
    # --------------------------------------------------------

    if channel_id_lower.startswith(
        "cctv"
    ):

        return "央视"


    # --------------------------------------------------------
    # 凤凰
    # --------------------------------------------------------

    if channel_id in {

        "PhoenixChineseChannel.hk",

        "PhoenixInfoNewsChannel.hk",

    }:

        return "凤凰卫视"


    # --------------------------------------------------------
    # 广东体育
    # --------------------------------------------------------

    if (
        channel_id
        == "GuangdongSports.cn"
    ):

        return "广东体育"


    # --------------------------------------------------------
    # 广东
    # --------------------------------------------------------

    if channel_id.startswith(
        "Guangdong"
    ):

        return "广东"


    return "其他"


# ============================================================
# EXTINF 信息解析
# ============================================================

def parse_extinf(
    line
):

    # --------------------------------------------------------
    # tvg-id
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # group-title
    # --------------------------------------------------------

    group_match = re.search(

        r'group-title="([^"]*)"',
        line,
        re.IGNORECASE

    )


    group = (

        group_match.group(1)

        if group_match

        else ""

    )


    # --------------------------------------------------------
    # tvg-logo
    # --------------------------------------------------------

    logo_match = re.search(

        r'tvg-logo="([^"]*)"',
        line,
        re.IGNORECASE

    )


    logo = (

        logo_match.group(1)

        if logo_match

        else ""

    )


    # --------------------------------------------------------
    # 频道名称
    # --------------------------------------------------------

    if "," in line:

        name = (
            line
            .split(
                ",",
                1
            )[1]
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
            group,

        "logo":
            logo,

    }


# ============================================================
# 解析 M3U
# ============================================================

def parse_m3u(
    text
):

    lines = [

        line.strip()

        for line
        in text.splitlines()

        if line.strip()

    ]


    channels = []

    current_info = None


    for line in lines:


        # ====================================================
        # EXTINF
        # ====================================================

        if line.startswith(
            "#EXTINF"
        ):

            current_info = line

            continue


        # ====================================================
        # URL
        # ====================================================

        if (

            current_info

            and not line.startswith(
                "#"
            )

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


            # =================================================
            # 精确频道过滤
            # =================================================

            if not is_target_channel(
                tvg_id
            ):

                current_info = None

                continue


            # =================================================
            # 拆分 Channel ID / Feed
            # =================================================

            channel_id, feed = (
                parse_stream_id(
                    tvg_id
                )
            )


            # =================================================
            # 分类
            # =================================================

            category = (
                classify_channel(
                    channel_id
                )
            )


            # =================================================
            # 保存
            # =================================================

            channels.append({

                "name":
                    info["name"],

                "tvg_id":
                    tvg_id,

                "channel_id":
                    channel_id,

                "feed":
                    feed,

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
# 同一个：
#
# channel_id + tvg_id + URL
#
# 才算重复。
#
# 同频道不同 URL 必须保留。
# ============================================================

def clean_channels(
    channels
):

    result = []

    seen = set()


    for channel in channels:

        key = (

            channel[
                "channel_id"
            ],

            channel[
                "tvg_id"
            ],

            channel[
                "url"
            ],

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
# 分类统计
# ============================================================

def make_statistics(
    channels
):

    statistics = {}


    for channel in channels:

        category = (
            channel[
                "category"
            ]
        )


        statistics[
            category
        ] = (

            statistics.get(
                category,
                0
            )

            + 1

        )


    return statistics


# ============================================================
# Channel ID 统计
# ============================================================

def make_channel_statistics(
    channels
):

    result = {}


    for channel in channels:

        channel_id = (
            channel[
                "channel_id"
            ]
        )


        result[
            channel_id
        ] = (

            result.get(
                channel_id,
                0
            )

            + 1

        )


    return result


# ============================================================
# Feed 统计
# ============================================================

def make_feed_statistics(
    channels
):

    result = {}


    for channel in channels:

        channel_id = (
            channel[
                "channel_id"
            ]
        )

        feed = (
            channel[
                "feed"
            ]
        )


        key = (

            channel_id,

            feed
            or "(无Feed)"

        )


        result[
            f"{key[0]}@{key[1]}"
        ] = (

            result.get(
                f"{key[0]}@{key[1]}",
                0
            )

            + 1

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
        " IPTV 精确频道发现系统 v4"
    )

    print(
        "========================================"
    )


    # ========================================================
    # 下载
    # ========================================================

    text = download(
        SOURCE_URL
    )


    print(
        f"[下载完成] "
        f"{len(text):,} 字符"
    )


    # ========================================================
    # 解析
    # ========================================================

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


    # ========================================================
    # 去重
    # ========================================================

    channels = clean_channels(
        channels
    )


    print(
        f"[去重后] "
        f"{len(channels)}"
    )


    # ========================================================
    # 分类统计
    # ========================================================

    statistics = (
        make_statistics(
            channels
        )
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


    # ========================================================
    # Channel ID
    # ========================================================

    channel_statistics = (
        make_channel_statistics(
            channels
        )
    )


    print(
        "----------------------------------------"
    )

    print(
        "[Channel ID]"
    )


    if channel_statistics:

        for channel_id, count in sorted(
            channel_statistics.items()
        ):

            print(
                f"  {channel_id}: {count}"
            )

    else:

        print(
            "  没有匹配 ID"
        )


    # ========================================================
    # Feed
    # ========================================================

    feed_statistics = (
        make_feed_statistics(
            channels
        )
    )


    print(
        "----------------------------------------"
    )

    print(
        "[Feed]"
    )


    if feed_statistics:

        for feed, count in sorted(
            feed_statistics.items()
        ):

            print(
                f"  {feed}: {count}"
            )

    else:

        print(
            "  没有 Feed"
        )


    # ========================================================
    # 输出 JSON
    # ========================================================

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

        "feed_statistics":
            feed_statistics,

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
        "----------------------------------------"
    )

    print(
        f"[完成] {RAW_FILE}"
    )

    print(
        "========================================"
    )


if __name__ == "__main__":

    main()
